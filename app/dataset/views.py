import os
import random
import string
import subprocess

import flask
import lxml
from flask.json import jsonify
from werkzeug.utils import secure_filename

import app.dataset.controllers as controllers  # TODO: don't import controllers like this
from app import app, db, celery
from app.dataset.models import Datasets, Datasets_single_entry
from app.modules.error_handling import InvalidUsage
from app.user.controllers import verify_user


@app.route('/api/dataset/list', methods=['GET'])
def ds_list_datasets():
    token = flask.request.headers.get('Authorization')
    mimetype = flask.request.args.get('mimetype')
    uid = verify_user(token)

    order = flask.request.args.get('order')
    if isinstance(order, str):
        order = order.upper()
    else:
        order = "ASC"
    if not isinstance(mimetype, str):
        mimetype = "text/xml"
    datasets = [Datasets.to_dict(i) for i in controllers.list_datasets(uid, order=order, mimetype=mimetype)]
    return flask.make_response(jsonify(datasets), 200)


@app.route('/api/dataset/<int:dsid>', methods=['GET'])
def ds_dataset_info(dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    dataset = controllers.list_datasets(uid, dsid=dsid)
    dataset = Datasets.to_dict(dataset)
    return flask.make_response(jsonify(dataset), 200)


@celery.task
def delete_dataset_async(dsid):
    # TODO: delete error_logs
    controllers.delete_dataset(dsid)


@app.route('/api/dataset/<int:dsid>', methods=['DELETE'])
def ds_delete_dataset(dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    delete_dataset_async.apply_async(args=[dsid])

    return flask.make_response(jsonify({'deleted': dsid}), 200)


@app.route('/api/dataset/<int:dsid>/preview', methods=['GET'])
def ds_dataset_preview(dsid):
    raise InvalidUsage('Not implemented', status_code=501)
    pass


@app.route('/api/dataset/<int:dsid>/entries', methods=['GET'])
def ds_list_entries(dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    headwords = flask.request.args.get('headwords', default='false', type=str) == 'true'  # this is not used
    rv = [Datasets_single_entry.to_dict(i) for i in controllers.list_dataset_entries(dsid)]
    return flask.make_response(jsonify(rv), 200)


@app.route('/api/dataset/<int:dsid>/<int:entryid>', methods=['GET'])
def ds_fetch_dataset_entry(dsid, entryid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    headwords = flask.request.args.get('headwords', default='false', type=str) == 'true'
    rv = Datasets_single_entry.to_dict(controllers.list_dataset_entries(dsid, entry_id=entryid))
    return flask.make_response(jsonify(rv), 200)


def generate_filename(filename, stringLength=20):
    extension = filename.split('.')[-1]
    letters = string.ascii_lowercase
    return ''.join(random.choice(letters) for i in range(stringLength)) + '.' + extension


def transform_pdf2xml(dataset):
    bashCommands = ['./app/modules/transformator/pdftoxml -noImage -readingOrder {0:s}'.format(dataset.file_path)]
    for command in bashCommands:
        subprocess.run(command.split(" "))


@app.route('/api/dataset/upload', methods=['POST'])
def ds_upload_new_dataset():
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)

    # file
    metadata = flask.request.form.get('metadata', None)
    dictname = flask.request.files.get('dictname', None)
    file_content = flask.request.files.get('file', None)
    total_filesize = flask.request.form.get('dztotalfilesize', None)
    dzuuid = flask.request.form.get('dzuuid', None)

    current_chunk = int(flask.request.form.get('dzchunkindex'))
    total_chunks = int(flask.request.form.get('dztotalchunkcount', None))
    chunk_offset = int(flask.request.form.get('dzchunkbyteoffset', None))

    # get file extension
    try:
        orig_filename = file_content.filename
        extension = '.' + file_content.filename.split('.')[-1]
    except AttributeError:
        orig_filename = 'Dictionary'
        extension = '.xml'

    filename = "tempFile_USER-{0:s}".format(str(uid)) + extension
    filepath = os.path.join(app.config['APP_MEDIA'], secure_filename(filename))

    if os.path.exists(filepath) and current_chunk == 0:
        os.remove(filepath)
        raise InvalidUsage('File already exists.', status_code=400, enum='FILE_EXISTS')

    try:  # write to file
        with open(filepath, 'ab') as f:
            f.seek(chunk_offset)
            f.write(file_content.stream.read())
    except OSError:
        raise InvalidUsage("Not sure why, but we couldn't write the file to disk.", status_code=500, enum="FILE_ERROR")

    if current_chunk != total_chunks:
        return flask.make_response(jsonify({'status': 'OK',
                                            'filename': filename,
                                            'current_chunk': current_chunk,
                                            'total_chunks': total_chunks}), 200)
    else:  # finish upload
        if os.path.getsize(filepath) != int(total_filesize):
            os.remove(filepath)
            raise InvalidUsage("Size mismatch.", status_code=500, enum="FILE_ERROR")
        else:
            new_random_name = generate_filename(filename)
            new_path = os.path.join(app.config['APP_MEDIA'], secure_filename(new_random_name))
            os.rename(filepath, new_path)
            dsid = controllers.add_dataset(db, uid, total_filesize, orig_filename, new_path, dzuuid)
            controllers.dataset_metadata(dsid, set=True, metadata=metadata)

            # prepare dataset
            dataset = controllers.list_datasets(uid, dsid)
            if "pdf" in dataset.upload_mimetype:
                transform_pdf2xml(dataset)
            else:
                controllers.map_xml_tags(db, dsid)
        return flask.make_response(Datasets.to_dict(dataset), 200)


@app.route('/api/dataset/<int:dsid>/name', methods=['POST'])
def ds_rename_dataset(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    raise InvalidUsage('Not implemented', status_code=501)
    pass


@app.route('/api/dataset/<int:dsid>/tags', methods=['GET'])
def get_dataset_tags(dsid):
    return controllers.get_xml_tags(dsid)


@celery.task
@app.route('/api/dataset/<int:dsid>/validate-path', methods=['POST'])
def validate_path(dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    paths = flask.request.json.get('paths', [])

    dataset = controllers.list_datasets(uid, dsid=dsid)
    tree = lxml.etree.parse(dataset.file_path)
    namespaces = tree.getroot().nsmap
    out = []

    for path in paths:
        _path = ".//" + "/".join(path)
        if len(tree.xpath(_path, namespaces=namespaces)) > 0:
            out.append(path)

    return flask.make_response(jsonify({'paths': out}), 200)


@app.route('/api/xml_nodes/<int:dsid>', methods=['GET'])
def ds_list_nodes(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    nodes = controllers.extract_xml_heads(db, dsid)
    return flask.make_response({'nodes': nodes}, 200)


@app.route('/api/xml_paths/<int:dsid>', methods=['GET'])
def ds_list_paths(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    nodes = controllers.extract_xpaths(db, dsid)
    return flask.make_response({'paths': nodes}, 200)


@app.route('/api/xml_pos/<int:dsid>', methods=['GET'])
def ds_pos(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    pos_element = flask.request.args.get('pos_element', type=str)
    attribute_name = flask.request.args.get('attribute_name', type=str)
    if len(attribute_name) != 0:
        nodes = controllers.extract_pos_elements(db, dsid, pos_element, attribute_name)
    else:
        nodes = controllers.extract_pos_elements(db, dsid, pos_element)
    return flask.make_response({'pos': nodes}, 200)


@app.route('/api/save_metadata/<int:dsid>', methods=['POST'])
def ds_save_metadata(dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    ds_metadata = flask.request.json.get('ds_metadata', None)
    rv = controllers.dataset_metadata(dsid, set=True, metadata=ds_metadata)
    return flask.make_response({'done': rv}, 200)


@app.route('/api/get_metadata/<int:dsid>', methods=['GET'])
def ds_get_metadata(dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    ds_metadata = controllers.dataset_metadata(dsid)
    return flask.make_response({'metadata': ds_metadata}, 200)
