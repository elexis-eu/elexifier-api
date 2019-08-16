#!/usr/bin/env python

"""
 Entry point for ELEXIS TEI LEX0 dictionary converter service
"""

import flask
import flask.json
from flask import jsonify, make_response
import werkzeug.debug
import pendulum
import json
import lxml

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
from app import app
from flask_cors import CORS, cross_origin
from celery import Celery
import random
import string


celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
APP_MEDIA = os.path.join(APP_ROOT, 'media')

db_path = os.path.join(os.path.dirname(__file__), '../app.db')
db_uri = 'sqlite:///{}'.format(db_path)
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
    username = flask.request.json['username']
    email = flask.request.json['email']
    password = flask.request.json['password']
    password = bcrypt.generate_password_hash(password).decode('utf-8')
    user = controllers.register_user(engine, username, email, password)
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
        response = { 'message' : 'Username already exists'}
        return flask.make_response(jsonify(response), 200)


@app.route('/api/user/<int:userid>/disable', methods=['DELETE'])
def user_delete(userid):
    # Authenticated user only?
    controllers.delete_user(engine, userid)
    return flask.make_response('OK', 200)


def verify_user(token):
    resp = User.decode_auth_token(token)
    if isinstance(resp, str):
        response = {
            'message': 'User not loged in!'
        }
        # proper login handling if more time......
        return make_response(jsonify(response)), 200
    else:
        return resp


@app.route('/api/user/logged-in', methods=['GET'])
def user_data():
    token = flask.request.headers.get('Authorization')
    id = User.decode_auth_token(token.split(" ")[1])
    user = controllers.user_data(engine, id)
    if user != None:
        response = {
                'username' : user.username,
                'email' : user.email,
                }
        return flask.make_response(jsonify(response),200)
    else:
        response = {
                    'message': 'Provide a valid auth token.'
                    }
        return flask.make_response(jsonify(response), 409)

# -- datasets
@app.route('/api/dataset/list', methods=['GET'])
def ds_list_datasets():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    datasets = controllers.list_datasets(engine, id)
    return _j(datasets)


@app.route('/api/dataset/<int:dsid>', methods=['GET'])
def ds_dataset_info(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    datasets = controllers.list_datasets(engine, id, dsid)
    return _j(datasets)


@app.route('/api/dataset/<int:dsid>', methods=['DELETE'])
def ds_delete_dataset():
    pass


@app.route('/api/dataset/<int:dsid>/preview', methods=['GET'])
def ds_dataset_preview():
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


@app.route('/api/dataset/upload', methods=['POST'])
def ds_upload_new_dataset():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)


    dictname = flask.request.files.get('dictname', None)
    dzcontent = flask.request.files.get('file', None)
    dzfilename = dzcontent.filename  # !!
    dztotalfilesize = flask.request.form.get('dztotalfilesize', None)
    dzfilepath = os.path.join(APP_MEDIA, secure_filename(dzfilename))
    dzuuid = flask.request.form.get('dzuuid', None)
    dzcontent = flask.request.files.get('file', None)
    current_chunk = int(flask.request.form.get('dzchunkindex'))

    if os.path.exists(dzfilepath) and current_chunk == 0:
        print('File already exists')
        return make_response(jsonify({'message':'File already exists'})), 400

    try:
        with open(dzfilepath, 'ab') as f:
            f.seek(int(flask.request.form.get('dzchunkbyteoffset', None)))
            f.write(dzcontent.stream.read())
    except OSError:
        print('Could not write to file')
        return make_response(jsonify({"message": "Not sure why, but we couldn't write the file to disk"})), 500

    total_chunks = int(flask.request.form.get('dztotalchunkcount', None))

    if current_chunk + 1 == total_chunks:
        if os.path.getsize(dzfilepath) != int(dztotalfilesize):
            print('Size mismatch', )
            return make_response(jsonify({"message":'Size mismatch'})), 500
        else:
            new_random_name = generate_filename(dzfilename)
            new_path = os.path.join(APP_MEDIA, secure_filename(new_random_name))
            os.rename(dzfilepath, new_path)
            result = controllers.add_dataset(engine, id, dztotalfilesize, dzfilename, new_path, dzuuid)
    return flask.make_response({ 'status': 'OK' },200)


@app.route('/api/dataset/<int:dsid>/name', methods=['POST'])
def ds_rename_dataset():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    pass

# -- transforms
@app.route('/api/transform/list/<int:dsid>', methods=['GET'])
def xf_list_transforms(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    rv = controllers.list_transforms(engine, id, dsid)
    return _j(rv)


@app.route('/api/transform/new', methods=['POST'])
def xf_new_transform():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)

    dsuuid = flask.request.json.get('dsuuid', None)
    dsid = flask.request.json.get('dsid', None)
    xfname = flask.request.json.get('xfname', None)
    entry_spec = flask.request.json.get('entry_spec', None)

    if dsuuid is None or xfname is None or dsid is None or entry_spec is None:
        return flask.make_response(('Invalid API call'), 422)
    xfid = controllers.new_transform(engine, id, dsuuid, xfname, dsid, entry_spec)
    isok, retmsg = controllers.prepare_dataset(engine, id, dsid, xfid, entry_spec)
    if not isok:
        return flask.make_response(retmsg, 422)
    return _j({'xfid': xfid})


@app.route('/api/transform/<int:xfid>', methods=['GET'])
def xf_get_transform_spec(xfid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    rv = controllers.describe_transform(engine, id, xfid)
    return _j(rv)


@app.route('/api/transform/<int:xfid>', methods=['DELETE'])
def xf_delete_transform():
    pass


@app.route('/api/transform/<int:xfid>', methods=['POST'])
def xf_update_transform(xfid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    xfspec = flask.request.json.get('xfspec', None)
    print('Update transform')
    if xfspec is None:
        return flask.make_response(('Invalid API call'), 422)
    rv = controllers.update_transform(engine, id, xfid, xfspec)
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
    entity, spec = controllers.get_entity_and_spec(engine, id, xfid, entityid)

    print(spec)


    if spec is None:
        return _j({'spec': None, 'entity_xml': None, 'output': None})

    for t in ('entry', 'sense'):

        if t in spec and 'type' in spec[t] and spec[t]['type'] == 'dummy':
            spec[t] = spec[t]['selector']

    parserLookup = lxml.etree.ElementDefaultClassLookup(element = transformator.TMyElement)
    myParser = lxml.etree.XMLParser()
    myParser.set_element_class_lookup(parserLookup)
    entity_xml = lxml.etree.fromstring(entity, parser = myParser)


    mapping = transformator.TMapping(spec)
    mapper = transformator.TMapper()
    out_TEI, out_aug = mapper.Transform(mapping, [], [lxml.etree.ElementTree(entity_xml)], makeAugmentedInputTrees=True, stripForValidation=strip_ns)

    return _j({'spec': spec, 'entity_xml': entity.replace('\t', '  '), 'output': lxml.etree.tostring(out_TEI, pretty_print=True, encoding='unicode')})


@app.route('/api/xml_nodes/<int:dsid>', methods=['GET'])
def ds_list_nodes(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    nodes = controllers.extract_xml_heads(engine, dsid)
    return _j({'nodes': nodes})


@app.route('/api/transform/<int:xfid>/download/<int:dsid>', methods=['GET'])
def ds_download(xfid, dsid):
    print('transformed dataset download')
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    xf, ds_path = dbfunc.get_ds_and_xf(engine, id, xfid, dsid)
    xf = json.loads(xf)

    orig_xml = open(ds_path, 'rb').read()
    parserLookup = lxml.etree.ElementDefaultClassLookup(element = transformator.TMyElement)
    myParser = lxml.etree.XMLParser()
    myParser.set_element_class_lookup(parserLookup)
    entity_xml = lxml.etree.fromstring(orig_xml, parser = myParser)
    mapping = transformator.TMapping(xf)
    mapper = transformator.TMapper()
    out_TEI, out_aug = mapper.Transform(mapping, [], [lxml.etree.ElementTree(entity_xml)], makeAugmentedInputTrees=True, stripForValidation=False)
    target_xml = lxml.etree.tostring(out_TEI, pretty_print=True, encoding='unicode')

    orig_fname = ds_path.split('/')[-1].split('.')
    target_fname = orig_fname[0]+'_TEI.'+orig_fname[1]
    target_path = os.path.join(APP_MEDIA, target_fname)

    with open(target_path, 'w') as out:
        out.write(target_xml)
    return flask.send_file(target_path, attachment_filename=target_fname)


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

    user = controllers.check_login(engine, username, password, bcrypt)
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
    username = flask.request.json['login']
    password = flask.request.json['password']
    bcrypt = Bcrypt()

    user = controllers.check_login(engine, username, password, bcrypt)
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
        resp = User.decode_auth_token(auth_token)
        if not isinstance(resp, str):
            # mark the token as blacklisted
            blacklist_token = BlacklistToken(token=auth_token)
            try:
                # insert the token
                engine.session.add(blacklist_token)
                engine.session.commit()
                responseObject = {
                    'status': 'success',
                    'message': 'Successfully logged out.'
                }
                return make_response(jsonify(responseObject)), 200
            except Exception as e:
                responseObject = {
                    'status': 'fail',
                    'message': e
                }
                return make_response(jsonify(responseObject)), 200
        else:
            responseObject = {
                'status': 'fail',
                'message': resp
            }
            return make_response(jsonify(responseObject)), 401
    else:
        responseObject = {
            'status': 'fail',
            'message': 'Provide a valid auth token.'
        }
        return make_response(jsonify(responseObject)), 403
    return flask.render_template('login.html')


if __name__ == "__main__":
    app.run()


