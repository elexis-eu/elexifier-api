import json
import os
import magic
import lxml
import lxml.etree
import re
import sqlalchemy

from app import app, db
from app.dataset.models import Datasets, Datasets_single_entry
from app.transformation.models import Transformer


def extract_keys(cur, single=False):
    dataset = list(cur.fetchall())
    #print(dataset)
    rv = [ {key:row[key] for key in row.keys()} for row in dataset]
    if not single:
        return rv
    else:
        return rv[0] if len(rv) > 0 else None


def add_dataset(db, uid, dztotalfilesize, dzfilename, dzfilepath, dzuuid, headerTitle, headerPublisher, headerBibl):
    print('add dataset')

    with magic.Magic(flags=magic.MAGIC_MIME_TYPE) as m:
        mimetype = m.id_filename(dzfilepath)

    xml_path = None
    if mimetype == "application/pdf":
        xml_path = dzfilepath[:-4] + ".xml"
    elif mimetype == 'text/plain':
        mimetype = 'text/xml'

    # Create
    dataset = Datasets(uid=uid, name=dzfilename, size=dztotalfilesize, file_path=dzfilepath, upload_mimetype=mimetype, upload_uuid=dzuuid, xml_file_path=xml_path, header_title=headerTitle, header_publisher=headerPublisher, header_bibl=headerBibl)
    db.session.add(dataset)
    db.session.commit()
    return dataset.id


def delete_dataset(db, uid, dsid):
    print('Delete dataset uid: {0:s}, dsid: {1:s}'.format(str(uid), str(dsid)))
    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).filter(Datasets.uid == uid).first()
    db.session.commit()
    db.session.query(Transformer).filter(Transformer.dsid == dataset.id).delete()
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
        db.session.close()
        return result
    elif order is 'ASC':
        result = Datasets.query.filter_by(uid=uid, upload_mimetype=mimetype).order_by(sqlalchemy.desc(Datasets.uploaded_ts)).all()
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
        dataset.dictionary_metadata = metadata
        db.session.commit()
    else:
        metadata = dataset.dictionary_metadata
        db.session.close()
    return metadata


def map_xml_tags(db, dsid):
    def xml_walk(node, acc={}):
        tag = node.tag
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
            if child_tag not in acc[tag]['child']:
                acc[tag]['child'].append(child_tag)
            acc = xml_walk(child, acc=acc)
        return acc

    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    db.session.commit()
    print(dataset.file_path, "<----------")
    tree = lxml.etree.parse(dataset.file_path)
    tags_json = xml_walk(tree.getroot())
    dataset.xml_tags = tags_json
    db.session.commit()
    return


def get_xml_tags(db, dsid):
    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    return dataset.xml_tags


def extract_pos_elements(db, dsid, pos_element, attribute_name=None):
    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    db.session.commit()
    if dataset.pos_elements != None:
        return json.loads(dataset.pos_elements)
    else:
        xml_file = dataset.file_path
        tree = lxml.etree.parse(xml_file)
        namespaces = tree.getroot().nsmap
        namespace = ''
        namespace_prefix = False
        for prefix, ns in namespaces.items():
            if prefix:
                namespace_prefix = True
                namespace = {prefix: ns}
                break
            else:
                namespace = ns

        if namespace_prefix:
            pos_els = tree.xpath('//' + pos_element, namespaces=namespace)
        else:
            pos_els = tree.xpath('//' + pos_element)

        unique_pos = []
        if attribute_name:
            for el in pos_els:
                pos = el.attrib[attribute_name].strip()
                unique_pos.append(pos)
        else:
            for el in pos_els:
                if el.text.strip() not in unique_pos:
                    unique_pos.append(el.text.strip())

        pos_elements = json.dumps(sorted(unique_pos))
        dataset.pos_elements = pos_elements
        db.session.commit()
        return json.loads(pos_elements)


def extract_xpaths(db, dsid):
    print('extract_xpaths')

    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    xml_file = dataset.file_path
    db.session.commit()

    tree = lxml.etree.parse(xml_file)
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

        tree = lxml.etree.parse(xml_file)
        unique_tags = set()
        for element in tree.iter():
            unique_tags.add(clean_tag(element.tag))

        unique_tags = sorted(list(unique_tags))
        dataset.head_elements = json.dumps(unique_tags)
        db.session.commit()

        return unique_tags


# TODO: don't do it like this
def set_dataset_status(db, uid, dsid, status):
    connection = db.connect()
    query = "UPDATE datasets SET status = '{0:s}' WHERE uid = {1:s} AND id = {2:s}".format(status, str(uid), str(dsid))
    connection.execute(query)
    connection.close()
    return dsid


# --- lexonomy ---
# TODO: don't do it like this
def dataset_add_lexonomy_access(db, dsid, lexonomy_access=None, lexonomy_edit=None, lexonomy_delete=None, lexonomy_status=None):
    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    dataset.lexonomy_access = lexonomy_access
    dataset.lexonomy_edit = lexonomy_edit
    dataset.lexonomy_delete = lexonomy_delete
    dataset.lexonomy_status = lexonomy_status
    db.session.commit()
    return dsid


# --- ml ---
# TODO: don't do it like this
def dataset_add_ml_paths(db, uid, dsid, xml_lex, xml_ml_out):
    connection = db.connect()
    query = "UPDATE datasets SET xml_lex = '{0:s}', xml_ml_out = '{1:s}' WHERE uid = {2:s} AND id = {3:s}".format(str(xml_lex), str(xml_ml_out), str(uid), str(dsid))
    connection.execute(query)
    connection.close()
    return dsid


# TODO: don't do it like this
def dataset_add_ml_lexonomy_access(db, dsid, lexonomy_access=None, lexonomy_edit=None, lexonomy_delete=None, lexonomy_status=None):
    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    dataset.lexonomy_ml_access = lexonomy_access
    dataset.lexonomy_ml_edit = lexonomy_edit
    dataset.lexonomy_ml_delete = lexonomy_delete
    dataset.lexonomy_ml_status = lexonomy_status
    db.session.commit()
    return dsid


def dataset_character_map(db, dsid, set=False, character_map=None):
    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    if set:
        dataset.character_map = character_map
    else:
        character_map = dataset.character_map
    db.session.commit()
    return character_map


def dataset_ml_task_id(db, dsid, set=False, task_id=None):
    connection = db.connect()
    if not set:
        query = "SELECT ml_task_id FROM datasets where id={0:s}".format(str(dsid))
        result = connection.execute(query)
        task_id = extract_keys(result)[0]['ml_task_id']
    else:
        query = "UPDATE datasets SET ml_task_id = '{0:s}' where id = {1:s}".format(task_id, str(dsid))
        connection.execute(query)
    connection.close()
    return task_id
