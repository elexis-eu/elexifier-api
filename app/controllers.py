import magic
import io
import zipfile
import lxml
import lxml.etree
import hashlib
import base64
import json
from app.models import *
import re
import os
import sqlalchemy
from app.transformator import dictTransformations3 as Transformator



def register_user(db, username, email, password_hash, sketch_engine_uid):
    print('Register user')
    
    result = db.session.query(User).filter((User.username == str(username).strip()) | (User.email == str(username).strip())).first()
    
    if result is None:
        
        if (password_hash is None) and (sketch_engine_uid is not None):
            user = User(username=username, authenticated=True, email=email.lower(), sketch_engine_uid=sketch_engine_uid)
        else:
            user = User(username=username, authenticated=True, email=email.lower(), password_hash=password_hash)
        db.session.add(user)
        db.session.commit()
        return user
    else:
        db.session.commit()
        return None

def delete_user(db, uid):
    print('Delete user')
    connection = db.connect()
    connection.execute("delete from users where id={0:s}".format(str(uid)))
    connection.close()
    return None


def check_login(db, username, password, bcrypt):
    print('Check login')
    user = db.session.query(User).filter((User.username == str(username).strip()) | (User.email == str(username.lower()).strip())).first()
    db.session.commit()
    if user is None:
        print ('invalid user')
        return None
    else:
        if bcrypt.check_password_hash(user.password_hash, password):
            if user.is_authenticated():
                return user
        return None

def login_or_register_sketch_user(db, sketch_token):
    print('login + sketch engine')
    
    user_data = User.decode_sketch_token(sketch_token)
    user = db.session.query(User).filter(User.sketch_engine_uid == str(user_data['id'])).first()
    db.session.commit()
    if user is None:
        new_user = register_user(db, user_data['email'], user_data['email'], None, user_data['id'])
        return new_user
    else:
        return user

def user_data(db, uid):
    print('user data')
    
    user = db.session.query(User).filter((User.id == str(uid).strip())).first()
    db.session.commit()
    return user

def blacklist_token(db, auth_token):
    print('blacklist token')
    
    db.session.add(BlacklistToken(token=auth_token))
    db.session.commit()
    return None

def is_blacklisted(db, auth_token):
    print('is blacklisted')
    connection = db.connect()
    result = connection.execute("SELECT * FROM blacklist_tokens WHERE token = '{0:s}'".format(auth_token))
    is_blacklisted = len([x for x in result]) != 0
    connection.close()
    return is_blacklisted

def extract_keys(cur, single=False):
    dataset = list(cur.fetchall())
    #print(dataset)
    rv = [ {key:row[key] for key in row.keys()} for row in dataset]
    if not single:
        return rv
    else:
        return rv[0] if len(rv) > 0 else None


def list_datasets(db, uid, dsid=None, order='ASC', mimetype=None):
    print('list datasets')
    connection = db.connect()

    if dsid is None:
        result = connection.execute("SELECT id, name, size, upload_uuid, file_path, xml_file_path, xml_lex, xml_ml_out, uploaded_ts, upload_mimetype, lexonomy_access, lexonomy_delete, lexonomy_edit, lexonomy_status, status "+
                                    ", lexonomy_ml_access, lexonomy_ml_delete, lexonomy_ml_edit, lexonomy_ml_status "+
                                    "FROM datasets WHERE uid='{0:s}' and upload_mimetype='{1:s}' ORDER BY uploaded_ts {2:s}".format(str(uid), mimetype, order))
    elif uid is None:
        result = connection.execute("SELECT id, file_path, xml_file_path from datasets WHERE id='{0:s}'".format(str(dsid)))
    else:
        result = connection.execute("SELECT id, name, size, upload_uuid, file_path, xml_file_path, xml_lex, xml_ml_out, uploaded_ts, upload_mimetype, lexonomy_access, lexonomy_delete, lexonomy_edit, lexonomy_status, status "+
                                    ", lexonomy_ml_access, lexonomy_ml_delete, lexonomy_ml_edit, lexonomy_ml_status " +
                                    "FROM datasets WHERE uid='{0:s}' AND id='{1:s}' ORDER BY uploaded_ts {2:s}".format(str(uid), str(dsid), order))
    datasets = extract_keys(result, dsid is not None)
    connection.close()
    return datasets


def search_dataset_entries(db, dsid, xfid, pattern):
    if len(pattern) == 0:
        entries = db.session.query(Datasets_single_entry).filter(Datasets_single_entry.xfid == str(xfid)).order_by(sqlalchemy.asc(Datasets_single_entry.entry_text)).limit(100).all()
    else:
        pattern = pattern + '%'
        entries = db.session.query(Datasets_single_entry).filter(Datasets_single_entry.dsid == str(dsid)).filter(Datasets_single_entry.xfid == str(xfid)).filter(Datasets_single_entry.entry_text.like(pattern)).order_by(sqlalchemy.asc(Datasets_single_entry.entry_text)).limit(100).all()

    db.session.commit()
    entries = [{'id': x.id, 'entry_text': x.entry_text, 'is_short_name': x.entry_name, 'entry_head': x.entry_head} for x in entries]
    return entries


def list_dataset_entries(db, uid, dsid, headwords):
    connection = db.connect()
    print('list dataset entries')
    result = connection.execute("SELECT dse.id, dse.entry_head FROM datasets_single_entry dse INNER JOIN datasets ds ON dse.dsid=ds.id WHERE dse.dsid='{0:s}' AND ds.uid='{1:s}'".format(str(dsid), str(uid)))
    d = extract_keys(result)#, ('id', 'entry_name'))
    #print(d)
    #headwords = lxm.etree.fromstring(entry_head)
    connection.close()
    return d


def get_entry(db, uid, dsid, entryid, headwords):
    connection = db.connect()
    print('get entry')
    result = connection.execute("SELECT id, entry_head, contents FROM datasets_single_entry dse INNER JOIN datasets ds ON dse.dsid=ds.id WHERE dse.dsid='{0:s}' AND ds.id='{1:s}' AND ds.uid='{2:s}'".format(str(dsid), str(entryid), str(uid)))
    d = extract_keys(result)#, ('id', 'entry_name', 'contents'))
    connection.close()
    return d


def set_dataset_status(db, uid, dsid, status):
    connection = db.connect()
    query = "UPDATE datasets SET status = '{0:s}' WHERE uid = {1:s} AND id = {2:s}".format(status, str(uid), str(dsid))
    connection.execute(query)
    connection.close()
    return dsid


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


def dataset_add_lexonomy_access(db, dsid, lexonomy_access=None, lexonomy_edit=None, lexonomy_delete=None, lexonomy_status=None):
    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    dataset.lexonomy_access = lexonomy_access
    dataset.lexonomy_edit = lexonomy_edit
    dataset.lexonomy_delete = lexonomy_delete
    dataset.lexonomy_status = lexonomy_status
    db.session.commit()
    return dsid


def dataset_add_ml_paths(db, uid, dsid, xml_lex, xml_ml_out):
    connection = db.connect()
    query = "UPDATE datasets SET xml_lex = '{0:s}', xml_ml_out = '{1:s}' WHERE uid = {2:s} AND id = {3:s}".format(str(xml_lex), str(xml_ml_out), str(uid), str(dsid))
    connection.execute(query)
    connection.close()
    return dsid


def dataset_add_ml_lexonomy_access(db, dsid, lexonomy_access=None, lexonomy_edit=None, lexonomy_delete=None, lexonomy_status=None):
    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    dataset.lexonomy_ml_access = lexonomy_access
    dataset.lexonomy_ml_edit = lexonomy_edit
    dataset.lexonomy_ml_delete = lexonomy_delete
    dataset.lexonomy_ml_status = lexonomy_status
    db.session.commit()
    return dsid


# ---- transforms
def delete_transform(db, uid, xfid):
    print('delete transform')
    connection = db.connect()
    result = connection.execute("SELECT * FROM transformers WHERE id = {0:s}".format(str(xfid)))
    if len([x for x in result]) == 0:
        connection.close()
        return None
    result = connection.execute("SELECT * FROM datasets ds INNER JOIN transformers ts on (ds.id = ts.dsid) WHERE ds.uid = {0:s} AND ts.id = {1:s}".format(str(uid), str(xfid)))
    if len([x for x in result]) == 0:
        connection.close()
        return False
    else:
        connection.execute("DELETE FROM transformers WHERE id = {0:s}".format(str(xfid)))
        connection.close()
    return True

def list_transforms(db, uid, dsid, order):
    connection = db.connect()
    if order == 'DESC':
        result = connection.execute("SELECT xf.id, xf.name, xf.created_ts, xf.entity_spec, xf.saved FROM transformers xf INNER JOIN datasets ds ON xf.dsid=ds.id WHERE ds.uid='{0:s}' AND ds.id='{1:s}' ORDER BY created_ts DESC".format(str(uid), str(dsid)))
    else:
        result = connection.execute("SELECT xf.id, xf.name, xf.created_ts, xf.entity_spec, xf.saved FROM transformers xf INNER JOIN datasets ds ON xf.dsid=ds.id WHERE ds.uid='{0:s}' AND ds.id='{1:s}'".format(str(uid), str(dsid)))
    transforms = extract_keys(result)
    connection.close()
    print('list transformers')
    return transforms

def list_saved_transforms(db, uid):
    connection = db.connect()
    result = connection.execute("SELECT xf.id, xf.name, xf.created_ts, xf.entity_spec FROM transformers xf INNER JOIN datasets ds ON xf.dsid=ds.id WHERE ds.uid='{0:s}' AND xf.saved".format(str(uid)))
    transforms = extract_keys(result)
    connection.close()
    print('list saved transformers')
    return transforms


def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i:i + n]

def describe_transform(db, uid, xfid, page):
    print('describe transform')
    connection = db.connect()
    result = connection.execute("SELECT xf.id, xf.name, xf.created_ts, xf.entity_spec, xf.saved, xf.transform FROM transformers xf INNER JOIN datasets ds ON xf.dsid=ds.id WHERE ds.uid='{0:s}' AND xf.id='{1:s}'".format(str(uid), str(xfid)))
    transform = extract_keys(result)
    for r in transform:
        try:
            r['transform'] = json.loads(r['transform'])
        except:
            pass

    result = connection.execute("SELECT id, dsid, entry_head as name, entry_name IS NOT NULL as is_short_name, entry_text as hw FROM datasets_single_entry WHERE xfid='{0:s}' order by entry_text asc".format(str(xfid)))
    entities = extract_keys(result)
    
    #page = 1
    
    pages = list(chunks(entities, 100))
    if page > len(pages):
        page = len(pages)

    try:
        entities_page = pages[page-1]
    except IndexError:
        entities_page = []

    connection.close()

    return {'transform': transform, 'entities': entities_page, 'pages': len(pages)}


def new_transform(db, uid, uuid, xfname, dsid, xpath, headword, saved):
    
    print('new transform')

    # Create
    #print(dzcontent.stream.read())
    dummy = {"entry": {"expr": ".//"+xpath, "type": "xpath"},
             "sense": {"expr": "dummy", "type": "xpath"},
             "hw": {"attr": "{http://elex.is/wp1/teiLex0Mapper/meta}innerText",
                    "type": "simple",
                    "selector": {"expr": ".//"+headword, "type": "xpath"}
                    }
             }

    transformer = Transformer(name=xfname, dsid=dsid, entity_spec=xpath, transform=dummy, saved=saved)
    db.session.add(transformer)
    db.session.commit()
    return transformer.id


def update_transform(db, uid, xfid, xfspec, name, saved):
    
    print('update transformer')

    transformer = db.session.query(Transformer).get(xfid)

    # if headword changed
    if xfspec['hw'] != transformer.transform['hw']:
        transformer.entity_spec = xfspec['entry']['expr'][3:]
        # update datasets single entry
        print("Updating Datasets_single_entry XFID: {0:d}".format(xfid))
        update_single_entries(db, xfid, xfspec)

    transformer.transform = xfspec
    transformer.saved = saved
    if name:
        transformer.name = name
    db.session.commit()
    return 1


def update_single_entries(db, xfid, transform):
    entries = db.session.query(Datasets_single_entry).filter(Datasets_single_entry.xfid == str(xfid))

    parserLookup = lxml.etree.ElementDefaultClassLookup(element=Transformator.TMyElement)
    myParser = lxml.etree.XMLParser()
    myParser.set_element_class_lookup(parserLookup)
    mapping = Transformator.TMapping(transform)
    mapper = Transformator.TMapper()

    counter = 0
    for e in entries:
        entity_xml = lxml.etree.fromstring(e.contents, parser=myParser)
        out_TEI, _aug = mapper.Transform(mapping, [], [lxml.etree.ElementTree(entity_xml)], makeAugmentedInputTrees=True, stripHeader=True, stripDictScrap=True)
        try:
            headword = out_TEI.findall('.//orth', namespaces=out_TEI.nsmap)[0].text.strip()
        except:
            headword = "Entry {}".format(counter)
        e.entry_text = headword.strip()
        counter += 1

    db.session.commit()
    return


def get_entity_and_spec(db, uid, xfid, entityid):
    connection = db.connect()
    result = connection.execute("SELECT tf.transform, dse.contents FROM transformers tf INNER JOIN datasets ds ON tf.dsid=ds.id INNER JOIN datasets_single_entry dse ON ds.id=dse.dsid WHERE tf.id='{0:s}' AND ds.uid='{1:s}' AND dse.id='{2:s}'".format(str(xfid), str(uid), str(entityid)))
    spec, entry = result.fetchone()
    try:
        spec = json.loads(spec)
    except:
        pass
    print("Tale spec: ", spec)
    connection.close()
    return entry, spec

def text_to_bits(text, encoding='utf-8', errors='surrogatepass'):
    bits = bin(int.from_bytes(text.encode(encoding, errors), 'big'))[2:]
    return bits.zfill(8 * ((len(bits) + 7) // 8))

def text_from_bits(bits, encoding='utf-8', errors='surrogatepass'):
    n = int(bits, 2)
    return n.to_bytes((n.bit_length() + 7) // 8, 'big').decode(encoding, errors) or '\0'


def transformer_download_status(db, xfid, set=False, download_status=None):
    transformer = db.session.query(Transformer).filter(Transformer.id == xfid).first()
    if set:
        transformer.file_download_status = download_status
    else:
        download_status = transformer.file_download_status
    db.session.commit()
    return download_status


def add_dataset(db, uid, dztotalfilesize, dzfilename, dzfilepath, dzuuid, headerTitle, headerPublisher, headerBibl):
    print('add dataset')

    with magic.Magic(flags=magic.MAGIC_MIME_TYPE) as m:
        mimetype = m.id_filename(dzfilepath)

    xml_path = None
    if mimetype == "application/pdf":
        xml_path = dzfilepath[:-4] + ".xml"
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


def xmls(mimetype, data):
    if mimetype == 'application/zip':
        print('processing zipfile')
        zio = zipfile.ZipFile(data)
        zil = zipfile.infolist()
        for fnm in zil:
            xdata = zio.read(fnm)
            with magic.Magic(flags=magic.MAGIC_MIME_TYPE) as m:
                mt = m.id_buffer(xdata)
                if mt == 'application/xml':
                    yield xdata
    elif mimetype == 'application/xml' or mimetype == 'text/xml':
        print ('processing single xml')
        yield data
    else:
        return None


def clean_tag(xml_tag):
    pattern = re.compile("\{http:\/\/")
    if pattern.match(xml_tag):
        m = re.search('\}.{1,10000}', xml_tag)
        if m:
            return m.group(0)[1:]
    else:
        return xml_tag


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


def prepare_dataset(db, uid, dsid, xfid, xpath, hw):
    print('prepare dataset')
    dataset = db.session.query(Datasets).filter((Datasets.uid == uid) & (Datasets.id == dsid)).first()
    mimetype, data = dataset.upload_mimetype, dataset.file_path


    for xml in xmls(mimetype, data):

        tree = lxml.etree.parse(xml)
        xpath = xpath.strip()

        namespaces = tree.getroot().nsmap
        namespace=''
        namespace_prefix = False
        for prefix, ns in namespaces.items():
            if prefix:
                namespace_prefix = True
                namespace = {prefix:ns}
                break
            else:
                namespace = ns

        if namespace_prefix:
            nodes = tree.xpath('//' + xpath, namespaces=namespace)
        else:
            nodes = tree.xpath('//' + xpath)

        print('have nodes', len(nodes))
        counter = 0

        for entry in nodes:
            headword = entry.findall('.//' + hw)
            if headword:
                text = headword[0].text
            else:
                text = ''
            entry_str = lxml.etree.tostring(entry, encoding='unicode', xml_declaration=False)
            # TODO: Return when needed. Commented out due to server breaking after commit 61634f5
            #     text = entry.tag
            #
            # entry_str = """<?xml version="1.0" encoding="utf-8"?>\n<?xml-stylesheet type='text/xsl' href='preview.xsl'?>\n<!DOCTYPE Dictionary PUBLIC "-//KDictionaries//DTD MLDS 1.0//EN" "schema.dtd">\n<Dictionary sourceLanguage="fr" targetLanguage="unspecified">\n"""
            # entry_str += lxml.etree.tostring(entry, encoding='unicode', xml_declaration=False)
            # entry_str += "\n</Dictionary>"
            entry_head = clean_tag(entry_str.split('\n',1)[0])[:10]

            # Create
            dataset = Datasets_single_entry(dsid=dsid, xfid=xfid, entry_head=entry_head, entry_text=text, contents=entry_str)
            db.session.add(dataset)
    db.session.commit()
    return (True, 'Done')


def extract_xml_head_content(db, dsid):
    print('extract xml head content')

    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    xml_file = dataset.file_path
    db.session.commit()

    tree = lxml.etree.parse(xml_file)
    unique_texts = set()
    for element in tree.iter():
        unique_texts.add(element.text.replace("\t",""))

    ## morda je bolj smiselno mapiranje iz teksta v nekaj? Npr. .tag?
    return list(unique_texts)


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


def extract_pos_elements(db, dsid, pos_element, attribute_name=None):
    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    db.session.commit()
    if dataset.pos_elements != None:
        return json.loads(dataset.pos_elements)
    else:
        xml_file = dataset.file_path
        tree = lxml.etree.parse(xml_file)
        namespaces = tree.getroot().nsmap
        namespace=''
        namespace_prefix = False
        for prefix, ns in namespaces.items():
            if prefix:
                namespace_prefix = True
                namespace = {prefix:ns}
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


def get_ds_and_xf(db, uid, xfid, dsid):
    print('get ds and xf')
    connection = db.connect()
    query = "SELECT ds.name, tf.transform, ds.file_path, ds.header_title, ds.header_publisher, ds.header_bibl FROM transformers tf INNER JOIN datasets ds ON tf.dsid = ds.id WHERE tf.dsid = '{0:s}' AND tf.id = '{1:s}'".format(str(dsid), str(xfid))
    result = connection.execute(query)

    name, transform, ds_file_path, headerTitle, headerPublisher, headerBibl = result.fetchone()
    connection.close()
    try:
        transform = json.loads(transform)
    except:
        pass

    return (transform, ds_file_path, name, headerTitle, headerPublisher, headerBibl)
    
def save_ds_metadata(db, dsid, ds_metadata):
    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    dataset.dictionary_metadata = ds_metadata
    db.session.commit()
    return 1

def get_ds_metadata(db, dsid):
    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    ds_metadata = dataset.dictionary_metadata
    db.session.commit()
    if ds_metadata is not None:
        return json.loads(ds_metadata)
    else:
        return {}


def dataset_character_map(db, dsid, set=False, character_map=None):
    dataset = db.session.query(Datasets).filter(Datasets.id == dsid).first()
    if set:
        dataset.character_map = character_map
    else:
        character_map = dataset.character_map
    db.session.commit()
    return character_map


def add_error_log(db, dsid, tag=None, message=None):
    err_log = Error_log(dsid, tag=tag, message=message)
    db.session.add(err_log)
    db.session.commit()
    return


def get_error_log(db, e_id=None):
    if e_id is None:
        logs = db.session.query(Error_log).order_by(sqlalchemy.desc(Error_log.created_ts)).limit(100).all()
    else:
        logs = db.session.query(Error_log).filter(Error_log.id == e_id).first()
    db.session.commit()
    return logs


def delete_error_log(db, e_id, dsid=None):
    if dsid is None:
        db.session.query(Error_log).filter(Error_log.id == e_id).delete()
    else:
        db.session.query(Error_log).filter(Error_log.dsid == dsid).delete()
    db.session.commit()
    return
