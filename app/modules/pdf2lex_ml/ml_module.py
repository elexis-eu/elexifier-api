import flask
from flask import after_this_request
import os
import json
import requests
import traceback
import lxml
import lxml.etree

from app import app, db, celery
from app.user.models import User
from app.user.controllers import check_auth
import app.dataset.controllers as Datasets
import app.modules.support as ErrorLog
from app.modules.error_handling import InvalidUsage
from app.modules.lexonomy import make_lexonomy_request, get_lex_xml

# ML scripts
from app.modules.pdf2lex_ml.xml2json_ML import xml2json
from app.modules.pdf2lex_ml.train_ML import train_ML
from app.modules.pdf2lex_ml.json2xml_ML import json2xml
from app.modules.pdf2lex_ml.tokenized2TEI import tokenized2TEI


# TODO: should this be here?
from sqlalchemy import create_engine
db_uri = app.config['SQLALCHEMY_DATABASE_URI']
engine = create_engine(db_uri, encoding='utf-8')
#engine = None

def ds_sendML_to_lexonomy(uid, dsid):
    #user = controllers.user_data(db, uid)
    user = db.session.query(User).filter_by(id=uid).first()
    dataset = Datasets.list_datasets(engine, uid, dsid=dsid)

    if dataset['lexonomy_ml_delete'] is not None:
        requests.post(dataset['lexonomy_ml_delete'],
                      headers={"Content-Type": 'application/json',
                               "Authorization": app.config['LEXONOMY_AUTH_KEY']})

    request_data = {
        'xml_file': '/api/lexonomy/' + str(uid) + '/download/' + str(dsid) + "?ml=True",
        'email': user.email,
        'filename': dataset['name'] + ' - preview',
        'type': 'preview',
        'url': app.config['URL'],
        'return_to': ""  # remove if no longer required
    }

    if user.password_hash is None:  # ske user
        request_data['ske_user'] = True
    else:
        request_data['ske_user'] = False

    print('Starting asynchronous request to Lexonomy')
    task = make_lexonomy_request.apply_async(args=[uid, dsid, request_data], kwargs={"ml": True}, countdown=0)

    status = 'preview_Starting'
    msg = 'OK'
    # Update dataset status
    Datasets.set_dataset_status(engine, uid, dsid, status)

    return flask.make_response({'message': msg, 'dsid': dsid, 'status': status, 'test_request': request_data}, 200)


@celery.task
def run_pdf2lex_ml_scripts(uid, dsid, xml_raw, xml_lex, xml_out):
    temp_fname = xml_raw.split('.xml')[0]
    json_ml_in = temp_fname + '-ML-IN.json'
    json_ml_out = temp_fname + '-ML-OUT.json'

    # Create files
    open(json_ml_in, 'a').close()
    open(json_ml_out, 'a').close()
    open(xml_out, 'a').close()

    print("xml2json_ML")
    try:
        xml2json(xml_raw, xml_lex, json_ml_in)
        Datasets.set_dataset_status(engine, uid, dsid, "ML_Format")
    except Exception as e:
        Datasets.set_dataset_status(engine, uid, dsid, "Lex2ML_Error")
        Datasets.dataset_ml_task_id(engine, dsid, set=True, task_id="")
        print(traceback.format_exc())
        ErrorLog.add_error_log(db, dsid, tag='ml_error', message=traceback.format_exc())
        return

    print("train_ML")
    try:
        _, report = train_ML(json_ml_in, json_ml_out, '')
        ErrorLog.add_error_log(db, dsid, tag='ml_finished', message=report)
        Datasets.set_dataset_status(engine, uid, dsid, "ML_Annotated")
    except Exception as e:
        Datasets.set_dataset_status(engine, uid, dsid, "ML_Error")
        Datasets.dataset_ml_task_id(engine, dsid, set=True, task_id="")
        print(traceback.format_exc())
        ErrorLog.add_error_log(db, dsid, tag='ml_error', message=traceback.format_exc())
        return

    print("json2xml_ML")
    try:
        json2xml(json_ml_out, xml_raw, xml_out)
        Datasets.set_dataset_status(engine, uid, dsid, "Lex_Format")
    except Exception as e:
        Datasets.set_dataset_status(engine, uid, dsid, "ML2Lex_Error")
        Datasets.dataset_ml_task_id(engine, dsid, set=True, task_id="")
        print(traceback.format_exc())
        ErrorLog.add_error_log(db, dsid, tag='ml_error', message=traceback.format_exc())
        return

    Datasets.dataset_ml_task_id(engine, dsid, set=True, task_id="")
    os.remove(json_ml_in)
    os.remove(json_ml_out)
    return


# --- views ---
@celery.task
@app.route('/api/ml/<int:dsid>', methods=['GET'])
def ds_machine_learning(dsid):
    token = flask.request.headers.get('Authorization')
    uid = User.decode_auth_token(token)

    xml_format = flask.request.args.get('xml_format', default=None, type=str) == 'True'
    get_file = flask.request.args.get('get_file', default=None, type=str) == 'True'
    run_ml = flask.request.args.get('run_ml', default=None, type=str) == 'True'
    send_file = flask.request.args.get('send_file', default=None, type=str) == 'True'

    # TODO: Save paths to DB
    dataset = Datasets.list_datasets(engine, uid, dsid=dsid)
    xml_lex = dataset['xml_lex']
    xml_raw = dataset['xml_file_path']
    print('xml_lex:', xml_lex, 'xml_raw:', xml_raw)

    if xml_lex == None:
        xml_ml_out = None
    else:
        xml_ml_out = xml_lex[:-4] + "-ML_OUT.xml"
    Datasets.dataset_add_ml_paths(engine, uid, dsid, dataset['xml_lex'], xml_ml_out)

    # Check if all params are None
    if xml_format is None and get_file is None and run_ml is None and send_file is None:
        raise InvalidUsage("Invalid API call. No params.", status_code=422, enum="GET_ERROR")
    # Check if to many params
    elif xml_format and (get_file or run_ml or send_file):
        raise InvalidUsage("Invalid API call. Can't work on file and send it.", status_code=422, enum="GET_ERROR")

    dataset = Datasets.list_datasets(engine, uid, dsid=dsid)
    dataset['ml_task_id'] = Datasets.dataset_ml_task_id(engine, dsid)
    status = dataset['status']

    # Check if dataset has ml_task, then send status
    if dataset['ml_task_id']:
        return flask.make_response({"message": "File is still processing.", "dsid": dsid, "Status": status}, 200)

    # Check if user wants file and then return it
    if xml_format and status not in ['Starting_ML', 'ML_Format', 'ML_Annotated', 'Lex2ML_Error', 'ML_Error',
                                     'ML2Lex_Error']:
        # TODO: get the latest annotated version from Lexonomy
        Datasets.set_dataset_status(engine, uid, dsid, 'Preparing_download')
        tmp_file = xml_ml_out.split(".xml")[0] + "_TEI.xml"
        character_map = Datasets.dataset_character_map(db, dsid)
        tokenized2TEI(xml_ml_out, tmp_file, character_map)

        @after_this_request
        def after(response):
            response.headers['x-suggested-filename'] = filename
            response.headers.add('Access-Control-Expose-Headers', '*')
            Datasets.set_dataset_status(engine, uid, dsid, 'Lex_Format')
            os.remove(tmp_file)
            return response

        filename = dataset['name'].split('.')[0] + '-transformed.xml'
        return flask.send_file(tmp_file, attachment_filename=filename, as_attachment=True)
    elif xml_format:
        raise InvalidUsage("File is not ready. Try running ML again", status_code=202, enum="STATUS_ERROR")

    # Run ML scripts
    if get_file:  # Get file from Lexonomy
        status = "Lexonomy_Annotated"
        get_lex_xml(uid, dsid)
        Datasets.set_dataset_status(engine, uid, dsid, status)

    elif run_ml:
        status = "Starting_ML"
        Datasets.set_dataset_status(engine, uid, dsid, status)
        task = run_pdf2lex_ml_scripts.apply_async(args=[uid, dsid, xml_raw, xml_lex, xml_ml_out], countdown=0)
        Datasets.dataset_ml_task_id(engine, dsid, set=True, task_id=task.id)

    elif send_file:  # Send file to Lexonomy
        # stauts = "ML_Annotated_@Lexonomy"
        ds_sendML_to_lexonomy(uid, dsid)
        # controllers.set_dataset_status(engine, uid, dsid, status)

    return flask.make_response({"message": "OK", "dsid": dsid, "Status": status}, 200)


@app.route('/api/ml/<int:dsid>', methods=['DELETE'])
def delete_ml(dsid):
    token = flask.request.headers.get('Authorization')
    uid = User.decode_auth_token(token)
    dataset = Datasets.list_datasets(engine, uid, dsid=dsid)

    local = flask.request.args.get('local', default=None, type=str) == 'True'

    if local:
        try:
            print("Deleting local ml files uid: {0:s}, dsid: {1:s}".format(str(uid), str(dsid)))
            json_ml_in = '/var/www/elexifier-api/app/media/ML-IN-{}.json'.format(str(dsid))
            json_ml_out = '/var/www/elexifier-api/app/media/ML-OUT-{}.json'.format(str(dsid))
            os.remove(json_ml_in)
            os.remove(json_ml_out)
            if dataset['xml_lex'] != "":
                os.remove(dataset['xml_lex'])
            if dataset['xml_ml_out'] != "":
                os.remove(dataset['xml_ml_out'])
        except:
            pass
        Datasets.dataset_add_ml_paths(engine, uid, dsid, '', '')

    else:
        if dataset['lexonomy_ml_delete'] is not None:
            requests.post(dataset['lexonomy_ml_delete'],
                          headers={"Content-Type": 'application/json',
                                   "Authorization": app.config['LEXONOMY_AUTH_KEY']})

        Datasets.dataset_add_ml_lexonomy_access(db, dsid)

    return flask.make_response({'message': 'OK'}, 200)


@check_auth
@app.route('/api/ml/<int:dsid>/character_map', methods=['POST'])
def char_map(dsid):
    character_map = flask.request.json.get('character_map', None)
    Datasets.dataset_character_map(db, dsid, set=True, character_map=character_map)
    return flask.make_response({'msg': 'ok'}, 200)


@check_auth
@app.route('/api/ml/<int:dsid>/character_map', methods=['GET'])
def get_char_map(dsid):
    character_map = Datasets.dataset_character_map(db, dsid)
    return flask.make_response({'character_map': character_map}, 200)

"""
# ---- lexonomy ----

# --- controllers ---
def first_n_pages(original_file, out_file, n):
    # Create root element and add attributes
    root_element = lxml.etree.fromstring('<DOCUMENT></DOCUMENT>')
    root_element.attrib['filename'] = original_file.split("/")[-1]
    # Create body and metadata
    body = lxml.etree.fromstring('<BODY></BODY>')
    metadata = lxml.etree.fromstring('<METADATA/>')
    metadata.text = 'pages 1-{0}'.format(n)
    body.append(metadata)

    # Parse original file and get BODY
    tree = lxml.etree.parse(original_file).getroot()
    tree = tree.xpath('.//BODY')[0]

    # Extract tokens from body
    for token in tree:
        if token.tag == 'METADATA':
            # Skip metadata, because we have a new one
            continue
        page_num = int(token.attrib['page'])
        if page_num <= n:
            body.append(token)

    root_element.append(body)
    out_xml = lxml.etree.tostring(root_element, pretty_print=True, encoding='unicode')
    file = open(out_file, 'w')
    file.write(out_xml)
    file.close()
    return


def additional_n_pages(original_file, lex_file, out_file, n):
    # Parse Lexonomy file and count bodies
    lex_tree = lxml.etree.parse(lex_file).getroot()
    last_page_num = len(lex_tree) * n
    # Insert metadata into lexonomy bodies
    c = 1
    for body in lex_tree:
        metadata = lxml.etree.fromstring('<METADATA/>')
        metadata.text = 'pages {0}-{1}'.format(c, c + n - 1)
        body.insert(0, metadata)
        c += n

    # Create root element and add attributes
    root_element = lxml.etree.fromstring('<DOCUMENT></DOCUMENT>')
    root_element.attrib['filename'] = original_file.split("/")[-1]
    # Create body and metadata
    body = lxml.etree.fromstring('<BODY></BODY>')
    metadata = lxml.etree.fromstring('<METADATA/>')
    metadata.text = 'pages {0}-{1}'.format(last_page_num + 1, last_page_num + n)
    body.append(metadata)

    # Parse original file and get BODY
    tree = lxml.etree.parse(original_file).getroot()
    tree = tree.xpath('.//BODY')[0]

    # Extract tokens from body
    for token in tree:
        if token.tag == 'METADATA':
            # Skip metadata, because we have a new one
            continue
        page_num = int(token.attrib['page'])
        if last_page_num < page_num <= (last_page_num + n):
            body.append(token)

    # Add lexonomy BODY-ies to root_element
    for lex_entry in lex_tree:
        root_element.append(lex_entry)

    root_element.append(body)
    out_xml = lxml.etree.tostring(root_element, pretty_print=True, encoding='unicode')
    file = open(out_file, 'w')
    file.write(out_xml)
    file.close()


def split_preview(anno_file, out_file, n):
    anno_tree = lxml.etree.parse(anno_file).getroot()
    new_root = lxml.etree.Element('DOCUMENT')
    body = lxml.etree.Element('BODY')
    metadata = lxml.etree.Element('METADATA')
    count = 0
    metadata.text = 'Entries 1 - {}'.format(n)
    body.append(metadata)

    for child in anno_tree:
        body.append(child)
        count += 1
        if count % n == 0 and count != 0:
            new_root.append(body)
            body = lxml.etree.Element('BODY')
            metadata = lxml.etree.Element('METADATA')
            metadata.text = 'Entries {0} - {1}'.format(count+1, count+n)
            body.append(metadata)

    new_root.append(body)
    out_xml = lxml.etree.tostring(new_root, pretty_print=True, encoding='unicode')
    file = open(out_file, 'w')
    file.write(out_xml)
    file.close()
    return


def get_lex_xml(uid, dsid):
    dataset = Datasets.list_datasets(engine, uid, dsid=dsid)
    xml_lex = dataset['xml_file_path'][:-4] + "-LEX.xml"
    Datasets.dataset_add_ml_paths(engine, uid, dsid, xml_lex, dataset['xml_ml_out'])

    request_headers = { "Authorization": app.config['LEXONOMY_AUTH_KEY'], "Content-Type": 'application/json' }
    response = requests.get(dataset['lexonomy_access'], headers=request_headers)

    #data = re.search("<BODY.*<\/BODY>", response.text).group()

    f = open(xml_lex, "w")
    f.write(response.text)
    f.close()
    return


@celery.task
def make_lexonomy_request(uid, dsid, request_data, ml=False):
    # Send request async and save links to db
    response = requests.post('https://lexonomy.elex.is/elexifier/new',
                             headers={"Content-Type": 'application/json', "Authorization": app.config['LEXONOMY_AUTH_KEY']},
                             data=json.dumps(request_data))
    if ml:
        status_prepend = "preview_"
    else:
        status_prepend = "annotate_"

    resp_js = json.loads(response.text)
    if resp_js['error'] == 'email not found':
        Datasets.set_dataset_status(engine, uid, dsid, status_prepend + "Lexonomy_Error")
        return

    try:
        if ml:
            Datasets.dataset_add_ml_lexonomy_access(db, dsid, resp_js['access_link'], resp_js['edit_link'], resp_js['delete_link'], resp_js['status_link'])
        else:
            # Update dataset in db
            Datasets.dataset_add_lexonomy_access(db, dsid, resp_js['access_link'], resp_js['edit_link'], resp_js['delete_link'], resp_js['status_link'])
    except:
        Datasets.set_dataset_status(engine, uid, dsid, status_prepend + "Lexonomy_Error")

    Datasets.set_dataset_status(engine, uid, dsid, status_prepend + 'Ready')
    return


# --- views --
@app.route('/api/lexonomy/<int:uid>/download/<int:dsid>', methods=['GET'])
def lexonomy_download(uid, dsid):
    if flask.request.headers.get('Authorization') != app.config['LEXONOMY_AUTH_KEY']:
        raise InvalidUsage("Shared secret is not valid!", status_code=401, enum='UNAUTHORIZED')

    ml = flask.request.args.get('ml', default="False", type=str) == "True"
    additional_pages = flask.request.args.get('add_pages', default="False", type=str) == "True"
    if ml:  # Set datasets status
        Datasets.set_dataset_status(engine, uid, dsid, 'preview_Processing')
    else:
        Datasets.set_dataset_status(engine, uid, dsid, 'annotate_Processing')

    dataset = Datasets.list_datasets(engine, uid, dsid=dsid)
    temp_fname = dataset['xml_file_path'].split(".xml")[0] + "-tmp.xml"

    @after_this_request
    def remove_file(response):
        os.remove(temp_fname)
        return response

    if ml:
        # Send ml file
        split_preview(dataset['xml_ml_out'], temp_fname, 100)
        return flask.send_file(temp_fname, attachment_filename=dataset['xml_ml_out'].split('/')[-1], as_attachment=True)

    elif not additional_pages:
        # Send first 20 pages file
        first_n_pages(dataset['xml_file_path'], temp_fname, 20)
        return flask.send_file(temp_fname, attachment_filename=dataset['xml_file_path'].split('/')[-1], as_attachment=True)
    else:
        # Send additional 20 pages file
        additional_n_pages(dataset['xml_file_path'], dataset['xml_lex'], temp_fname, 20)
        return flask.send_file(temp_fname, attachment_filename=dataset['xml_file_path'].split('/')[-1], as_attachment=True)


@app.route('/api/lexonomy/<int:dsid>', methods=['GET'])
def ds_send_to_lexonomy(dsid):
    token = flask.request.headers.get('Authorization')
    uid = User.decode_auth_token(token)

    #user = controllers.user_data(db, uid)
    user = db.session.query(User).filter_by(id=id).first
    db.session.close()
    dataset = Datasets.list_datasets(engine, uid, dsid=dsid)

    additional_pages = flask.request.args.get('add_pages', default='false', type=str).lower() == 'true'
    if additional_pages:
        # get file from lexonomy and save it
        get_lex_xml(uid, dsid)
        #return _j({'message': 'test_ok', 'dsid': dsid})

    if dataset['lexonomy_delete'] is not None:
        requests.post(dataset['lexonomy_delete'],
                      headers={"Content-Type": 'application/json',
                               "Authorization": app.config['LEXONOMY_AUTH_KEY']})

    request_data = {
        'xml_file': '/api/lexonomy/' + str(uid) + '/download/' + str(dsid),
        'email': user.email,
        'filename': dataset['name'] + ' - annotate',
        'type': 'edit',
        'url': app.config['URL'],
        'return_to': ""  # remove if no longer required
    }

    if additional_pages:
        request_data['xml_file'] += "?add_pages=True"

    if user.password_hash is None:  # ske user
        request_data['ske_user'] = True
    else:
        request_data['ske_user'] = False

    print('Starting asynchronous request to Lexonomy')
    task = make_lexonomy_request.apply_async(args=[uid, dsid, request_data], countdown=0)

    status = 'annotate_Starting'
    msg = 'OK'
    # Update dataset status
    Datasets.set_dataset_status(engine, uid, dsid, status)

    return flask.make_response({'message': msg, 'dsid': dsid, 'status': status, 'test_request': request_data}, 200)


@app.route('/api/lexonomy/<int:dsid>', methods=['DELETE'])
def delete_lexonomy(dsid):
    token = flask.request.headers.get('Authorization')
    uid = User.decode_auth_token(token)
    dataset = Datasets.list_datasets(engine, uid, dsid=dsid)

    if dataset['lexonomy_delete'] is not None:
        requests.post(dataset['lexonomy_delete'],
                      headers={"Content-Type": 'application/json',
                               "Authorization": app.config['LEXONOMY_AUTH_KEY']})

    Datasets.dataset_add_lexonomy_access(db, dsid)

    return flask.make_response({'message': 'OK'}, 200)
"""