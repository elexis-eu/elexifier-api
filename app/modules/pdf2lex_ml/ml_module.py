import flask
from flask import after_this_request
import os
import json
import requests
import traceback
import lxml
import lxml.etree
import re

from app import app, db, celery
from app.user.models import User
from app.user.controllers import verify_user
#from app.dataset.controllers import set_dataset_status, dataset_add_ml_lexonomy_access, dataset_add_ml_paths, dataset_ml_task_id, dataset_character_map
#from app.dataset.models import Datasets
import app.dataset.controllers as Datasets
import app.modules.support as ErrorLog
from app.modules.error_handling import InvalidUsage
from app.modules.log import print_log
from app.modules.lexonomy import make_lexonomy_request, get_lex_annotate, get_lex_preview

# ML scripts
from app.modules.pdf2lex_ml.xml2json_ML import xml2json
from app.modules.pdf2lex_ml.train_ML import train_ML
from app.modules.pdf2lex_ml.json2xml_ML import json2xml
import app.modules.transformator.dictTransformations3 as transformator
from app.modules.pdf2lex_ml.tokenized2TEI import tokenized2TEI


def ds_sendML_to_lexonomy(uid, dsid):
    user = User.query.filter_by(id=uid).first()
    dataset = Datasets.list_datasets(uid, dsid=dsid)

    if dataset.lexonomy_ml_delete is not None:
        requests.post(dataset.lexonomy_ml_delete,
                      headers={"Content-Type": 'application/json',
                               "Authorization": app.config['LEXONOMY_AUTH_KEY']})

    request_data = {
        'xml_file': '/api/lexonomy/' + str(uid) + '/download/' + str(dsid) + "?ml=True",
        'email': user.email,
        'filename': dataset.name + ' - preview',
        'type': 'preview',
        'url': app.config['URL'],
        'return_to': ""  # remove if no longer required
    }

    if user.sketch_engine_uid is not None:  # ske user
        request_data['ske_user'] = True
    else:
        request_data['ske_user'] = False

    print('Starting asynchronous request to Lexonomy')
    make_lexonomy_request.apply_async(args=[dsid, request_data], kwargs={"ml": True}, countdown=0)

    # Update dataset status
    status = Datasets.dataset_status(dsid)
    status['preview'] = 'Starting'
    Datasets.dataset_status(dsid, set=True, status=status)
    msg = 'OK'
    return flask.make_response({'message': msg, 'dsid': dsid, 'status': status['preview'], 'test_request': request_data}, 200)


@celery.task
def run_pdf2lex_ml_scripts(uid, dsid, xml_raw, xml_lex, xml_out):
    # Create files
    temp_fname = xml_raw.split('.xml')[0]
    json_ml_in = temp_fname + '-ML-IN.json'
    json_ml_out = temp_fname + '-ML-OUT.json'
    open(json_ml_in, 'a').close()
    open(json_ml_out, 'a').close()
    open(xml_out, 'a').close()

    def clean_files():
        os.remove(json_ml_in)
        os.remove(json_ml_out)

    status = Datasets.dataset_status(dsid)
    print_log('celery', 'Dictionary: {} @xml2json_ML'.format(dsid))  # step 1
    try:
        xml2json(xml_raw, xml_lex, json_ml_in)
        status['ml'] = 'ML_Format'
        Datasets.dataset_status(dsid, set=True, status=status)
    except Exception as e:
        status['ml'] = 'Lex2ML_Error'
        Datasets.dataset_status(dsid, set=True, status=status)
        Datasets.dataset_ml_task_id(dsid, set=True, task_id="")
        print_log('celery', 'Dictionary: {} @xml2json_ML [ERROR]'.format(dsid))
        clean_files()
        ErrorLog.add_error_log(db, dsid, tag='ml_error', message=traceback.format_exc())
        return

    print_log('celery', 'Dictionary: {} @train_ML'.format(dsid))  # step 2
    try:
        _, report = train_ML(json_ml_in, json_ml_out, '')
        ErrorLog.add_error_log(db, dsid, tag='ml_finished', message=report)
        status['ml'] = 'ML_Annotated'
        Datasets.dataset_status(dsid, set=True, status=status)
    except Exception as e:
        status['ml'] = 'ML_Error'
        Datasets.dataset_status(dsid, set=True, status=status)
        Datasets.dataset_ml_task_id(dsid, set=True, task_id="")
        print_log('celery', 'Dictionary: {} @train_ML [ERROR]'.format(dsid))
        clean_files()
        ErrorLog.add_error_log(db, dsid, tag='ml_error', message=traceback.format_exc())
        return

    print_log('celery', 'Dictionary: {} @json2xml_ML'.format(dsid))  # step 3
    try:
        json2xml(json_ml_out, xml_raw, xml_out)
        status['ml'] = 'Lex_Format'
        Datasets.dataset_status(dsid, set=True, status=status)
    except Exception as e:
        status['ml'] = 'ML2Lex_Error'
        Datasets.dataset_status(dsid, set=True, status=status)
        Datasets.dataset_ml_task_id(dsid, set=True, task_id="")
        print_log('celery', 'Dictionary: {} @json2xml_ML [ERROR]'.format(dsid))
        clean_files()
        ErrorLog.add_error_log(db, dsid, tag='ml_error', message=traceback.format_exc())
        return

    pos_map = extract_ml_pos_map(xml_out)
    Datasets.update_pos_elements(db, dsid, pos_map)
    Datasets.dataset_ml_task_id(dsid, set=True, task_id="")
    clean_files()
    return


def clean_tokens(node, char_map):
    if len(node) > 0 and node[-1].text:
        if node[-1].text[-1] in [',', ':', ';']:
            dictScrap = lxml.etree.fromstring('<dictScrap></dictScrap>')
            dictScrap.text = node[-1].text[-1]
            node[-1].text = node[-1].text[:-1]
            node.addnext(dictScrap)
    if node.text is None:
        node.text = ''
    for child in node:
        if child.tag == 'TOKEN':
            node.text += ' ' + child.text.strip()
            node.remove(child)
        clean_tokens(child, char_map)

    for key in char_map:
        node.text = re.sub(key, char_map[key], node.text)
    node.text = node.text.strip()


def remap_pos(node, pos_map):
    for container in node.xpath("//container[@name='pos']"):
        pos_key = None
        for i, token in enumerate(container):
            if pos_key is None:
                pos_key = token.text
            elif token.text is not None:
                pos_key += ' ' + token.text
            if i > 0:
                container.remove(token)
        if len(container) > 0:
            try:
                container[0].text = pos_map[pos_key]
            except:
                continue
    return


@celery.task
def prepare_TEI_download(uid, dsid, input_file, output_file, pos_map, character_map):
    get_lex_preview(uid, dsid)

    # Load json for transformation
    json_file = os.path.join(app.config['APP_DIR'], 'modules/pdf2lex_ml/lexonomy_to_tei.json')
    with open(json_file, 'r') as file:
        json_data = file.read()
        file.close()

    transformation_json = json.loads(json_data)

    # remap pos and clean tokens
    parser = lxml.etree.XMLParser(encoding='utf-8', recover=True)
    lexonomy_xml = lxml.etree.parse(input_file, parser=parser)
    remap_pos(lexonomy_xml.getroot(), pos_map)
    if character_map is None:
        character_map = dict()
    clean_tokens(lexonomy_xml.getroot(), character_map)
    orig_xml = lxml.etree.tostring(lexonomy_xml)

    parserLookup = lxml.etree.ElementDefaultClassLookup(element=transformator.TMyElement)
    myParser = lxml.etree.XMLParser(encoding='utf-8', recover=True)
    myParser.set_element_class_lookup(parserLookup)
    lexonomy_xml = lxml.etree.fromstring(orig_xml, parser=myParser)

    # init transformator
    mapping = transformator.TMapping(transformation_json)
    mapper = transformator.TMapper()

    # transform lexonomy format to tei format
    metadata = Datasets.dataset_metadata(dsid)
    out_TEI, out_aug, _ = mapper.Transform(mapping, [], [lxml.etree.ElementTree(lexonomy_xml)], makeAugmentedInputTrees=True,
                                        stripForValidation=False,
                                        stripHeader=False,
                                        #stripDictScrap=True, # TODO: change when fixed
                                        stripDictScrap=False,
                                        headerTitle=False,
                                        headerPublisher=False,
                                        headerBibl=False,
                                        promoteNestedEntries=True,
                                        metadata=metadata)
    print_log('DEBUG', 'transformed')
    target_xml = '\n' + lxml.etree.tostring(out_TEI, pretty_print=True, encoding='unicode')
    print_log('DEBUG', 'in string')
    target_xml = target_xml.replace(
        '<entry xmlns:m="http://elex.is/wp1/teiLex0Mapper/meta" xmlns:a="http://elex.is/wp1/teiLex0Mapper/legacyAttributes" xmlns="http://www.tei-c.org/ns/1.0">',
        '<entry>')
    print_log('DEBUG', 'entry replaced')

    # writing transformed xml to file
    open(output_file, 'a').close()
    print_log('DEBUG', 'writing to file')
    with open(output_file, 'w') as out:
        out.write(target_xml)
        out.close()
    print_log('DEBUG', 'writing finished')
    status = Datasets.dataset_status(dsid)
    status['download'] = 'Ready'
    Datasets.dataset_status(dsid, set=True, status=status)
    return


def extract_ml_pos_map(xml_file_path):
    parser = lxml.etree.XMLParser(encoding='utf-8', recover=True)
    tree = lxml.etree.parse(xml_file_path, parser=parser)
    results = set()
    for container in tree.xpath("//container[@name='pos']"):
        _tmp_pos = None
        for token in container:
            if _tmp_pos is None:
                _tmp_pos = token.text
            elif token.text is not None:
                _tmp_pos += ' ' + token.text
        results.add(_tmp_pos)
    pos_map = {pos:pos for pos in results}
    return pos_map


# --- views ---
@app.route('/api/ml/<int:dsid>/annotate', methods=['GET'])
def ds_send_to_lexonomy(dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    user = User.query.filter_by(id=uid).first()
    db.session.close()
    dataset = Datasets.list_datasets(uid, dsid=dsid)
    additional_pages = flask.request.args.get('add_pages', default='0', type=str).lower() == '1'

    if additional_pages:
        # get file from lexonomy and save it
        get_lex_annotate(uid, dsid)

    # Reset dataset status and delete old files @Lexonomy
    dataset.status['ml'] = None
    dataset.status['preview'] = None
    if dataset.lexonomy_delete is not None:
        requests.post(dataset.lexonomy_delete, headers={"Content-Type": 'application/json',
                                                        "Authorization": app.config['LEXONOMY_AUTH_KEY']})
    if dataset.lexonomy_ml_delete is not None:
        requests.post(dataset.lexonomy_ml_delete, headers={"Content-Type": 'application/json',
                                                           "Authorization": app.config['LEXONOMY_AUTH_KEY']})

    request_data = {
        'xml_file': '/api/lexonomy/{}/download/{}'.format(uid, dsid) + ('?add_pages=True' if additional_pages else ''),
        'email': user.email,
        'filename': dataset.name + ' - annotate',
        'type': 'edit',
        'url': app.config['URL'],
        'ske_user': True if user.sketch_engine_uid is not None else False,
        'return_to': ""  # remove if no longer required
    }

    print_log(app.name, 'Starting asynchronous request to Lexonomy {}'.format(dataset))
    make_lexonomy_request.apply_async(args=[dsid, request_data], countdown=0)

    # Update dataset status
    dataset.status['annotate'] = 'Starting'
    Datasets.dataset_status(dsid, set=True, status=dataset.status)

    return flask.make_response({'message': 'OK', 'dsid': dsid, 'status': dataset.status['annotate'], 'test_request': request_data}, 200)


@app.route('/api/ml/<int:dsid>/run', methods=['GET'])
def ml_run(dsid):
    """
    Dataset should be annotated at Lexonomy so we can download it and start ML process.
    ML statuses: Starting_ML -> ML_Format -> ML_Annotated -> Lex_Format
    Error statuses: Lex2ML_Error, ML_Error, ML2Lex_Error
    """
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    # get annotations first, so we get lex_xml path in db
    dataset = Datasets.list_datasets(uid, dsid=dsid)
    if dataset.status['annotate'] != 'Ready':
        raise InvalidUsage('File is not annotated at Lexonomy.', status_code=409, enum='STATUS_ERROR')
    get_lex_annotate(uid, dsid)
    dataset = Datasets.list_datasets(uid, dsid=dsid)

    # deleting preview
    dataset.status['preview'] = None
    Datasets.dataset_add_ml_lexonomy_access(dsid)
    if dataset.lexonomy_ml_delete is not None:
        requests.post(dataset.lexonomy_ml_delete, headers={"Content-Type": 'application/json',
                                                           "Authorization": app.config['LEXONOMY_AUTH_KEY']})

    if dataset.status['ml'] in ['Starting_ML', 'ML_Format', 'ML_Annotated']:
        raise InvalidUsage('ML is already running.', status_code=409, enum='STATUS_ERROR')
    print_log(app.name, '{} Starting ML'.format(dataset))
    dataset.status['ml'] = 'Starting_ML'
    Datasets.dataset_status(dsid, set=True, status=dataset.status)
    # Get files ready
    xml_raw = dataset.xml_file_path
    xml_ml_out = dataset.xml_lex[:-4] + '-ML_OUT.xml'
    Datasets.dataset_add_ml_paths(dsid, xml_lex=dataset.xml_lex, xml_ml_out=xml_ml_out)
    # Run ml
    task = run_pdf2lex_ml_scripts.apply_async(args=[uid, dsid, xml_raw, dataset.xml_lex, xml_ml_out], countdown=0)
    Datasets.dataset_ml_task_id(dsid, set=True, task_id=task.id)
    return flask.make_response({'message': 'ok', 'dsid': dsid, 'status': dataset.status['ml']}, 200)


@app.route('/api/ml/<int:dsid>/preview', methods=['GET'])
def ml_preview(dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    dataset = Datasets.list_datasets(uid, dsid=dsid)
    if dataset.status['ml'] == 'Lex_Format' and dataset.xml_ml_out is None or dataset.xml_ml_out is '':
        raise InvalidUsage('No file for preview. Try running ML first.', status_code=409, enum='STATUS_ERROR')
    ds_sendML_to_lexonomy(uid, dsid)
    return flask.make_response({'message': 'ok', 'dsid': dsid, 'status': dataset.status}, 200)


@app.route('/api/ml/<int:dsid>/status', methods=['GET'])
def ml_status(dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    dataset = Datasets.list_datasets(uid, dsid=dsid)
    return flask.make_response({'dsid': dsid, 'status': dataset.status}, 200)


@app.route('/api/ml/<int:dsid>/download', methods=['GET'])
def ml_download(dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    dataset = Datasets.list_datasets(uid, dsid=dsid)

    # TODO: This checks can be replaced: if preview exists (is Ready), then get it from Lexonomy and download it
    # TODO: otherwise notify user to send ml output to preview
    # check if ml output is ready for download
    if dataset.xml_ml_out is None or dataset.xml_ml_out is '':
        raise InvalidUsage('No file for download. Try running ML first.', status_code=409, enum='STATUS_ERROR')
    elif dataset.status['ml'] in [None, 'Starting_ML', 'Lex2ML_Error', 'ML_Format', 'ML_Error', 'ML_Annotated', 'ML2Lex_Error']:
        raise InvalidUsage('File is not ready for download. Wait for ML to finish first.', status_code=409, enum='STATUS_ERROR')

    tmp_file = dataset.xml_ml_out.split(".xml")[0] + "_TEI.xml"

    # stop if already preparing download
    if dataset.status['download'] == 'Preparing_download':
        return flask.make_response({'msg': 'Dataset is preparing for download', 'status': dataset.status}, 200)
    # if download is ready, return file
    elif dataset.status['download'] == 'Ready':
        dataset.status['download'] = None
        Datasets.dataset_status(dsid, set=True, status=dataset.status)

        @after_this_request
        def after(response):
            response.headers['x-suggested-filename'] = filename
            response.headers.add('Access-Control-Expose-Headers', '*')
            os.remove(tmp_file)
            return response

        filename = os.path.splitext(dataset.name)[0] + '-transformed.xml'
        return flask.send_file(tmp_file, attachment_filename=filename, as_attachment=True, conditional=True)

    # prepare download
    dataset.status['download'] = 'Preparing_download'
    Datasets.dataset_status(dsid, set=True, status=dataset.status)
    character_map = Datasets.dataset_character_map(dsid)
    pos_map = json.loads(dataset.pos_elements)
    prepare_TEI_download.apply_async(args=[uid, dsid, dataset.xml_ml_out, tmp_file, pos_map, character_map])
    return flask.make_response({'msg': 'Dataset is preparing for download', 'status': dataset.status['download']}, 200)


@app.route('/api/ml/<int:dsid>', methods=['DELETE'])
def delete_ml(dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    dataset = Datasets.list_datasets(uid, dsid=dsid)
    local = flask.request.args.get('local', default=None, type=str) == 'True'

    if local:
        try:
            print_log(app.name, 'Deleting local ML files: {}'.format(dataset))
            json_ml_in = '/var/www/elexifier-api/app/media/ML-IN-{}.json'.format(str(dsid))
            json_ml_out = '/var/www/elexifier-api/app/media/ML-OUT-{}.json'.format(str(dsid))
            if dataset.xml_lex != "":
                os.remove(dataset.xml_lex)
            if dataset.xml_ml_out != "":
                os.remove(dataset.xml_ml_out)
            os.remove(json_ml_in)
            os.remove(json_ml_out)
        except:
            pass
        Datasets.dataset_add_ml_paths(dsid)
    else:
        print_log(app.name, 'Deleting Lexonomy preview file: {}'.format(dataset))
        if dataset.lexonomy_ml_delete is not None:
            requests.post(dataset.lexonomy_ml_delete,
                          headers={"Content-Type": 'application/json',
                                   "Authorization": app.config['LEXONOMY_AUTH_KEY']})
        Datasets.dataset_add_ml_lexonomy_access(db, dsid)

    return flask.make_response({'message': 'OK'}, 200)


@app.route('/api/ml/<int:dsid>/character_map', methods=['POST'])
def char_map(dsid):
    character_map = flask.request.json.get('character_map', None)
    Datasets.dataset_character_map(dsid, set=True, character_map=character_map)
    return flask.make_response({'msg': 'ok'}, 200)


@app.route('/api/ml/<int:dsid>/character_map', methods=['GET'])
def get_char_map(dsid):
    character_map = Datasets.dataset_character_map(dsid)
    return flask.make_response({'character_map': character_map}, 200)


@app.route('/api/ml/<int:dsid>/pos_map', methods=['GET'])
def get_pos_map(dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    dataset = Datasets.list_datasets(uid, dsid=dsid)
    refresh = int(flask.request.args.get('refresh', default=0))
    if dataset.pos_elements is not None:
        pos_map = json.loads(dataset.pos_elements)
    else:
        pos_map = dict()
    if refresh and dataset.lexonomy_ml_access is not None:
        get_lex_preview(uid, dsid)
        new_pos_map = extract_ml_pos_map(dataset.xml_ml_out)
        for key, value in pos_map.items():
            if key in new_pos_map:
                new_pos_map[key] = value
        pos_map = new_pos_map
        Datasets.update_pos_elements(db, dsid, pos_map)
    return flask.make_response({'pos_map': pos_map}, 200)


@app.route('/api/ml/<int:dsid>/pos_map', methods=['POST'])
def update_pos_map(dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    pos_map = flask.request.json.get('pos_map', dict())
    Datasets.update_pos_elements(db, dsid, pos_map)
    return flask.make_response({'pos_map': pos_map}, 200)
