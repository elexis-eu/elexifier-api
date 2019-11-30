#!/usr/bin/env python

"""
 Entry point for ELEXIS TEI LEX0 dictionary converter service
"""

import flask
import flask.json
from flask import jsonify, make_response, after_this_request
import werkzeug.debug
import pendulum
import json
import lxml
import subprocess


from app.transformator import dictTransformations3 as transformator
from functools import partial
import json, collections
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename
import app.controllers as controllers

from sqlalchemy import create_engine
from flask_sqlalchemy import SQLAlchemy
import os
from app.models import User, BlacklistToken
from app import app, db
from flask_cors import CORS, cross_origin
from celery import Celery
import random
import string
import requests

celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
APP_MEDIA = os.path.join(APP_ROOT, 'media')

# if app.config['ENV'] == 'development':
#     db_path = os.path.join(os.path.dirname(__file__), '../app.db')
#     db_uri = 'sqlite:///{}'.format(db_path)
# else:
db_uri = app.config['SQLALCHEMY_DATABASE_URI']
engine = create_engine(db_uri, encoding="utf8")
orm = SQLAlchemy()
orm.init_app(app)

def _j(r):
    s = flask.make_response(flask.jsonify(r))
    s.mimetype = 'application/json'
    return s


# --- API ---
# @app.after_request
# def apply_caching(response):
#     response.headers["Access-Control-Allow-Origin"] = "*"
#     return response


# -- users
@app.route('/api/user/new', methods=['POST'])
def user_add():
    bcrypt = Bcrypt()
    for field in ['email', 'password']:
        if field not in flask.request.json:
            raise InvalidUsage("Field {0:s} is missing".format(field), status_code=422, enum='POST_ERROR')

    email = flask.request.json['email']
    # TODO: Remove username from EVERYWHERE
    username = email
    password = flask.request.json['password']
    password = bcrypt.generate_password_hash(password).decode('utf-8')
    user = controllers.register_user(db, username, email, password, None)
    if user != None:
        auth_token = user.encode_auth_token(user.id)
        response = {
                    'message' : 'Registration was successful',
                    'username' : username,
                    'email' : email,
                    'auth_token': auth_token.decode(),
                    }
        return flask.make_response(jsonify(response),200)
    else:
        raise InvalidUsage('User already exists', status_code=409, enum="USER_EXISTS")


@app.route('/api/user/<int:userid>/disable', methods=['DELETE'])
def user_delete(userid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    if id != userid:
        raise InvalidUsage("User ids don't match", status_code=401, enum="UNAUTHORIZED")
    controllers.delete_user(engine, userid)
    return flask.make_response(jsonify({ 'message': 'OK'}), 200)


def verify_user(token):
    if not token:
        raise InvalidUsage("No auth token provided.", status_code=401, enum="UNAUTHORIZED")
    elif "Bearer " in token:
        token = token.split("Bearer ")[1]
    resp = User.decode_auth_token(token)
    if isinstance(resp, str):
        raise InvalidUsage(resp, status_code=401, enum="UNAUTHORIZED")
    elif controllers.is_blacklisted(engine, token):
        raise InvalidUsage('User logged out. Please log in again.', status_code=401, enum="UNAUTHORIZED")
    else:
        return resp


@app.route('/api/user/logged-in', methods=['GET'])
def user_data():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    user = controllers.user_data(db, id)
    if user != None:
        response = {
                'username' : user.username,
                'email' : user.email,
                }
        return flask.make_response(jsonify(response),200)
    else:
        raise InvalidUsage('Provide a valid auth token.', status_code=409, enum="INVALID_AUTH_TOKEN")


# -- datasets
@app.route('/api/dataset/list', methods=['GET'])
def ds_list_datasets():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    order = flask.request.args.get('order')
    mimetype = flask.request.args.get('mimetype')
    if isinstance(order, str):
        order = order.upper()
    else:
        order = "ASC"
    if not isinstance(mimetype, str):
        mimetype = "text/xml"
    datasets = controllers.list_datasets(engine, id, order=order, mimetype=mimetype)
    return _j(datasets)


@app.route('/api/dataset/<int:dsid>', methods=['GET'])
def ds_dataset_info(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    datasets = controllers.list_datasets(engine, id, dsid=dsid)
    return _j(datasets)


@app.route('/api/dataset/<int:dsid>', methods=['DELETE'])
def ds_delete_dataset(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    resp = controllers.delete_dataset(engine, id, dsid)
    if resp is None:
        raise InvalidUsage("Dictionary does not exist.", status_code=404, enum="DICTIONARY_DOESNT_EXIST")
    elif not resp:
        raise InvalidUsage("You do not own this dataset", status_code=401, enum="UNAUTHORIZED")
    else:
        return _j({'deleted': dsid})


@app.route('/api/dataset/<int:dsid>/preview', methods=['GET'])
def ds_dataset_preview(dsid):
    raise InvalidUsage('Not implemented', status_code=501)
    pass


@app.route('/api/dataset/<int:dsid>/entries', methods=['GET'])
def ds_list_entries(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    headwords = flask.request.args.get('headwords', default='false', type=str) == 'true'
    rv = controllers.list_dataset_entries(engine, id, dsid, headwords)
    return _j(rv)


@app.route('/api/dataset/<int:dsid>/<int:entryid>', methods=['GET'])
def ds_fetch_dataset_entry(dsid, entryid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    headwords = flask.request.args.get('headwords', default='false', type=str) == 'true'
    rv = controllers.get_entry(engine, id, dsid, entryid, headwords)
    return _j(rv)


def generate_filename(filename,stringLength=20):
    extension = filename.split('.')[-1]
    letters = string.ascii_lowercase
    return ''.join(random.choice(letters) for i in range(stringLength)) + '.' + extension


def transform_pdf2xml(dataset):
    print("Converting PDF to XML")
    bashCommands = ['./app/transformator/pdftoxml -noImage -readingOrder {0:s}'.format(dataset['file_path'])]

    for command in bashCommands:
        print("Command:", command)
        subprocess.run(command.split(" "))


@app.route('/api/dataset/upload', methods=['POST'])
def ds_upload_new_dataset():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    
    headerTitle = flask.request.form.get('headerTitle', None)
    headerPublisher = flask.request.form.get('headerPublisher', None)
    headerBibl = flask.request.form.get('headerBibl', None)

    dictname = flask.request.files.get('dictname', None)
    dzcontent = flask.request.files.get('file', None)
    try :
        dzfilename = dzcontent.filename  # !!
    except AttributeError:
        dzfilename = "tempFile_USER-{0:s}".format( str(id) )

    dztotalfilesize = flask.request.form.get('dztotalfilesize', None)
    dzfilepath = os.path.join(APP_MEDIA, secure_filename(dzfilename))
    dzuuid = flask.request.form.get('dzuuid', None)
    dzcontent = flask.request.files.get('file', None)
    current_chunk = int(flask.request.form.get('dzchunkindex'))

    if os.path.exists(dzfilepath) and current_chunk == 0:
        print('File already exists')
        raise InvalidUsage('File already exists.', status_code=400, enum="FILE_EXISTS")
        #return make_response(jsonify({'message':'File already exists'})), 400

    try:
        with open(dzfilepath, 'ab') as f:
            f.seek(int(flask.request.form.get('dzchunkbyteoffset', None)))
            f.write(dzcontent.stream.read())
    except OSError:
        print('Could not write to file')
        raise InvalidUsage("Not sure why, but we couldn't write the file to disk.", status_code=500, enum="FILE_ERROR")
        #return make_response(jsonify({"message": "Not sure why, but we couldn't write the file to disk"})), 500

    total_chunks = int(flask.request.form.get('dztotalchunkcount', None))

    if current_chunk == total_chunks:
        if os.path.getsize(dzfilepath) != int(dztotalfilesize):
            print('Size mismatch' )
            raise InvalidUsage("Size mismatch.", status_code=500, enum="FILE_ERROR")
            #return make_response(jsonify({"message":'Size mismatch'})), 500
        else:
            new_random_name = generate_filename(dzfilename)
            new_path = os.path.join(APP_MEDIA, secure_filename(new_random_name))
            os.rename(dzfilepath, new_path)
            dsid = controllers.add_dataset(db, id, dztotalfilesize, dzfilename, new_path, dzuuid, headerTitle, headerPublisher, headerBibl)
            result = controllers.list_datasets(engine, id, dsid=dsid)
            if "pdf" in result['upload_mimetype']:
                transform_pdf2xml(result)

        return _j(result)
    else:
        return _j({ 'status': 'OK',
                    'filename': dzfilename,
                    'current_chunk': current_chunk,
                    'total_chunks': total_chunks })


@app.route('/api/dataset/<int:dsid>/name', methods=['POST'])
def ds_rename_dataset(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    raise InvalidUsage('Not implemented', status_code=501)
    pass


# -- lexonomy
@app.route('/api/lexonomy/<int:uid>/download/<int:dsid>', methods=['GET'])
def lexonomy_download(uid, dsid):
    # TODO: add shared secrets to .env
    if flask.request.headers.get('Authorization') != 'Basic AKCdmbwzk7YOXGzswlJ2xyi1aWG4E6B08':
        raise InvalidUsage("Shared secret is not valid!", status_code=401, enum='UNAUTHORIZED')

    controllers.set_dataset_status(engine, uid, dsid, 'Processing')
    dataset = controllers.list_datasets(engine, uid, dsid=dsid)
    return flask.send_file(dataset['xml_file_path'], attachment_filename=dataset['xml_file_path'].split('/')[-1], as_attachment=True)


@celery.task
def make_lexonomy_request(uid, dsid, request_data):
    # Send request async and save links to db
    # TODO: add shared secret to .env
    response = requests.post('https://beta.lexonomy.cjvt.si/elexifier/new',
                             headers={"Content-Type": 'application/json', "Authorization": 'Basic AKCdmbwzk7YOXGzswlJ2xyi1aWG4E6B08'},
                             data=json.dumps(request_data))
    try:

        resp_js = json.loads(response.text)
        # Update dataset in db
        controllers.dataset_add_lexonomy_access(engine, uid, dsid, resp_js['access_link'], resp_js['delete_link'], resp_js['edit_link'], resp_js['status_link'])
        controllers.set_dataset_status(engine, uid, dsid, 'Ready')
    except:
        controllers.set_dataset_status(engine, uid, dsid, "Lexonomy_error: " + str(response.status_code))
    return


@app.route('/api/lexonomy/<int:dsid>', methods=['GET'])
def ds_send_to_lexonomy(dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)

    user = controllers.user_data(db, uid)
    dataset = controllers.list_datasets(engine, uid, dsid=dsid)

    request_data = {
        'xml_file': '/api/lexonomy/' + str(uid) + '/download/' + str(dsid),
        'email': user.email,
        'filename': dataset['name'],
        'return_to': ""  # remove if no longer required
    }

    print('Starting asynchronous request to Lexonomy')
    task = make_lexonomy_request.apply_async(args=[uid, dsid, request_data], countdown=0)

    status = 'Starting'
    msg = 'OK'
    # Update dataset status
    controllers.set_dataset_status(engine, uid, dsid, status)

    return _j({'message': msg, 'dsid': dsid, 'status': status, 'test_request': request_data})


# -- transforms
@app.route('/api/transform/list/<int:dsid>', methods=['GET'])
def xf_list_transforms(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    order = flask.request.args.get('order')
    if isinstance(order, str):
        order = order.upper()
    rv = controllers.list_transforms(engine, id, dsid, order)
    return _j(rv)


@app.route('/api/transform/saved', methods=['GET'])
def xf_list_saved_transforms():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)   
    rv = controllers.list_saved_transforms(engine, id)
    return _j(rv)


@app.route('/api/transform/new', methods=['POST'])
def xf_new_transform():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)

    dsuuid = flask.request.json.get('dsuuid', None)
    dsid = flask.request.json.get('dsid', None)
    xfname = flask.request.json.get('xfname', None)
    entry_spec = flask.request.json.get('entry_spec', None)
    headword = flask.request.json.get('hw', None)
    saved = flask.request.json.get('saved', False)
    print(flask.request.json)

    if dsuuid is None or xfname is None or dsid is None or entry_spec is None:
        raise InvalidUsage("Invalid API call.", status_code=422, enum="POST_ERROR")
        #return flask.make_response(('Invalid API call'), 422)
    xfid = controllers.new_transform(db, id, dsuuid, xfname, dsid, entry_spec, saved)
    isok, retmsg = controllers.prepare_dataset(db, id, dsid, xfid, entry_spec, headword)
    if not isok:
        raise InvalidUsage(retmsg, status_code=422, enum="POST_ERROR")
        #return flask.make_response(retmsg, 422)
    return _j({'xfid': xfid})


@app.route('/api/transform/<int:xfid>', methods=['GET'])
def xf_get_transform_spec(xfid):
    token = flask.request.headers.get('Authorization')
    page_num = flask.request.args.get('page_num', default='1', type=int)
    id = verify_user(token)
    rv = controllers.describe_transform(engine, id, xfid, page_num)
    return _j(rv)


@app.route('/api/transform/<int:xfid>', methods=['DELETE'])
def xf_delete_transform(xfid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    resp = controllers.delete_transform(engine, id, xfid)
    if resp is None:
        raise InvalidUsage("Transformation does not exist.", status_code=404, enum="TRANSFORMATION_DOESNT_EXIST")
    elif not resp:
        raise InvalidUsage("You do not own this transformaiton", status_code=401, enum="UNAUTHORIZED")
    else:
        return _j({'deleted': xfid})


@app.route('/api/transform/<int:xfid>', methods=['POST'])
def xf_update_transform(xfid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    xfspec = flask.request.json.get('xfspec', None)
    saved = flask.request.json.get('saved', False)
    name = flask.request.json.get('name', None)
    print('Update transform')
    if xfspec is None:
        raise InvalidUsage("Invalid API call.", status_code=422, enum="POST_ERROR")
        #return flask.make_response(('Invalid API call'), 422)
    rv = controllers.update_transform(db, id, xfid, xfspec, name, saved)
    return _j({'updated': rv})


@app.route('/api/transform/<int:xfid>/apply/<int:entityid>', methods=['GET'])
def xf_entity_transform(xfid,entityid):
    print('entity transform')
    token = flask.request.args.get('Authorization')
    token_header = flask.request.headers.get('Authorization')

    # Old application is in this case sending Authorization token through query params.
    # Keep this conditional until we drop the support for the old app.

    if token_header is None:
        id = verify_user(token)
    else:
        id = verify_user(token_header)

    strip_ns = flask.request.args.get('strip_ns', default='false', type=str) == 'true'
    strip_header = flask.request.args.get('strip_header', default='false', type=str) == 'true'
    strip_DictScrap = flask.request.args.get('strip_dict_scrap', default='false', type=str) == 'true'

    entity, spec = controllers.get_entity_and_spec(engine, id, xfid, entityid)

    print(spec)


    if spec is None:
        return _j({'spec': None, 'entity_xml': None, 'output': None})

    # Why is this used for?
    # Frontend has been modified to send dumy now directly in the root of the transformer.
    # for t in ('entry', 'sense'):

    #     if t in spec and 'type' in spec[t] and spec[t]['type'] == 'dummy':
    #         spec[t] = spec[t]['selector']

    parserLookup = lxml.etree.ElementDefaultClassLookup(element = transformator.TMyElement)
    myParser = lxml.etree.XMLParser()
    myParser.set_element_class_lookup(parserLookup)
    entity_xml = lxml.etree.fromstring(entity, parser = myParser)


    mapping = transformator.TMapping(spec)
    mapper = transformator.TMapper()
    out_TEI, out_aug = mapper.Transform(mapping, [], [lxml.etree.ElementTree(entity_xml)], makeAugmentedInputTrees=True, stripForValidation=strip_ns,
                                        stripDictScrap=strip_DictScrap, stripHeader=strip_header, returnFirstEntryOnly=True)
                                        
    target_xml = lxml.etree.tostring(out_TEI, pretty_print=True, encoding='unicode')
    target_xml = target_xml.replace('<entry xmlns:m="http://elex.is/wp1/teiLex0Mapper/meta" xmlns:a="http://elex.is/wp1/teiLex0Mapper/legacyAttributes" xmlns="http://www.tei-c.org/ns/1.0">', '<entry>')

    original = lxml.etree.tostring(entity_xml, pretty_print=True, encoding='unicode')
    return _j({'spec': spec, 'entity_xml': original, 'output': target_xml})


@app.route('/api/xml_nodes/<int:dsid>', methods=['GET'])
def ds_list_nodes(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    nodes = controllers.extract_xml_heads(db, dsid)
    return _j({'nodes': nodes})


@app.route('/api/xml_paths/<int:dsid>', methods=['GET'])
def ds_list_paths(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    nodes = controllers.extract_xpaths(db, dsid)
    return _j({'nodes': nodes})


@app.route('/api/transform/<int:xfid>/download/<int:dsid>', methods=['GET'])
def ds_download(xfid, dsid):
    print('transformed dataset download')
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    
    strip_ns = flask.request.args.get('strip_ns', default='false', type=str) == 'true'
    strip_header = flask.request.args.get('strip_header', default='false', type=str) == 'true'
    strip_DictScrap = flask.request.args.get('strip_DictScrap', default='false', type=str) == 'true'


    try:
        xf, ds_path, file_name, header_Title, header_Publisher, header_Bibl = controllers.get_ds_and_xf(engine, id, xfid, dsid)
    except:
        raise InvalidUsage('Transformer does not exist. Click on the save transform button duh! Also, change this error message for production', status_code=409)

    if xf is None:
        return _j({'spec': None, 'entity_xml': None, 'output': None})

    # Why is this used for?
    # Frontend has been modified to send dumy now directly in the root of the transformer.
    # for t in ('entry', 'sense'):

    #     if t in spec and 'type' in spec[t] and spec[t]['type'] == 'dummy':
    #         spec[t] = spec[t]['selector']


    orig_xml = open(ds_path, 'rb').read()
    parserLookup = lxml.etree.ElementDefaultClassLookup(element = transformator.TMyElement)
    myParser = lxml.etree.XMLParser()
    myParser.set_element_class_lookup(parserLookup)
    entity_xml = lxml.etree.fromstring(orig_xml, parser = myParser)
    mapping = transformator.TMapping(xf)
    mapper = transformator.TMapper()
    out_TEI, out_aug = mapper.Transform(mapping, [], [lxml.etree.ElementTree(entity_xml)], makeAugmentedInputTrees=True, stripForValidation=strip_ns,
                                        stripHeader=strip_header, stripDictScrap=strip_DictScrap, headerTitle=header_Title, headerPublisher=header_Publisher, headerBibl=header_Publisher)
    target_xml = lxml.etree.tostring(out_TEI, pretty_print=True, encoding='unicode')

    orig_fname, file_type = file_name.split('.')
    target_fname = orig_fname + '_TEI.' + file_type
    target_path = os.path.join(APP_MEDIA, target_fname)

    with open(target_path, 'w') as out:
        out.write(target_xml)

    @after_this_request
    def remove_file(response):
        os.remove(target_path)
        return response

    return flask.send_file(target_path, attachment_filename=target_path.split('/')[-1], as_attachment=True)


# --- login, static content ---

@app.route('/')
@cross_origin(headers=['Content-Type'])
def index():
    return flask.render_template('login.html')


@app.route('/do_login', methods=['GET', 'POST'])
@cross_origin(headers=['Content-Type'])
def login():
    username = flask.request.form['login']
    password = flask.request.form['password']
    bcrypt = Bcrypt()

    user = controllers.check_login(db, username, password, bcrypt)
    if user is None:
        response = {
            'message': 'Wrong password or user does not exist!'
        }
        # proper login handling if more time......
        return make_response(jsonify(response)), 200
    else:
        #flask_login.login_user(user, remember=True)
        auth_token = user.encode_auth_token(user.id)
        if auth_token:
            response = {
                'message': 'Login succesful!',
                'auth_token': auth_token.decode(),
                'username': user.username,
                'email': user.email
            }
            return flask.redirect(flask.url_for('.return_token', response=json.dumps(response)))


@app.route('/api/login', methods=['GET', 'POST'])
@cross_origin(headers=['Content-Type'])
def login2():
    if 'sketch_token' in flask.request.json:
        sketch_token = flask.request.json['sketch_token']
        user = controllers.login_or_register_sketch_user(db, sketch_token)
    else:
        for field in ['login', 'password']:
            if field not in flask.request.json:
                raise InvalidUsage("Field {0:s} is missing".format(field), status_code=422, enum='POST_ERROR')

        username = flask.request.json['login']
        password = flask.request.json['password']

        bcrypt = Bcrypt()
        user = controllers.check_login(db, username, password, bcrypt)

    if user is None:
        # proper login handling if more time......
        raise InvalidUsage("Wrong password or user does not exist!", status_code=403, enum="LOGIN_ERROR")
    else:
        #flask_login.login_user(user, remember=True)
        auth_token = user.encode_auth_token(user.id)
        if auth_token:
            response = {
                'auth_token': auth_token.decode(),
                'username': user.username,
                'email': user.email,
            }
            return flask.make_response(jsonify(response), 200)


@app.route('/home')
@cross_origin(headers=['Content-Type'])
def return_token():
    response = flask.request.args['response']
    return flask.render_template('build_transform.html', response=_j(response))


@app.route('/do_logout')
@cross_origin(headers=['Content-Type'])
def logout():
    # get auth token
    auth_header = flask.request.headers.get('Authorization')
    if auth_header:
        auth_token = auth_header
    else:
        auth_token = ''
    if auth_token:
        verify_user(auth_token)
        if "Bearer " in auth_token:
            auth_token = auth_token.split("Bearer ")[1]
        controllers.blacklist_token(db, auth_token)
    else:
        raise InvalidUsage('Provide a valid auth token.', status_code=409, enum="INVALID_AUTH_TOKEN")
    return flask.render_template('login.html')


# --- error handling ---
class InvalidUsage(Exception):
    status_code = 400
    enum = "ERROR"

    def __init__(self, message, status_code=None, enum=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if enum is not None:
            self.enum = enum

    def to_dict(self):
        rv = dict()
        rv['message'] = self.message
        rv['status_code'] = self.status_code
        rv['enum'] = self.enum
        return rv

@app.errorhandler(InvalidUsage)
def handle_invalid_usage(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response


if __name__ == "__main__":
    app.run()

