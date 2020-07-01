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
from app.user.controllers import verify_user
#from app.dataset.controllers import set_dataset_status, dataset_add_ml_lexonomy_access, dataset_add_ml_paths, dataset_ml_task_id, dataset_character_map
#from app.dataset.models import Datasets
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
    uid = verify_user(token)

    xml_format = flask.request.args.get('xml_format', default=None, type=str) == 'True'
    get_file = flask.request.args.get('get_file', default=None, type=str) == 'True'
    run_ml = flask.request.args.get('run_ml', default=None, type=str) == 'True'
    send_file = flask.request.args.get('send_file', default=None, type=str) == 'True'

    # TODO: Save paths to DB
    dataset = Datasets.list_datasets(uid, dsid=dsid)
    xml_lex = dataset.xml_lex
    xml_raw = dataset.xml_file_path
    print('xml_lex:', xml_lex, 'xml_raw:', xml_raw)

    if xml_lex == None:
        xml_ml_out = None
    else:
        xml_ml_out = xml_lex[:-4] + "-ML_OUT.xml"
    Datasets.dataset_add_ml_paths(engine, uid, dsid, dataset.xml_lex, xml_ml_out)

    # Check if all params are None
    if xml_format is None and get_file is None and run_ml is None and send_file is None:
        raise InvalidUsage("Invalid API call. No params.", status_code=422, enum="GET_ERROR")
    # Check if to many params
    elif xml_format and (get_file or run_ml or send_file):
        raise InvalidUsage("Invalid API call. Can't work on file and send it.", status_code=422, enum="GET_ERROR")

    dataset.ml_task_id = Datasets.dataset_ml_task_id(engine, dsid)
    status = dataset.status

    # Check if dataset has ml_task, then send status
    if dataset.ml_task_id:
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

        filename = dataset.name.split('.')[0] + '-transformed.xml'
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
    uid = verify_user(token)
    dataset = Datasets.list_datasets(uid, dsid=dsid)

    local = flask.request.args.get('local', default=None, type=str) == 'True'

    if local:
        try:
            print("Deleting local ml files uid: {0:s}, dsid: {1:s}".format(str(uid), str(dsid)))
            json_ml_in = '/var/www/elexifier-api/app/media/ML-IN-{}.json'.format(str(dsid))
            json_ml_out = '/var/www/elexifier-api/app/media/ML-OUT-{}.json'.format(str(dsid))
            os.remove(json_ml_in)
            os.remove(json_ml_out)
            if dataset.xml_lex != "":
                os.remove(dataset.xml_lex)
            if dataset.xml_ml_out != "":
                os.remove(dataset.xml_ml_out)
        except:
            pass
        Datasets.dataset_add_ml_paths(engine, uid, dsid, '', '')

    else:
        if dataset.lexonomy_ml_delete is not None:
            requests.post(dataset.lexonomy_ml_delete,
                          headers={"Content-Type": 'application/json',
                                   "Authorization": app.config['LEXONOMY_AUTH_KEY']})

        Datasets.dataset_add_ml_lexonomy_access(db, dsid)

    return flask.make_response({'message': 'OK'}, 200)


@app.route('/api/ml/<int:dsid>/character_map', methods=['POST'])
def char_map(dsid):
    character_map = flask.request.json.get('character_map', None)
    Datasets.dataset_character_map(db, dsid, set=True, character_map=character_map)
    return flask.make_response({'msg': 'ok'}, 200)


@app.route('/api/ml/<int:dsid>/character_map', methods=['GET'])
def get_char_map(dsid):
    character_map = Datasets.dataset_character_map(db, dsid)
    return flask.make_response({'character_map': character_map}, 200)
