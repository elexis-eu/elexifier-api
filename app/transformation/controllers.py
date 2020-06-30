import json
import zipfile
import magic
import lxml
import lxml.etree
import re
import sqlalchemy

from app.transformation.models import Transformer
from app.dataset.models import Datasets, Datasets_single_entry
import app.modules.transformator.dictTransformations3 as DictTransformator


def extract_keys(cur, single=False):
    dataset = list(cur.fetchall())
    #print(dataset)
    rv = [ {key:row[key] for key in row.keys()} for row in dataset]
    if not single:
        return rv
    else:
        return rv[0] if len(rv) > 0 else None


# TODO: is this used?
def list_saved_transforms(db, uid):
    connection = db.connect()
    result = connection.execute("SELECT xf.id, xf.name, xf.created_ts, xf.entity_spec FROM transformers xf INNER JOIN datasets ds ON xf.dsid=ds.id WHERE ds.uid='{0:s}' AND xf.saved".format(str(uid)))
    transforms = extract_keys(result)
    connection.close()
    print('list saved transformers')
    return transforms


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


def new_transform(db, uid, uuid, xfname, dsid, xpath, headword, saved):
    print('new transform')

    # Create
    # print(dzcontent.stream.read())
    dummy = {"entry": {"expr": ".//" + xpath, "type": "xpath"},
             "sense": {"expr": "dummy", "type": "xpath"},
             "hw": {"attr": "{http://elex.is/wp1/teiLex0Mapper/meta}innerText",
                    "type": "simple",
                    "selector": {"expr": ".//" + headword, "type": "xpath"}
                    }
             }

    transformer = Transformer(name=xfname, dsid=dsid, entity_spec=xpath, transform=dummy, saved=saved)
    db.session.add(transformer)
    db.session.commit()
    return transformer.id


def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i:i + n]


def describe_transform(db, uid, xfid, page):
    print('describe transform')
    connection = db.connect()
    result = connection.execute(
        "SELECT xf.id, xf.name, xf.created_ts, xf.entity_spec, xf.saved, xf.transform FROM transformers xf INNER JOIN datasets ds ON xf.dsid=ds.id WHERE ds.uid='{0:s}' AND xf.id='{1:s}'".format(
            str(uid), str(xfid)))
    transform = extract_keys(result)
    for r in transform:
        try:
            r['transform'] = json.loads(r['transform'])
        except:
            pass

    result = connection.execute(
        "SELECT id, dsid, entry_head as name, entry_name IS NOT NULL as is_short_name, entry_text as hw FROM datasets_single_entry WHERE xfid='{0:s}' order by entry_text asc".format(
            str(xfid)))
    entities = extract_keys(result)

    # page = 1

    pages = list(chunks(entities, 100))
    if page > len(pages):
        page = len(pages)

    try:
        entities_page = pages[page - 1]
    except IndexError:
        entities_page = []

    connection.close()

    return {'transform': transform, 'entities': entities_page, 'pages': len(pages)}


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

    parserLookup = lxml.etree.ElementDefaultClassLookup(element=DictTransformator.TMyElement)
    myParser = lxml.etree.XMLParser()
    myParser.set_element_class_lookup(parserLookup)
    mapping = DictTransformator.TMapping(transform)
    mapper = DictTransformator.TMapper()

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


def search_dataset_entries(db, dsid, xfid, pattern):
    if len(pattern) == 0:
        entries = db.session.query(Datasets_single_entry).filter(Datasets_single_entry.xfid == str(xfid)).order_by(sqlalchemy.asc(Datasets_single_entry.entry_text)).limit(100).all()
    else:
        pattern = pattern + '%'
        entries = db.session.query(Datasets_single_entry).filter(Datasets_single_entry.dsid == str(dsid)).filter(Datasets_single_entry.xfid == str(xfid)).filter(Datasets_single_entry.entry_text.like(pattern)).order_by(sqlalchemy.asc(Datasets_single_entry.entry_text)).limit(100).all()

    db.session.commit()
    entries = [{'id': x.id, 'entry_text': x.entry_text, 'is_short_name': x.entry_name, 'entry_head': x.entry_head} for x in entries]
    return entries


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


def transformer_download_status(db, xfid, set=False, download_status=None):
    transformer = db.session.query(Transformer).filter(Transformer.id == xfid).first()
    if set:
        transformer.file_download_status = download_status
    else:
        download_status = transformer.file_download_status
    db.session.commit()
    return download_status