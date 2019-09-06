import magic
import io
import zipfile
import lxml
import lxml.etree
import hashlib
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import base64
import json
from app.models import *
import re
import os



def register_user(db, username, email, password_hash):
    Session = sessionmaker(db)
    session = Session()
    result = session.execute("SELECT * FROM users WHERE username='{0:s}'".format(username))
    if len([x for x in result]) == 0:
        uid = [x for x in session.execute("SELECT MAX(id) FROM users")][0][0]
        if uid:
             uid += 1
        else:
            uid = 0
        session.execute("INSERT INTO users (id, username, password_hash, authenticated, email) VALUES ({0:s}, '{1:s}', '{2:s}', 1, '{3:s}')".format(str(uid), username, password_hash, email.lower()))
        user = session.query(User).filter((User.username == str(username).strip()) | (User.email == str(username).strip())).first()
        session.commit()
        return user
    else:
        return None

def delete_user(db, uid):
    connection = db.connect()
    connection.execute("delete from users where id={0:s}".format(str(uid)))
    return None


def check_login(db, username, password, bcrypt):
    Session = sessionmaker(db)
    session = Session()
    user = session.query(User).filter((User.username == str(username).strip()) | (User.email == str(username.lower()).strip())).first()
    session.commit()
    if user is None:
        print ('invalid user')
        return None
    else:
        if bcrypt.check_password_hash(user.password_hash, password):
            if user.is_authenticated():
                return user
        return None

def user_data(db, uid):
    Session = sessionmaker(db)
    session = Session()
    user = session.query(User).filter((User.id == str(uid).strip())).first()
    session.commit()
    return user

def blacklist_token(db, auth_token):
    Session = sessionmaker(db)
    session = Session()
    session.add(BlacklistToken(token=auth_token))
    session.commit()
    return None

def is_blacklisted(db, auth_token):
    Session = sessionmaker(db)
    session = Session()
    result = session.execute("SELECT * FROM blacklist_tokens WHERE token = '{0:s}'".format(auth_token))
    return len([x for x in result]) != 0

def extract_keys(cur, single=False):
    dataset = list(cur.fetchall())
    #print(dataset)
    rv = [ {key:row[key] for key in row.keys()} for row in dataset]
    if not single:
        return rv
    else:
        return rv[0] if len(rv) > 0 else None


def list_datasets(db, uid, dsid=None, order=None):
    connection = db.connect()
    if dsid is None:
        if order is None or order == 'ASC':
            result = connection.execute("SELECT id, name, size, upload_uuid, file_path, uploaded_ts, upload_mimetype FROM datasets WHERE uid='{0:s}'".format(str(uid)))
        else:
            result = connection.execute("SELECT id, name, size, upload_uuid, file_path, uploaded_ts, upload_mimetype FROM datasets WHERE uid='{0:s}' ORDER BY uploaded_ts DESC".format(str(uid)))
    else:
        if order is None or order == 'ASC':
            result = connection.execute("SELECT id, name, size, upload_uuid, file_path, uploaded_ts, upload_mimetype FROM datasets WHERE uid='{0:s}' AND id='{1:s}'".format(str(uid), str(dsid)))
        else:
            result = connection.execute("SELECT id, name, size, upload_uuid, file_path, uploaded_ts, upload_mimetype FROM datasets WHERE uid='{0:s}' AND id='{1:s}' ORDER BY uploaded_ts DESC".format(str(uid), str(dsid)))
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
    Session = sessionmaker(db)
    session = Session()
    result = session.execute("SELECT * FROM transformers WHERE id = {0:s}".format(str(xfid)))
    if len([x for x in result]) == 0:
        return None
    result = session.execute("SELECT * FROM datasets ds INNER JOIN transformers ts on (ds.id = ts.dsid) WHERE ds.uid = {0:s} AND ts.id = {1:s}".format(str(uid), str(xfid)))
    if len([x for x in result]) == 0:
        return False
    else:
        session.execute("DELETE FROM transformers WHERE id = {0:s}".format(str(xfid)))
        session.commit()
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
    base = declarative_base()
    Session = sessionmaker(db)
    session = Session()
    base.metadata.create_all(db)
    print('new transform')

    # Create
    #print(dzcontent.stream.read())
    transformer = Transformer(name=xfname, dsid=dsid, entity_spec=xpath, saved=saved)
    session.add(transformer)
    session.commit()
    return transformer.id


def update_transform(db, uid, xfid, xfspec, name, saved):
    base = declarative_base()
    Session = sessionmaker(db)
    session = Session()
    base.metadata.create_all(db)
    print('update transformer')

    transformer = session.query(Transformer).get(xfid)
    transformer.transform = xfspec
    transformer.saved = saved
    if name:
        transformer.name = name
    session.commit()
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

    with magic.Magic(flags=magic.MAGIC_MIME_TYPE) as m:
        mimetype = m.id_filename(dzfilepath)

    base = declarative_base()
    Session = sessionmaker(db)
    session = Session()
    base.metadata.create_all(db)

    # Create
    dataset = Datasets(uid=uid, name=dzfilename, size=dztotalfilesize, file_path=dzfilepath, upload_mimetype=mimetype, upload_uuid=dzuuid)
    session.add(dataset)
    session.commit()
    return dataset.id


def delete_dataset(db, uid, dsid):
    connection = db.connect()
    Session = sessionmaker(db)
    session = Session()
    result = session.execute("SELECT * FROM datasets WHERE id = {0:s}".format(str(dsid)))
    if len([x for x in result]) == 0:
        return None
    result = session.execute("SELECT * FROM datasets WHERE uid = {0:s} AND id = {1:s}".format(str(uid), str(dsid)))
    if len([x for x in result]) == 0:
        return False
    else:
        result = session.execute("SELECT ts.id FROM datasets ds INNER JOIN transformers ts on (ds.id = ts.dsid) WHERE ds.id = {0:s} AND ds.uid = {1:s}".format(str(dsid), str(uid)))
        for i in result:
            session.execute("DELETE FROM transformers WHERE id = {0:s}".format(str(i[0])))
        result = session.execute("SELECT file_path FROM datasets WHERE id = {0:s} AND uid = {1:s}".format(str(dsid), str(uid)))
        os.remove(str([x for x in result][0][0]))
        print("File removed")
        session.execute("DELETE FROM datasets WHERE id = {0:s} AND uid = {1:s}".format(str(dsid), str(uid)))
        session.commit()
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
    connection = db.connect()
    result = connection.execute("SELECT upload_mimetype, file_path FROM datasets WHERE uid='{0:s}' AND id='{1:s}'".format(str(uid), str(dsid)))
    mimetype, data = result.fetchone()

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

        base = declarative_base()
        Session = sessionmaker(db)
        session = Session()
        base.metadata.create_all(db)

        for entry in nodes:
            headword = entry.findall('.//' + hw)
            if headword:
                text = headword[0].text
            else:
                text = ''
            entry_str = lxml.etree.tostring(entry, encoding='unicode', xml_declaration=False)
            entry_head = clean_tag(entry_str.split('\n',1)[0])[:10]

            # Create
            dataset = Datasets_single_entry(dsid=dsid, xfid=xfid, entry_head=entry_head, entry_text=text, contents=entry_str)
            session.add(dataset)
        session.commit()


    connection.close()
    return (True, 'Done')


def extract_xml_head_content(db, dsid):
    Session = sessionmaker(db)
    session = Session()
    dataset = session.query(Datasets).filter(Datasets.id == dsid).first()
    xml_file = dataset.file_path
    session.commit()

    tree = lxml.etree.parse(xml_file)
    unique_texts = set()
    for element in tree.iter():
        unique_texts.add(element.text.replace("\t",""))

    ## morda je bolj smiselno mapiranje iz teksta v nekaj? Npr. .tag?
    return list(unique_texts)


def extract_xml_heads(db, dsid):

    Session = sessionmaker(db)
    session = Session()
    dataset = session.query(Datasets).filter(Datasets.id == dsid).first()
    xml_file = dataset.file_path
    session.commit()

    tree = lxml.etree.parse(xml_file)
    unique_tags = set()
    for element in tree.iter():
        unique_tags.add(clean_tag(element.tag))
    return list(unique_tags)

def get_ds_and_xf(db, uid, xfid, dsid):
    Session = sessionmaker(db)
    session = Session()
    transformer, dataset = session.query(Transformer, Datasets).filter(Transformer.dsid == Datasets.id).filter(Transformer.id == xfid).first()
    session.commit()
    xf = transformer.transform
    ds_path = dataset.file_path
    name = dataset.name

    return(xf, ds_path, name)