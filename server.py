#!/usr/bin/env python

"""
 Entry point for ELEXIS TEI LEX0 dictionary converter service
"""

import flask
import flask.json
import werkzeug.debug
import pendulum
import json
import psycopg2
import lxml
import lxml.etree

import dbfunc
import transformator.dictTransformations3 as transformator
from sqlalchemy import create_engine
from functools import partial
import json, collections
from flask_bcrypt import Bcrypt
import os
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename


#import jsonrpc.backend.flask
#rpcapi = jsonrpc.backend.flask.api

#db = dbfunc.db_connect()
#db = sqlite3.connect('databases/harmonizator.sqlite3')

db_path = os.path.abspath(os.getcwd())+"/app.db"

app = flask.Flask(__name__, static_url_path='/static', static_folder='static')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = "\x15['\xfc\xa6\x0fo^\xda\x83\xfe\x83Zz\xd1\xa8?Cs\xf4\xf3]\xf8\x94"

app.debug = True
bcrypt = Bcrypt()
#app.secret_key = dbfunc.load_app_secret_key(db)
#app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///databases/harmonizator.sqlite3'
#db = create_engine('sqlite:///databases/harmonizator.sqlite3', json_deserializer=partial(json.loads, object_pairs_hook=collections.OrderedDict), encoding="utf8")
db = create_engine('sqlite:///app.db', encoding="utf8")
orm = SQLAlchemy()
orm.init_app(app)

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
APP_MEDIA = os.path.join(APP_ROOT, 'media')

#app.add_url_rule('/api', 'api', flask_login.login_required(rpcapi.as_view()), methods=['POST'])

def _j(r):
    s = flask.make_response(flask.jsonify(r))
    s.mimetype = 'application/json'
    return s

# --- API ---
# -- users
@app.route('/api/user/new', methods=['POST'])
def user_add():
    pass

@app.route('/api/user/<int:userid>/disable', methods=['DELETE'])
def user_delete():
    pass

def verify_user(token):
    from models import User
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
    datasets = dbfunc.list_datasets(db, id)
    return _j(datasets)

@app.route('/api/dataset/<int:dsid>', methods=['GET'])
def ds_dataset_info(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    datasets = dbfunc.list_datasets(db, id, dsid)
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
    rv = dbfunc.list_dataset_entries(db, id, dsid)
    return _j(rv)

@app.route('/api/dataset/<int:dsid>/<int:entryid>', methods=['GET'])
#@flask_login.login_required
def ds_fetch_dataset_entry(dsid, entryid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    rv = dbfunc.get_entry(db, id, dsid, entryid)
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
    result = dbfunc.add_dataset(db, id, dztotalfilesize, dzfilename, dzfilepath, dzuuid)
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
    rv = dbfunc.list_transforms(db, id, dsid)
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
    xfid = dbfunc.new_transform(db, id, dsuuid, xfname, dsid, entry_spec)
    isok, retmsg = dbfunc.prepare_dataset(db, id, dsid, xfid, entry_spec)
    if not isok:
        return flask.make_response(retmsg, 422)
    return _j({'xfid': xfid})

@app.route('/api/transform/<int:xfid>', methods=['GET'])
#@flask_login.login_required
def xf_get_transform_spec(xfid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    rv = dbfunc.describe_transform(db, id, xfid)
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
    rv = dbfunc.update_transform(db, id, xfid, xfspec)
    return _j({'updated': rv})

@app.route('/api/transform/<int:xfid>/apply/<int:entityid>', methods=['GET'])
#@flask_login.login_required
def xf_entity_transform(xfid,entityid):
    print('entity transform')
    token = flask.request.args.get('Authorization')
    id = verify_user(token)
    strip_ns = flask.request.args.get('strip_ns', default='false', type=str) == 'true'
    entity, spec = dbfunc.get_entity_and_spec(db, id, xfid, entityid)

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
    
#    import pdb; pdb.set_trace()

    return _j({'spec': spec, 'entity_xml': entity.replace('\t', '  '), 'output': lxml.etree.tostring(out_TEI, pretty_print=True, encoding='unicode')})

# --- login, static content ---

@app.route('/')
def index():
    return flask.render_template('login.html')

@app.route('/do_login', methods=['GET', 'POST'])
def login():
    username = flask.request.form['login']
    password = flask.request.form['password']

    user = dbfunc.check_login(db, username, password, bcrypt)
    if user is None:
        # proper login handling if more time......
        return flask.redirect('/')
    else:
        #flask_login.login_user(user, remember=True)
        auth_token = user.encode_auth_token(user.id)
        if auth_token:
            response = {
                'auth_token': auth_token.decode()
            }
            return flask.redirect(flask.url_for('.return_token', response=json.dumps(response)))


@app.route('/static/build_transform.html')
def return_token():
    response = flask.request.args['response']
    return flask.render_template('build_transform.html', response=_j(response))


@app.route('/do_logout')
def logout():
    from models import User, BlacklistToken
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
                db.session.add(blacklist_token)
                db.session.commit()
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





def main():
    app.run(debug=True, use_reloader=True, host="0.0.0.0", port=8081)

if __name__ == '__main__':
    main()
