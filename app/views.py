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
import app.dbfunc as dbfunc

from sqlalchemy import create_engine
from flask_sqlalchemy import SQLAlchemy
import os
from app.models import User, BlacklistToken
from app import app
from flask_cors import CORS, cross_origin





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
@app.after_request
def apply_caching(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response
  
# -- users
@app.route('/api/user/new', methods=['POST'])
def user_add():
    bcrypt = Bcrypt()
    username = flask.request.headers.get('username')
    email = flask.request.headers.get('email')
    password = flask.request.headers.get('password')
    password = bcrypt.generate_password_hash(password).decode('utf-8')
    if dbfunc.register_user(engine, username, email, password):
        return flask.make_response('OK',200)
    else:
        return flask.make_response('Already exists', 200)

@app.route('/api/user/<int:userid>/disable', methods=['DELETE'])
def user_delete(userid):
    # Authenticated user only?
    dbfunc.delete_user(engine, userid)
    return flask.make_response('OK', 200)

def verify_user(token):
    resp = User.decode_auth_token(token)
    if isinstance(resp, str):
        #TODO
        flask.render_template('login.html')
    else:
        return resp


# -- datasets
@app.route('/api/dataset/list', methods=['GET'])
def ds_list_datasets():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    datasets = dbfunc.list_datasets(engine, id)
    return _j(datasets)

@app.route('/api/dataset/<int:dsid>', methods=['GET'])
def ds_dataset_info(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    datasets = dbfunc.list_datasets(engine, id, dsid)
    return _j(datasets)

@app.route('/api/dataset/<int:dsid>', methods=['DELETE'])
#@flask_login.login_required
def ds_delete_dataset():
    pass

@app.route('/api/dataset/<int:dsid>/preview', methods=['GET'])
#@flask_login.login_required
def ds_dataset_preview():
    pass

@app.route('/api/dataset/<int:dsid>/entries', methods=['GET'])
#@flask_login.login_required
def ds_list_entries(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    rv = dbfunc.list_dataset_entries(engine, id, dsid)
    return _j(rv)

@app.route('/api/dataset/<int:dsid>/<int:entryid>', methods=['GET'])
#@flask_login.login_required
def ds_fetch_dataset_entry(dsid, entryid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    rv = dbfunc.get_entry(engine, id, dsid, entryid)
    return _j(rv)

@app.route('/api/dataset/upload', methods=['POST'])
#@flask_login.login_required
def ds_upload_new_dataset():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    dictname = flask.request.files.get('dictname', None)
    dzcontent = flask.request.files.get('file', None)
    dzfilename = flask.request.files.get('file', None).filename  # !!
    dztotalfilesize = flask.request.form.get('dztotalfilesize', None)
    dzfilepath = os.path.join(APP_MEDIA, secure_filename(dzcontent.filename))
    dzuuid = flask.request.form.get('dzuuid', None)
    dzcontent.save(os.path.join(APP_MEDIA, secure_filename(dzcontent.filename)))
    result = dbfunc.add_dataset(engine, id, dztotalfilesize, dzfilename, dzfilepath, dzuuid)
    if result:
        return flask.make_response('OK',200)

@app.route('/api/dataset/<int:dsid>/name', methods=['POST'])
#@flask_login.login_required
def ds_rename_dataset():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    pass

# -- transforms
@app.route('/api/transform/list/<int:dsid>', methods=['GET'])
#@flask_login.login_required
def xf_list_transforms(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    rv = dbfunc.list_transforms(engine, id, dsid)
    return _j(rv)

@app.route('/api/transform/new', methods=['POST'])
#@flask_login.login_required
def xf_new_transform():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)

    dsuuid = flask.request.json.get('dsuuid', None)
    dsid = flask.request.json.get('dsid', None)
    xfname = flask.request.json.get('xfname', None)
    entry_spec = flask.request.json.get('entry_spec', None)

    if dsuuid is None or xfname is None or dsid is None or entry_spec is None:
        return flask.make_response(('Invalid API call'), 422)
    xfid = dbfunc.new_transform(engine, id, dsuuid, xfname, dsid, entry_spec)
    isok, retmsg = dbfunc.prepare_dataset(engine, id, dsid, xfid, entry_spec)
    if not isok:
        return flask.make_response(retmsg, 422)
    return _j({'xfid': xfid})

@app.route('/api/transform/<int:xfid>', methods=['GET'])
#@flask_login.login_required
def xf_get_transform_spec(xfid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    rv = dbfunc.describe_transform(engine, id, xfid)
    return _j(rv)

@app.route('/api/transform/<int:xfid>', methods=['DELETE'])
#@flask_login.login_required
def xf_delete_transform():
    pass

@app.route('/api/transform/<int:xfid>', methods=['POST'])
#@flask_login.login_required
def xf_update_transform(xfid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    xfspec = flask.request.json.get('xfspec', None)
    print('Update transform')
    if xfspec is None:
        return flask.make_response(('Invalid API call'), 422)
    rv = dbfunc.update_transform(engine, id, xfid, xfspec)
    return _j({'updated': rv})

@app.route('/api/transform/<int:xfid>/apply/<int:entityid>', methods=['GET'])
#@flask_login.login_required
def xf_entity_transform(xfid,entityid):
    print('entity transform')
    token = flask.request.args.get('Authorization')
    id = verify_user(token)
    strip_ns = flask.request.args.get('strip_ns', default='false', type=str) == 'true'
    entity, spec = dbfunc.get_entity_and_spec(engine, id, xfid, entityid)

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
def ds_list_nodes():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    datasets = dbfunc.extract_xml_heads(dsid)
    return _j(datasets)


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

    user = dbfunc.check_login(engine, username, password, bcrypt)
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
    username = flask.request.form['login']
    password = flask.request.form['password']
    bcrypt = Bcrypt()

    user = dbfunc.check_login(engine, username, password, bcrypt)
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



