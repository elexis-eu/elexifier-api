import json
import os
import magic
import lxml
import lxml.etree
import re
import sqlalchemy
import subprocess
import copy

from app import app, db, celery
from app.dataset.models import Datasets, Datasets_single_entry
from app.transformation.models import Transformer
from app.modules.support import Error_log
from app.modules.log import print_log


# TODO: remove this
def extract_keys(cur, single=False):
    dataset = list(cur.fetchall())
    #print(dataset)
    rv = [ {key:row[key] for key in row.keys()} for row in dataset]
    if not single:
        return rv
    else:
        return rv[0] if len(rv) > 0 else None


def add_dataset(db, uid, dztotalfilesize, dzfilename, dzfilepath, dzuuid):
    with magic.Magic(flags=magic.MAGIC_MIME_TYPE) as m:
        mimetype = m.id_filename(dzfilepath)

    xml_path = None
    if mimetype == "application/pdf":
        xml_path = dzfilepath[:-4] + ".xml"
    elif mimetype in ['text/plain', 'text/html']:
        mimetype = 'text/xml'

    # Create
    status = json.dumps({'annotate': None, 'ml': None, 'preview': None, 'download': None})
    dataset = Datasets(uid=uid, name=dzfilename, size=dztotalfilesize, file_path=dzfilepath, upload_mimetype=mimetype, upload_uuid=dzuuid, xml_file_path=xml_path, status=status)
    print_log(app.name, 'Adding dataset: {}'.format(dataset))
    db.session.add(dataset)
    db.session.commit()
    return dataset.id


def delete_dataset(dsid):
    dataset = Datasets.query.filter_by(id=dsid).first()
    print('Delete {0}'.format(dataset))
    db.session.commit()
    # delete transformations
    db.session.query(Transformer).filter(Transformer.dsid == dataset.id).delete()
    # delete error_logs
    db.session.query(Error_log).filter(Error_log.dsid == dsid).delete()
    db.session.query(Datasets_single_entry).filter(Datasets_single_entry.dsid == dataset.id).delete()
    db.session.query(Datasets).filter(Datasets.id == dataset.id).delete()
    db.session.commit()
    try:
        os.remove(dataset.file_path)
        os.remove(dataset.xml_file_path)
        os.remove(dataset.xml_lex)
        os.remove(dataset.xml_out)
    except:
        pass
    return


def list_datasets(uid, dsid=None, order='ASC', mimetype='text/xml'):
    if dsid is not None:
        result = Datasets.query.filter_by(id=dsid).first()
        if result.status is not None:
            result.status = json.loads(result.status)
        db.session.close()
        return result
    elif order is 'ASC':
        result = Datasets.query.filter_by(uid=uid, upload_mimetype=mimetype).order_by(sqlalchemy.asc(Datasets.uploaded_ts)).all()
    else:
        result = Datasets.query.filter_by(uid=uid, upload_mimetype=mimetype).order_by(sqlalchemy.desc(Datasets.uploaded_ts)).all()
    db.session.close()
    return result  # [Datasets.to_dict(i) for i in result]


def list_dataset_entries(dsid, entry_id=None):
    if entry_id is not None:
        result = Datasets_single_entry.query.filter_by(id=entry_id).first()
    else:
        result = Datasets_single_entry.query.filter_by(dsid=dsid).all()
    db.session.close()
    return result


def dataset_metadata(dsid, set=False, metadata=None):
    dataset = Datasets.query.filter_by(id=dsid).first()
    if set:
        if not isinstance(metadata, str):
            metadata = json.dumps(metadata)
        dataset.dictionary_metadata = metadata
        db.session.commit()
    else:
        metadata = dataset.dictionary_metadata
        metadata = json.loads(metadata)
        db.session.close()
    return metadata


def clean_empty_namespace(dsid):
    dataset = Datasets.query.filter_by(id=dsid).first()
    db.session.close()
    with open(dataset.file_path, 'r') as f:
        xml_data = f.read()
    xml_data = re.sub('xmlns=".*?"', '', xml_data)
    with open(dataset.file_path, 'w') as f:
        f.write(xml_data)


@celery.task
def transform_pdf2xml(dsid):
    dataset = Datasets.query.filter_by(id=dsid).first()
    db.session.close()

    bashCommands = ['./app/modules/transformator/pdftoxml -noImage -readingOrder {0:s}'.format(dataset.file_path)]
    for command in bashCommands:
        subprocess.run(command.split(" "))

    xml_file_path = dataset.file_path[:-4] + '.xml'

    punctuation_types = ['.', ',', ';', ':', '!', '?', '’']
    punctiation_counter = 0
    curr_line = '1'

    parser = lxml.etree.XMLParser(encoding='utf-8', recover=True)
    root = lxml.etree.parse(xml_file_path, parser=parser).getroot()
    body = root.xpath('.//BODY')[0]

    for token in body[1:]:
        # if new line -> reset the punctuation counter
        if token.attrib['line'] != curr_line:
            curr_line = token.attrib['line']
            punctiation_counter = 0

        # add number of punctuations to token word number
        token.attrib['word'] = str(int(token.attrib['word']) + punctiation_counter)

        # if punctuation is at the end of word
        if len(token.text) > 1 and token.text[-1] in punctuation_types:
            # split all punctuations in separate tokens
            pun_tokens = [token]
            for char in token.text[::-1]:
                if char in punctuation_types:
                    pun_token = copy.copy(token)
                    pun_token.text = char
                    pun_tokens.append(pun_token)
                    pun_tokens[-1].attrib['word'] = str(int(pun_tokens[-2].attrib['word']) + 1)
                else:
                    pun_tokens.pop(0)
                    break

            # delete punctuations from original text
            token.text = token.text[:len(pun_tokens)]
            punctiation_counter += len(pun_tokens)

            # insert punctuations
            for i in range(len(pun_tokens)):
                body.insert(body.index(token) + i + 1, pun_tokens[i])

    file = open(xml_file_path, 'w')
    new_xml = lxml.etree.tostring(root, pretty_print=True, encoding='utf8').decode('utf8')
    file.write(new_xml)
    file.close()


@celery.task
def map_xml_tags(dsid):
    def xml_walk(node, acc={}):
        tag = node.tag
        if type(tag) is not str:
            return acc
            # we skip non-string, since there can appear tags that get transformed into functions

        if tag not in acc:
            acc[tag] = {'parent': [], 'child': []}
        # add parent to accumulator
        try:
            parent_tag = node.getparent().tag
            if parent_tag not in acc[tag]['parent']:
                acc[tag]['parent'].append(parent_tag)
        except:
            pass  # root node has no parent
        # search children
        for child in node:
            child_tag = child.tag
            if type(child_tag) is not str:
                continue
                # avoid saving non-strings as above

            if child_tag not in acc[tag]['child']:
                acc[tag]['child'].append(child_tag)
            acc = xml_walk(child, acc=acc)
        return acc

    dataset = Datasets.query.filter_by(id=dsid).first()
    parser = lxml.etree.XMLParser(encoding='utf-8', recover=True)
    tree = lxml.etree.parse(dataset.file_path, parser=parser)
    tags_json = xml_walk(tree.getroot())
    dataset.xml_tags = tags_json
    db.session.commit()
    return


def get_xml_tags(dsid):
    dataset = Datasets.query.filter_by(id=dsid).first()
    db.session.close()
    return dataset.xml_tags


def extract_pos_elements(xml_file, pos_element, attribute_name):
    parser = lxml.etree.XMLParser(encoding='utf-8', recover=True)
    tree = lxml.etree.parse(xml_file, parser=parser)
    namespaces = tree.getroot().nsmap

    result = []
    for pos_el in pos_element:
        result.extend(tree.xpath('//' + pos_el, namespaces=namespaces))
    unique_pos = set()

    for el in result:
        pos = ''
        if attribute_name is not None and attribute_name in el.attrib.keys():
            pos = el.attrib[attribute_name].strip()
        elif el.text and attribute_name is None:
            pos = el.text.strip()
        else:
            continue
        unique_pos.add(pos)
        if len(unique_pos) > 100: # limiting the number of pos outputs
            break
    return sorted(list(unique_pos))


def get_pos_elements(db, dsid, pos_json):
    pos_element = pos_json['pos_element']
    attribute_name = pos_json['attribute_name']
    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    db.session.commit()

    if dataset.pos_elements is not None:
        pos_elms = json.loads(dataset.pos_elements)
        if pos_elms['pos_element'] == pos_element and pos_elms['attribute_name'] == attribute_name:
            return pos_elms
    
    pos_elms = extract_pos_elements(dataset.file_path, pos_element, attribute_name)
    pos_elms = {
        'pos_element': pos_element,
        'attribute_name': attribute_name,
        'pos': sorted(list(pos_elms))
    }
    dataset.pos_elements = json.dumps(pos_elms)
    db.session.commit()
    return pos_elms


def extract_xpaths(db, dsid):
    print('extract_xpaths')

    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    xml_file = dataset.file_path
    db.session.commit()

    parser = lxml.etree.XMLParser(encoding='utf-8', recover=True)
    tree = lxml.etree.parse(xml_file, parser=parser)
    nodes = ['%s, %s' % (tree.getpath(e), e.text) for e in tree.iter()]
    unique_nodes = []
    for node in nodes:
        node = node.strip().split(',')[0].lstrip('/oxford/')
        node = ''.join([c for c in node if not c.isdigit()])
        node = ''.join([c for c in node if c not in '[]'])
        if node not in unique_nodes:
            unique_nodes.append(node)

    all_paths = []
    for node in unique_nodes:
        els = node.split('/')
        print(node, len(els))
        for i in range(len(els)):
            path = '/'.join(els[i:len(els)])
            if path not in all_paths:
                all_paths.append(path)

    return all_paths


def clean_tag(xml_tag):
    pattern = re.compile("\{http:\/\/")
    if pattern.match(xml_tag):
        m = re.search('\}.{1,10000}', xml_tag)
        if m:
            return m.group(0)[1:]
    else:
        return xml_tag


def extract_xml_heads(db, dsid):
    print('extract xml head')
    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    db.session.commit()

    if dataset.head_elements is not None:
        return json.loads(dataset.head_elements)
    else:
        xml_file = dataset.file_path

        parser = lxml.etree.XMLParser(encoding='utf-8', recover=True)
        tree = lxml.etree.parse(xml_file, parser=parser)
        unique_tags = set()
        for element in tree.iter():
            if type(element.tag) is not str:
                continue  # we skip non-string, since there can appear tags that get transformed into functions
            unique_tags.add(clean_tag(element.tag))

        unique_tags = sorted(list(unique_tags))
        dataset.head_elements = json.dumps(unique_tags)
        db.session.commit()

        return unique_tags


def update_dataset_status(dsid, status):
    if not isinstance(status, str):
        status = json.dumps(status)
    dataset = Datasets.query.filter_by(id=dsid).first()
    dataset.status = status
    db.session.commit()
    return status


def dataset_status(dsid, set=False, status=None):
    dataset = Datasets.query.filter_by(id=dsid).first()
    if set:
        if not isinstance(status, str):
            status = json.dumps(status)
        dataset.status = status
    else:
        status = json.loads(dataset.status)
    db.session.commit()
    return status


# --- lexonomy ---
def dataset_add_lexonomy_access(dsid, lexonomy_access=None, lexonomy_edit=None, lexonomy_delete=None, lexonomy_status=None):
    dataset = Datasets.query.filter_by(id=dsid).first()
    dataset.lexonomy_access = lexonomy_access
    dataset.lexonomy_edit = lexonomy_edit
    dataset.lexonomy_delete = lexonomy_delete
    dataset.lexonomy_status = lexonomy_status
    db.session.commit()
    return dsid


# --- ml ---
def dataset_add_ml_paths(dsid, xml_lex=None, xml_ml_out=None):
    dataset = Datasets.query.filter_by(id=dsid).first()
    dataset.xml_lex = xml_lex
    dataset.xml_ml_out = xml_ml_out
    db.session.commit()
    return dsid


def dataset_add_ml_lexonomy_access(dsid, lexonomy_access=None, lexonomy_edit=None, lexonomy_delete=None, lexonomy_status=None):
    dataset = Datasets.query.filter_by(id=dsid).first()
    dataset.lexonomy_ml_access = lexonomy_access
    dataset.lexonomy_ml_edit = lexonomy_edit
    dataset.lexonomy_ml_delete = lexonomy_delete
    dataset.lexonomy_ml_status = lexonomy_status
    db.session.commit()
    return dsid


def dataset_character_map(dsid, set=False, character_map=None):
    dataset = Datasets.query.filter_by(id=dsid).first()
    if set:
        dataset.character_map = character_map
    else:
        character_map = dataset.character_map
    db.session.commit()
    return character_map


def dataset_ml_task_id(dsid, set=False, task_id=None):
    dataset = Datasets.query.filter_by(id=dsid).first()
    if set:
        dataset.ml_task_id = task_id
        db.session.commit()
    else:
        db.session.close()
    return dataset.ml_task_id

