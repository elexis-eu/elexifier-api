import flask
import json
import os
import requests
import lxml
import lxml.etree
import string
import random
from werkzeug.utils import secure_filename
from urllib.request import urlopen
from zipfile import ZipFile
from io import BytesIO

from app import app, db, celery
from app.user.controllers import verify_user
import app.dataset.controllers as Datasets
from app.modules.error_handling import InvalidUsage


# --- controllers
VALID_MIMETYPES = ['text/xml', 'application/pdf', 'application/zip']


def transform_handle(handle):
    handle = handle.strip().split('hdl.handle.net/')
    return handle[-1]


def get_clarin_definition(clarin_id):
    """
    Get Clarin repository definition.
    If it does not exist, returns False.
    """
    url = f"http://www.clarin.si/repository/oai/request?verb=GetRecord&metadataPrefix=cmdi&identifier=oai:www.clarin.si:{clarin_id}"
    parser = lxml.etree.XMLParser(encoding='utf-8', recover=True)
    resp = requests.get(url)
    text = resp.text.replace("<?xml version='1.0' encoding='UTF-8'?>", '')
    definition = lxml.etree.fromstring(text, parser=parser)
    if len(definition.xpath('.//*[local-name()="error"][@code="idDoesNotExist"]')) > 0:
        raise InvalidUsage('Invalid handle.', status_code=400, enum='CLARIN_ERROR')
    return definition


def build_metadata(definition):
    metadata = {
        'acronym': 'CLRN',
        'creator': []
    }
    xpath = {
        'title':'.//*[local-name()="title"]',
        'creator': './/*[local-name()="author"]',
        'publisher': './/*[local-name()="publisher"]',
        'license': './/*[local-name()="license"]/*[local-name()="uri"]',
        'identifier': './/*[local-name()="identifier"][@type="Handle"]',
        'created': './/*[local-name()="dates"]/*[local-name()="dateIssued"]',
        'source': './/*[local-name()="projectUrl"]'
    }
    for key in xpath:
        result = definition.xpath(xpath[key])
        if len(result) == 0:
            continue
        if key == 'creator':
            for author in result:
                try:
                    first = author.xpath('.//*[local-name()="firstName"]')[0].text.strip()
                    last = author.xpath('.//*[local-name()="lastName"]')[0].text.strip()
                    metadata['creator'].append({'name': f'{first} {last}'})
                except:
                    continue
        else:
            metadata[key] = result[0].text
    return metadata


def find_clarin_resources(definition):
    global VALID_MIMETYPES
    found = []
    for mimetype in VALID_MIMETYPES:
        resources = definition.xpath(f'.//*[local-name()="ResourceType"][@mimetype="{mimetype}"]')
        if len(resources) == 0:
            continue
        for resource in resources:
            url = resource.getparent()[1].text
            if mimetype == 'application/zip':
                resp = urlopen(url)
                if mimetype == 'application/zip':
                    zipfile = ZipFile(BytesIO(resp.read()))
                    found.extend([i for i in zipfile.namelist() if i[-3:].lower() in ['pdf', 'xml']])
            else:
                name = url.split('/')[-1].split('?')[0]
                found.append(name)
    return found


def download_clarin_resources(definition, chosen_files):
    global VALID_MIMETYPES
    downloaded = []
    for mimetype in VALID_MIMETYPES:
        resources = definition.xpath(f'.//*[local-name()="ResourceType"][@mimetype="{mimetype}"]')
        if len(resources) == 0:
            continue
        for resource in resources:
            url = resource.getparent()[1].text
            name = url.split('/')[-1].split('?')[0]
            if mimetype != 'application/zip' and name not in chosen_files:
                # If it's not a ZIP file and we dont need it -> skip it
                continue
            resp = urlopen(url)
            if mimetype != 'application/zip':
                filename = os.path.join(app.config['APP_MEDIA'], name)
                with open(filename, 'wb') as file:
                    file.write(resp.read())
                    downloaded.append((filename, mimetype))
            # Special handling for ZIP files
            else:
                zipfile = ZipFile(BytesIO(resp.read()))
                for zip_filename in chosen_files:
                    if zip_filename in zipfile.namelist():
                        filename = zip_filename.split('/')[-1]
                        filename = os.path.join(app.config['APP_MEDIA'], filename)
                        with open(filename, 'wb') as file:
                            file.write(zipfile.read(zip_filename))
                            downloaded.append((filename, filename[-3:]))
    return downloaded



def generate_filename(filename, stringLength=20):
    extension = filename.split('.')[-1]
    letters = string.ascii_lowercase
    return ''.join(random.choice(letters) for i in range(stringLength)) + '.' + extension


# --- views ---
@app.route('/api/clarin/new', methods=['POST'])
def get_clarin_resource():
    token = flask.request.headers.get('Authorization')
    uid = verify_user(token)
    handle = flask.request.json.get('handle', None)
    chosen_files = flask.request.json.get('files', None)
    acronym = flask.request.json.get('acronym', 'CLRN')

    if handle is None:
        raise InvalidUsage('Missing handle.', status_code=400, enum='CLARIN_ERROR')
    handle = transform_handle(handle)
    clarin_definition = get_clarin_definition(handle)
    metadata = build_metadata(clarin_definition)
    found_files = find_clarin_resources(clarin_definition)
    metadata['acronym'] = acronym
    # We let user choose which files to import
    if chosen_files is None:
        return flask.make_response({'message': 'ok', 'metadata': metadata, 'found': found_files}, 200)

    # Lets download chosen files 
    for filename, mimetype in download_clarin_resources(clarin_definition, chosen_files):
        orig_name = os.path.basename(filename)
        total_filesize = os.path.getsize(filename)
        new_random_name = generate_filename(filename)
        new_path = os.path.join(app.config['APP_MEDIA'], secure_filename(new_random_name))
        os.rename(filename, new_path)
        dsid = Datasets.add_dataset(db, uid, total_filesize, orig_name, new_path, 0)
        Datasets.dataset_metadata(dsid, set=True, metadata=metadata)

        # prepare dataset
        try:
            if "pdf" in mimetype:
                Datasets.transform_pdf2xml.apply_async(args=[dsid])
            else:
                Datasets.clean_empty_namespace(dsid)
                Datasets.map_xml_tags.apply_async(args=[dsid])
        except Exception as e:
            print(traceback.format_exc())
            ErrorLog.add_error_log(db, dsid, tag='upload', message=traceback.format_exc())
    return flask.make_response({'message': 'ok',
                                'metadata': metadata,
                                'found': found_files,
                                'downloaded': chosen_files}, 200)


# --- test ---
# HANDLE = 'http://hdl.handle.net/11356/1214'  # ZIP/XML | Developmental corpus Šolar 2.0
# HANDLE = 'http://hdl.handle.net/11356/1475'  # XML | The Croatian web dictionary Mrežnik (A-F) 1.0
# HANDLE = 'http://hdl.handle.net/11356/1470'   # ZIPs | Corpus of term-annotated texts RSDO5 1.1
# if __name__ == '__main__':
#     CLARIN_ID = transform_handle(HANDLE)
# 
#     definition = get_clarin_definition(CLARIN_ID)
# 
#     print(f'DEFINITION:\n{lxml.etree.tostring(definition, pretty_print=True).decode()}')
# 
#     metadata = build_metadata(definition)
# 
#     print(f'METADATA:\n{json.dumps(metadata, indent=4, ensure_ascii=False)}')
#     get_resource(definition)