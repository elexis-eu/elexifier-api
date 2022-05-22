import flask
from flask import after_this_request
import os
import lxml
import lxml.etree
import traceback
import json

from app import app, db, celery
from app.transformation.models import Transformer
import app.transformation.controllers as controllers
import app.dataset.controllers as Datasets
from app.modules.error_handling import InvalidUsage
from app.modules.log import print_log
from app.user.controllers import verify_user
import app.modules.support as ErrorLog
import app.modules.transformator.dictTransformations3 as DictTransformator


@app.route('/api/transform/list', methods=['GET'])
def xf_list_all_transforms():
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    datasets = Datasets.list_datasets(uid)
    transformations = []
    for dataset in datasets:
        _transformations = controllers.list_transforms(dataset.id)
        for xf in _transformations:
            xf.name = dataset.name + '/' + xf.name
            transformations.append(Transformer.to_dict(xf))
    return flask.make_response(flask.jsonify(transformations), 200)


@app.route('/api/transform/list/<int:dsid>', methods=['GET'])
def xf_list_transforms(dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    order = flask.request.args.get('order', 'ASC').upper()
    rv = controllers.list_transforms(dsid, order=order)
    rv = [Transformer.to_dict(i) for i in rv]
    return flask.make_response(flask.jsonify(rv), 200)


@app.route('/api/transform/saved', methods=['GET'])
def xf_list_saved_transforms():
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    rv = controllers.list_saved_transforms(id)
    rv = flask.jsonify(rv)
    return flask.make_response(rv, 200)


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

    if dsuuid is None or xfname is None or dsid is None or entry_spec is None:
        raise InvalidUsage("Invalid API call.", status_code=422, enum="POST_ERROR")

    try:
        xfid = controllers.new_transform(xfname, dsid, entry_spec, headword, saved)
        isok, retmsg = controllers.prepare_dataset(id, dsid, xfid, entry_spec, headword)
    except Exception as e:
        print(traceback.format_exc())
        message=f'Transformation Id: {xfid}\nTransformation definiton: {entry_spec}\n\n{traceback.format_exc()}'
        ErrorLog.add_error_log(db, dsid, tag='xml_new', message=message)

    if not isok:
        raise InvalidUsage(retmsg, status_code=422, enum="POST_ERROR")
    return flask.make_response({'xfid': xfid}, 200)


@app.route('/api/transform/<int:xfid>', methods=['GET'])
def xf_get_transform_spec(xfid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    page_num = flask.request.args.get('page_num', default='1', type=int)
    rv = controllers.describe_transform(xfid, page_num)
    return flask.make_response(rv, 200)


@app.route('/api/transform/<int:xfid>', methods=['DELETE'])
def xf_delete_transform(xfid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    resp = controllers.delete_transform(id, xfid)
    if resp is None:
        raise InvalidUsage("Transformation does not exist.", status_code=404, enum="TRANSFORMATION_DOESNT_EXIST")
    elif not resp:
        raise InvalidUsage("You do not own this transformation", status_code=401, enum="UNAUTHORIZED")
    else:
        return flask.make_response({'deleted': xfid}, 200)


@celery.task
@app.route('/api/transform/<int:xfid>', methods=['POST'])
def xf_update_transform(xfid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)
    xfspec = flask.request.json.get('xfspec', None)
    saved = flask.request.json.get('saved', False)
    name = flask.request.json.get('name', None)
    print_log(app.name, 'Update transform {}'.format(xfid))
    if xfspec is None:
        raise InvalidUsage("Invalid API call.", status_code=422, enum="POST_ERROR")
    try:
        rv = controllers.update_transform(xfid, xfspec, name, saved)
    except Exception as e:
        print(traceback.format_exc())
        transformer = controllers.list_transforms(None, xfid=xfid)
        message=f'Transformation Id: {xfid}\nTransformation definiton: {xfspec}\n\n{traceback.format_exc()}'
        ErrorLog.add_error_log(db, transformer.dsid, tag='xml_update', message=message)
        rv = 0
    return flask.make_response({'updated': rv}, 200)


@app.route('/api/transform/<int:xfid>/apply/<int:entityid>', methods=['GET'])
def xf_entity_transform(xfid, entityid):
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
    strip_DictScrap = 3 if strip_DictScrap else 0

    entity = Datasets.list_dataset_entries(None, entry_id=entityid).contents
    transformer = controllers.list_transforms(None, xfid=xfid)
    spec = transformer.transform
    metadata = Datasets.dataset_metadata(transformer.dsid)

    if spec is None:
        return flask.make_response({'spec': None, 'entity_xml': None, 'output': None}, 200)

    parserLookup = lxml.etree.ElementDefaultClassLookup(element=DictTransformator.TMyElement)
    myParser = lxml.etree.XMLParser(encoding='utf-8', remove_blank_text=True, recover=True)
    myParser.set_element_class_lookup(parserLookup)
    entity_xml = lxml.etree.fromstring(entity, parser=myParser)

    mapping = DictTransformator.TMapping(spec)
    mapper = DictTransformator.TMapper()
    out_TEI, out_aug, validation = mapper.Transform(mapping, [], [lxml.etree.ElementTree(entity_xml)], makeAugmentedInputTrees=True,
                                        stripForValidation=strip_ns,
                                        stripDictScrap=strip_DictScrap, stripHeader=strip_header,
                                        promoteNestedEntries=True,
                                        returnFirstEntryOnly=True,
                                        metadata=metadata)

    target_xml = '\n' + lxml.etree.tostring(out_TEI, pretty_print=True, encoding='unicode')
    target_xml = target_xml.replace(
        '<entry xmlns:m="http://elex.is/wp1/teiLex0Mapper/meta" xmlns:a="http://elex.is/wp1/teiLex0Mapper/legacyAttributes" xmlns="http://www.tei-c.org/ns/1.0">',
        '<entry>')

    original = '\n' + lxml.etree.tostring(entity_xml, pretty_print=True, encoding='unicode')
    validation = [
        {
            **e,
            "long_message": f'{e["line"]}:{e["column"]}:{e["levelName"]}:{e["typeName"]}:{e["message"]}'
        }
        for e in validation
    ]

    return flask.make_response({'spec': spec, 'entity_xml': original, 'output': target_xml, 'validation': validation}, 200)


@app.route('/api/transform/<int:xfid>/search/<int:dsid>')
def entries_search(xfid, dsid):
    token = flask.request.headers.get('Authorization')
    id = verify_user(token)

    pattern = flask.request.args.get('pattern', default='', type=str)
    result = controllers.search_dataset_entries(db, dsid, xfid, pattern)

    return flask.make_response({'result': result}, 200)


# --- download
@celery.task
def prepare_download(uid, xfid, dsid, strip_ns, strip_header, strip_DictScrap):
    xf = None
    try:
        transformer = controllers.list_transforms(dsid, xfid=xfid)
        dataset = Datasets.list_datasets(uid, dsid=dsid)
        metadata = Datasets.dataset_metadata(dsid)
        config = Datasets.dataset_config(dsid)
        xf = transformer.transform
        ds_path = dataset.file_path
        file_name = dataset.name
        header_Title = metadata['title']
        header_Bibl = metadata['bibliographicCitation']
        header_Publisher = metadata['publisher']

        if "limit_entries" in config:
            limit_entries = config["limit_entries"]
        else:
            limit_entries = -1

        orig_xml = open(ds_path, 'rb').read()
        parserLookup = lxml.etree.ElementDefaultClassLookup(element=DictTransformator.TMyElement)
        myParser = lxml.etree.XMLParser(encoding='utf-8', remove_blank_text=True, recover=True)
        myParser.set_element_class_lookup(parserLookup)
        entity_xml = lxml.etree.fromstring(orig_xml, parser=myParser)
        mapping = DictTransformator.TMapping(xf)
        mapper = DictTransformator.TMapper()
        out_TEI, out_aug, validation = mapper.Transform(mapping, [], [lxml.etree.ElementTree(entity_xml)],
                                                        makeAugmentedInputTrees=True,
                                                        stripForValidation=strip_ns,
                                                        stripHeader=strip_header, stripDictScrap=strip_DictScrap,
                                                        promoteNestedEntries=True,
                                                        headerTitle=header_Title,
                                                        headerPublisher=header_Publisher,
                                                        headerBibl=header_Bibl,
                                                        metadata=metadata,
                                                        maxEntriesToProcess=limit_entries,
                                                    )
        target_xml = lxml.etree.tostring(out_TEI, pretty_print=True, encoding='unicode')

        orig_fname, file_type = file_name.split('.')
        target_fname = orig_fname + '_' + str(xfid) + '_TEI.' + file_type
        target_path = os.path.join(app.config['APP_MEDIA'], target_fname)

        open(target_path, 'a').close()
        with open(target_path, 'w') as out:
            out.write(target_xml)
            out.close()
            controllers.transformer_download_status(xfid, set=True, download_status='Ready')

        validation = [
            {
                **e,
                "long_message": f'{e["line"]}:{e["column"]}:{e["levelName"]}:{e["typeName"]}:{e["message"]}'
            }
            for e in validation
        ]
        validation_path = target_path.replace(".xml", ".log")
        open(validation_path, 'a').close()
        with open(validation_path, 'w') as out:
            out.write(json.dumps(validation, indent=4, sort_keys=True))
            out.close()

    except Exception as e:
        print(traceback.format_exc())
        message = f'Transformation Id: {xfid}\nTransformation definiton: {xf}\n\n{traceback.format_exc()}'
        ErrorLog.add_error_log(db, dsid, tag='xml_download', message=message)
        controllers.transformer_download_status(xfid, set=True, download_status='Error')
        return

    return


@app.route('/api/transform/<int:xfid>/download/<int:dsid>', methods=['GET'])
def ds_download2(xfid, dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    status = controllers.transformer_download_status(xfid)

    get_status = flask.request.args.get('status', default='false', type=str) == 'true'

    if get_status:
        return flask.make_response({'status': status}, 200)

    elif status is None or status == 'Error':
        print_log(app.name, 'Transformed dataset download started uid: {0:s}, xfid: {1:s} , dsid: {2:s}'.format(str(uid), str(xfid), str(dsid)))
        strip_ns = flask.request.args.get('strip_ns', default='false', type=str) == 'true'
        strip_header = flask.request.args.get('strip_header', default='false', type=str) == 'true'
        strip_DictScrap = flask.request.args.get('strip_DictScrap', default='false', type=str) == 'true'
        strip_DictScrap = strip_ns  # TODO: remove this, when added to FE

        # Check if transformer exists
        try:
            transform = controllers.list_transforms(dsid, xfid=xfid)
            xf = transform.transform
        except:
            raise InvalidUsage('Transformer does not exist.', status_code=409)

        if xf is None:  # Not sure why this is needed here?
            return flask.make_response({'spec': None, 'entity_xml': None, 'output': None}, 200)
        else:
            # start download task
            prepare_download.apply_async(args=[uid, xfid, dsid, strip_ns, strip_header, strip_DictScrap], countdown=0)
            status = 'Processing'
            controllers.transformer_download_status(xfid, set=True, download_status=status)

    elif status == "Processing":
        return flask.make_response({'message': 'File is still processing'}, 200)

    elif status == "Ready":
        print_log(app.name, 'Transformed dataset download finished uid: {0:s}, xfid: {1:s} , dsid: {2:s}'.format(str(uid), str(xfid), str(dsid)))
        # return file and delete afterwards
        dataset = Datasets.list_datasets(uid, dsid=dsid)
        file_name, file_type = dataset.name.split('.')
        target_file_name = file_name + '_' + str(xfid) + '_TEI.' + file_type
        target_path = os.path.join(app.config['APP_MEDIA'], target_file_name)

        @after_this_request
        def remove_file(response):
            response.headers['x-suggested-filename'] = out_name
            response.headers.add('Access-Control-Expose-Headers', '*')
            os.remove(target_path)
            return response

        controllers.transformer_download_status(xfid, set=True)  # reset status
        transform_name = controllers.list_transforms(dsid, xfid=xfid).name
        out_name = dataset.name[:-4] + '-' + transform_name + '.xml'
        return flask.send_file(target_path, attachment_filename=out_name, as_attachment=True)

    return flask.make_response({'message': 'ok', 'status': status}, 200)


@app.route('/api/transform/<int:xfid>/validation/<int:dsid>', methods=['GET'])
def get_validation_log(xfid, dsid):
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)

    dataset = Datasets.list_datasets(uid, dsid=dsid)
    file_name, _ = dataset.name.split('.')
    target_file_name = file_name + '_' + str(xfid) + '_TEI.log'
    target_path = os.path.join(app.config['APP_MEDIA'], target_file_name)
    transform_name = controllers.list_transforms(dsid, xfid=xfid).name
    out_name = dataset.name[:-4] + '-' + transform_name + '-validation.log'

    if not os.path.exists(target_path):
        raise InvalidUsage('No validation file found, retry downloading file without namespaces.', status_code=409)

    @after_this_request
    def remove_file(response):
        response.headers['x-suggested-filename'] = out_name
        response.headers.add('Access-Control-Expose-Headers', '*')
        os.remove(target_path)
        return response

    return flask.send_file(target_path, attachment_filename=out_name, as_attachment=True)
