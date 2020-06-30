import flask
from flask import after_this_request
import os
import requests
import lxml
import lxml.etree
import json

from app.user.models import User
from app.user.controllers import verify_user
import app.dataset.controllers as Datasets
from app.modules.error_handling import InvalidUsage
from app import app, db, celery

# TODO: should this be here?đ
from sqlalchemy import create_engine
db_uri = app.config['SQLALCHEMY_DATABASE_URI']
engine = create_engine(db_uri, encoding='utf-8')
#engine = None


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
    uid = verify_user(token)

    #user = controllers.user_data(db, uid)
    user = User.query.filter_by(id=uid).first()
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
    uid = verify_user(token)
    dataset = Datasets.list_datasets(engine, uid, dsid=dsid)

    if dataset['lexonomy_delete'] is not None:
        requests.post(dataset['lexonomy_delete'],
                      headers={"Content-Type": 'application/json',
                               "Authorization": app.config['LEXONOMY_AUTH_KEY']})

    Datasets.dataset_add_lexonomy_access(db, dsid)

    return flask.make_response({'message': 'OK'}, 200)
