import magic
import io
import zipfile
import lxml
import lxml.etree
import hashlib
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import base64
<<<<<<< HEAD:app/dbfunc.py
import json
from app.models import *

=======
import re
>>>>>>> master:dbfunc.py



def user_loader(db, uid):
    return User.query.get(int(uid))
    #uid = int(uid)
    #cur = db.cursor()
    #cur.execute("SELECT id FROM users WHERE ")


def check_login(db, username, password, bcrypt):
    Session = sessionmaker(db)
    session = Session()
    user = session.query(User).filter((User.username == str(username).strip()) | (User.email == str(username).strip())).first()
    session.commit()
    if user is None:
        print ('invalid user')
        return None
    else:
        if bcrypt.check_password_hash(user.password_hash, password):
            if user.is_authenticated():
                return user
        return None


def extract_keys(cur, single=False):
    dataset = list(cur.fetchall())
    #print(dataset)
    rv = [ {key:row[key] for key in row.keys()} for row in dataset]
    if not single:
        return rv
    else:
        return rv[0] if len(rv) > 0 else None

def list_datasets(db, uid, dsid=None):
    connection = db.connect()
    if dsid is None:
        result = connection.execute("SELECT id, name, size, upload_uuid, file_path, uploaded_ts, upload_mimetype FROM datasets WHERE uid='{0:s}'".format(str(uid)))
    else:
        result = connection.execute("SELECT id, name, size, upload_uuid, file_path, uploaded_ts, upload_mimetype FROM datasets WHERE uid='{0:s}' AND id='{1:s}'".format(str(uid), str(dsid)))
    datasets = extract_keys(result, dsid is not None)
    connection.close()
    return datasets

def list_dataset_entries(db, uid, dsid):
    connection = db.connect()
    result = connection.execute("SELECT dse.id, dse.entry_name FROM datasets_single_entry dse INNER JOIN datasets ds ON dse.dsid=ds.id WHERE dse.dsid='{0:s}' AND ds.uid='{1:s}'".format(str(dsid), str(uid)))
    d = extract_keys(result)#, ('id', 'entry_name'))
    connection.close()
    return d

def get_entry(db, uid, dsid, entryid):
    connection = db.connect()
    result = connection.execute("SELECT id, entry_name, contents FROM datasets_single_entry dse INNER JOIN datasets ds ON dse.dsid=ds.id WHERE dse.dsid='{0:s}' AND ds.id='{1:s}' AND ds.uid='{2:s}'".format(str(dsid), str(entryid), str(uid)))
    d = extract_keys(result)#, ('id', 'entry_name', 'contents'))
    connection.close()
    return d

# ---- transforms

def list_transforms(db, uid, dsid):
    connection = db.connect()
    result = connection.execute("SELECT xf.id, xf.name, xf.created_ts, xf.entity_spec FROM transformers xf INNER JOIN datasets ds ON xf.dsid=ds.id WHERE ds.uid='{0:s}' AND ds.id='{1:s}'".format(str(uid), str(dsid)))
    transforms = extract_keys(result)
    connection.close()
    print('list transformers')
    return transforms

def describe_transform(db, uid, xfid):
    connection = db.connect()
    result = connection.execute("SELECT xf.id, xf.name, xf.created_ts, xf.entity_spec, xf.transform FROM transformers xf INNER JOIN datasets ds ON xf.dsid=ds.id WHERE ds.uid='{0:s}' AND xf.id='{1:s}'".format(str(uid), str(xfid)))
    transform = extract_keys(result)
    print('describe transform')
    for r in transform:
        try:
            r['transform'] = json.loads(r['transform'])
        except:
            pass

    print("Transform: ", transform)
    result = connection.execute("SELECT id, dsid, COALESCE(entry_name, entry_head) as name, entry_name IS NOT NULL as is_short_name FROM datasets_single_entry WHERE xfid='{0:s}'".format(str(xfid)))
    entities = extract_keys(result)
    return {'transform': transform, 'entities': entities}

def new_transform(db, uid, uuid, xfname, dsid, xpath):
    base = declarative_base()
    Session = sessionmaker(db)
    session = Session()
    base.metadata.create_all(db)
    print('new transform')

    # Create
    #print(dzcontent.stream.read())
    transformer = Transformer(name=xfname, dsid=dsid, entity_spec=xpath)
    session.add(transformer)
    session.commit()
    return transformer.id


def update_transform(db, uid, xfid, xfspec):
    base = declarative_base()
    Session = sessionmaker(db)
    session = Session()
    base.metadata.create_all(db)
    print('update transformer')

    transformer = session.query(Transformer).get(xfid)
    print(xfspec['slots'])
    transformer.transform = xfspec
    session.commit()
    return 1

def get_entity_and_spec(db, uid, xfid, entityid):
    connection = db.connect()
    result = connection.execute("SELECT tf.transform, dse.contents FROM transformers tf INNER JOIN datasets ds ON tf.dsid=ds.id INNER JOIN datasets_single_entry dse ON ds.id=dse.dsid WHERE tf.id='{0:s}' AND ds.uid='{1:s}' AND dse.id='{2:s}'".format(str(xfid), str(uid), str(entityid)))
    spec, entry = result.fetchone()
    print(spec)
    spec = json.loads(spec)
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


def prepare_dataset(db, uid, dsid, xfid, xpath):
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
            nodes = tree.xpath('.//' + xpath, namespaces=namespace)
        else:
            nodes = tree.findall('.//{' + namespace + '}' + xpath)

        print('have nodes', len(nodes))
        counter = 0

        base = declarative_base()
        Session = sessionmaker(db)
        session = Session()
        base.metadata.create_all(db)

        for entry in nodes:
            entry_str = lxml.etree.tostring(entry, encoding='unicode', xml_declaration=False)
            entry_head = entry_str.split('\n',1)[0] #!!
            #print(entry_head)



            # Create
            dataset = Datasets_single_entry(dsid=dsid, xfid=xfid, entry_head=entry_head, contents=entry_str)
            session.add(dataset)
        session.commit()


    connection.close()
    return (True, 'Done')

def extract_xml_head_content(xml_file):

    tree = lxml.etree.parse(xml_file)
    unique_texts = set()
    for element in tree.iter():
        unique_texts.add(element.text.replace("\t",""))
        
    ## morda je bolj smiselno mapiranje iz teksta v nekaj? Npr. .tag?
    return unique_texts

def clean_tag(xml_tag):
    pattern = re.compile("\{http:\/\/")
    if pattern.match(xml_tag):
        m = re.search('\}.{1,10000}', xml_tag)
        if m:
            return m.group(0)[1:]
    else:
        return xml_tag

def extract_xml_heads(xml_file):

    tree = lxml.etree.parse(xml_file)
    unique_tags = set()
    for element in tree.iter():
        unique_tags.add(clean_tag(element.tag))        
    print(unique_tags)
                        
if __name__ == "__main__":

    import glob
    for fil in glob.glob("./example_xml/*"):
#        if fil != "./example_xml/Bridge_A_TEI-valid (1).xml":            
        try:
            results = extract_xml_heads(fil)
            results2 = extract_xml_head_content(fil)
        except Exception as es:
            print(es)
            pass
