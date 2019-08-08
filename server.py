#!/usr/bin/env python

"""
 Entry point for ELEXIS TEI LEX0 dictionary converter service
"""

import flask
import flask.json
import flask_login
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
app.secret_key = "super secret key"

app.debug = True
bcrypt = Bcrypt()
#app.secret_key = dbfunc.load_app_secret_key(db)
#app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///databases/harmonizator.sqlite3'
#db = create_engine('sqlite:///databases/harmonizator.sqlite3', json_deserializer=partial(json.loads, object_pairs_hook=collections.OrderedDict), encoding="utf8")
db = create_engine('sqlite:///app.db', encoding="utf8")
orm = SQLAlchemy()
orm.init_app(app)

login_manager = flask_login.LoginManager()
login_manager.session_protection = "strong"
login_manager.init_app(app)
login_manager.user_loader(lambda uid: dbfunc.user_loader(db, uid))

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
#@flask_login.login_required
def user_add():
    pass

@app.route('/api/user/<int:userid>/disable', methods=['DELETE'])
#@flask_login.login_required
def user_delete():
    pass

# -- datasets
@app.route('/api/dataset/list', methods=['GET'])
#@flask_login.login_required
def ds_list_datasets():
    user = flask_login.current_user
    datasets = dbfunc.list_datasets(db, user.id)
    return _j(datasets)

@app.route('/api/dataset/<int:dsid>', methods=['GET'])
#@flask_login.login_required
def ds_dataset_info(dsid):
    user = flask_login.current_user
    datasets = dbfunc.list_datasets(db, user.id, dsid)
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
    user = flask_login.current_user
    rv = dbfunc.list_dataset_entries(db, user.id, dsid)
    return _j(rv)

@app.route('/api/dataset/<int:dsid>/<int:entryid>', methods=['GET'])
#@flask_login.login_required
def ds_fetch_dataset_entry(dsid, entryid):
    user = flask_login.current_user
    rv = dbfunc.get_entry(db, user.id, dsid, entryid)
    return _j(rv)

@app.route('/api/dataset/upload', methods=['POST'])
#@flask_login.login_required
def ds_upload_new_dataset():
    user = flask_login.current_user
    dictname = flask.request.files.get('dictname', None)
    dzcontent = flask.request.files.get('file', None)
    dzfilename = flask.request.files.get('file', None).filename  # !!
    dztotalfilesize = flask.request.form.get('dztotalfilesize', None)
    dzfilepath = os.path.join(APP_MEDIA, secure_filename(dzcontent.filename))
    dzuuid = flask.request.form.get('dzuuid', None)
    dzcontent.save(os.path.join(APP_MEDIA, secure_filename(dzcontent.filename)))
    result = dbfunc.add_dataset(db, user.id, dztotalfilesize, dzfilename, dzfilepath, dzuuid)
    if result:
        return flask.make_response('OK',200)

@app.route('/api/dataset/<int:dsid>/name', methods=['POST'])
#@flask_login.login_required
def ds_rename_dataset():
    user = flask_login.current_user
    pass

# -- transforms
@app.route('/api/transform/list/<int:dsid>', methods=['GET'])
#@flask_login.login_required
def xf_list_transforms(dsid):
    user = flask_login.current_user
    rv = dbfunc.list_transforms(db, user.id, dsid)
    return _j(rv)

@app.route('/api/transform/new', methods=['POST'])
#@flask_login.login_required
def xf_new_transform():
    user = flask_login.current_user

    dsuuid = flask.request.json.get('dsuuid', None)
    dsid = flask.request.json.get('dsid', None)
    xfname = flask.request.json.get('xfname', None)
    entry_spec = flask.request.json.get('entry_spec', None)

    if dsuuid is None or xfname is None or dsid is None or entry_spec is None:
        return flask.make_response(('Invalid API call'), 422)
    xfid = dbfunc.new_transform(db, user.id, dsuuid, xfname, dsid, entry_spec)
    isok, retmsg = dbfunc.prepare_dataset(db, user.id, dsid, xfid, entry_spec)
    if not isok:
        return flask.make_response(retmsg, 422)
    return _j({'xfid': xfid})

@app.route('/api/transform/<int:xfid>', methods=['GET'])
#@flask_login.login_required
def xf_get_transform_spec(xfid):
    user = flask_login.current_user
    rv = dbfunc.describe_transform(db, user.id, xfid)
    return _j(rv)

@app.route('/api/transform/<int:xfid>', methods=['DELETE'])
#@flask_login.login_required
def xf_delete_transform():
    pass

@app.route('/api/transform/<int:xfid>', methods=['POST'])
#@flask_login.login_required
def xf_update_transform(xfid):
    user = flask_login.current_user
    xfspec = flask.request.json.get('xfspec', None)
    if xfspec is None:
        return flask.make_response(('Invalid API call'), 422)
    rv = dbfunc.update_transform(db, user.id, xfid, xfspec)
    return _j({'updated': rv})

@app.route('/api/transform/<int:xfid>/apply/<int:entityid>', methods=['GET'])
#@flask_login.login_required
def xf_entity_transform(xfid,entityid):
    user = flask_login.current_user
    strip_ns = flask.request.args.get('strip_ns', default='false', type=str) == 'true'
    print ('strip_ns', strip_ns)
    entity, spec = dbfunc.get_entity_and_spec(db, user.id, xfid, entityid)

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
    return flask.redirect('/static/login.html')

@app.route('/do_login', methods=['GET', 'POST'])
def login():
    username = flask.request.args.get('login', None)
    password = flask.request.args.get('password', None)

    user = dbfunc.check_login(db, username, password, bcrypt)
    if user is None:
        # proper login handling if more time......
        return flask.redirect('/')
    else:
        flask_login.login_user(user, remember=True)
        return flask.redirect('/static/build_transform.html')

@app.route('/do_logout')
@flask_login.login_required
def logout():
    flask_login.logout_user()
    return flask.redirect('http://elexifier.elex.is/')

@login_manager.unauthorized_handler
def unauthorized():
    return flask.redirect('/')

def main():
    app.run(debug=True, use_reloader=True, host="0.0.0.0", port=8081)

if __name__ == '__main__':
    main()
