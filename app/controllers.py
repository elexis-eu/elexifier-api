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
        result = connection.execute("SELECT id, name, size, upload_uuid, file_path, xml_file_path, uploaded_ts, upload_mimetype, status FROM datasets WHERE uid='{0:s}' and upload_mimetype='{1:s}' ORDER BY uploaded_ts {2:s}".format(str(uid), mimetype, order))
    else:
        result = connection.execute("SELECT id, name, size, upload_uuid, file_path, xml_file_path, uploaded_ts, upload_mimetype, status FROM datasets WHERE uid='{0:s}' AND id='{1:s}' ORDER BY uploaded_ts {2:s}".format(str(uid), str(dsid), order))
    datasets = extract_keys(result, dsid is not None)
    connection.close()
    return datasets


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


def describe_transform(db, uid, xfid):
    print('describe transform')
    connection = db.connect()
    result = connection.execute("SELECT xf.id, xf.name, xf.created_ts, xf.entity_spec, xf.saved, xf.transform FROM transformers xf INNER JOIN datasets ds ON xf.dsid=ds.id WHERE ds.uid='{0:s}' AND xf.id='{1:s}'".format(str(uid), str(xfid)))
    transform = extract_keys(result)
    for r in transform:
        try:
            r['transform'] = json.loads(r['transform'])
        except:
            pass

    result = connection.execute("SELECT id, dsid, entry_head as name, entry_name IS NOT NULL as is_short_name, entry_text as hw FROM datasets_single_entry WHERE xfid='{0:s}'".format(str(xfid)))
    entities = extract_keys(result)
    connection.close()

    return {'transform': transform, 'entities': entities}


def new_transform(db, uid, uuid, xfname, dsid, xpath, saved):
    
    print('new transform')

    # Create
    #print(dzcontent.stream.read())
    transformer = Transformer(name=xfname, dsid=dsid, entity_spec=xpath, saved=saved)
    db.session.add(transformer)
    db.session.commit()
    return transformer.id


def update_transform(db, uid, xfid, xfspec, name, saved):
    
    print('update transformer')

    transformer = db.session.query(Transformer).get(xfid)
    transformer.transform = xfspec
    transformer.saved = saved
    if name:
        transformer.name = name
    db.session.commit()
    return 1


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


def add_dataset(db, uid, dztotalfilesize, dzfilename, dzfilepath, dzuuid):
    print('add dataset')

    with magic.Magic(flags=magic.MAGIC_MIME_TYPE) as m:
        mimetype = m.id_filename(dzfilepath)

    xml_path = None
    if mimetype == "application/pdf":
        xml_path = dzfilepath[:-4] + ".xml"
    # Create
    dataset = Datasets(uid=uid, name=dzfilename, size=dztotalfilesize, file_path=dzfilepath, upload_mimetype=mimetype, upload_uuid=dzuuid, xml_file_path=xml_path)
    db.session.add(dataset)
    db.session.commit()
    return dataset.id


def delete_dataset(db, uid, dsid):
    print('delete dataset')
    connection = db.connect()
    result = connection.execute("SELECT * FROM datasets WHERE id = {0:s}".format(str(dsid)))
    if len([x for x in result]) == 0:
        connection.close()
        return None
    result = connection.execute("SELECT * FROM datasets WHERE uid = {0:s} AND id = {1:s}".format(str(uid), str(dsid)))
    if len([x for x in result]) == 0:
        connection.close()
        return False
    else:
        result = connection.execute("SELECT ts.id FROM datasets ds INNER JOIN transformers ts on (ds.id = ts.dsid) WHERE ds.id = {0:s} AND ds.uid = {1:s}".format(str(dsid), str(uid)))
        for i in result:
            connection.execute("DELETE FROM transformers WHERE id = {0:s}".format(str(i[0])))
        result = connection.execute("SELECT file_path FROM datasets WHERE id = {0:s} AND uid = {1:s}".format(str(dsid), str(uid)))
        file_path = str([x for x in result][0][0])
        os.remove(file_path)
        if ".pdf" in file_path:
            os.remove(file_path[:-4] + ".xml")
        print("File removed")
        connection.execute("DELETE FROM datasets WHERE id = {0:s} AND uid = {1:s}".format(str(dsid), str(uid)))
        connection.close()
        return True

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
    xml_file = dataset.file_path
    db.session.commit()

    tree = lxml.etree.parse(xml_file)
    unique_tags = set()
    for element in tree.iter():
        unique_tags.add(clean_tag(element.tag))
    return list(unique_tags)
    
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
    query = "SELECT ds.name, tf.transform, ds.file_path FROM transformers tf INNER JOIN datasets ds ON tf.dsid = ds.id WHERE tf.dsid = '{0:s}' AND tf.id = '{1:s}'".format(str(dsid), str(xfid))
    result = connection.execute(query)

    name, transform, ds_file_path = result.fetchone()
    connection.close()
    try:
        transform = json.loads(transform)
    except:
        pass

    return (transform, ds_file_path, name)