import json
import zipfile
import magic
import lxml
import lxml.etree
import re
import sqlalchemy

from app import app, db, celery
from app.transformation.models import Transformer
from app.dataset.models import Datasets, Datasets_single_entry
import app.modules.transformator.dictTransformations3 as DictTransformator
from app.modules.log import print_log


def extract_keys(cur, single=False):
    dataset = list(cur.fetchall())
    rv = [{key: row[key] for key in row.keys()} for row in dataset]
    if not single:
        return rv
    else:
        return rv[0] if len(rv) > 0 else None


def list_transforms(dsid, xfid=None, order='ASC'):
    if xfid is not None:
        result = Transformer.query.filter_by(id=xfid).first()
        try:
            result.transform = json.loads(result.transform)
        except:
            pass
    elif order == 'ASC':
        result = Transformer.query.filter_by(dsid=dsid).order_by(sqlalchemy.asc(Transformer.created_ts)).all()
    else:
        result = Transformer.query.filter_by(dsid=dsid).order_by(sqlalchemy.desc(Transformer.created_ts)).all()
    db.session.close()
    return result


# TODO: is this used?
def list_saved_transforms(uid):
    datasets = Datasets.query.filter_by(uid=uid).all()
    out = []
    for ds in datasets:
        transforms = Transformer.query.filter_by(dsid=ds.id, saved=True).all()
        transforms = [Transformer.to_dict(i) for i in transforms]
        out.extend(transforms)
    return out


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


def prepare_dataset(uid, dsid, xfid, xpath, hw):
    dataset = Datasets.query.filter_by(uid=uid, id=dsid).first()
    print_log(app.name, 'Preparing dataset {}'.format(dataset))
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
            db.session.add(dataset)
    db.session.commit()
    return (True, 'Done')


def new_transform(xfname, dsid, xpath, headword, saved):
    dummy = {"entry": {"expr": ".//" + xpath, "type": "xpath"},
             "sense": {"expr": "dummy", "type": "xpath"},
             "hw": {"attr": "{http://elex.is/wp1/teiLex0Mapper/meta}innerText",
                    "type": "simple",
                    "selector": {"expr": ".//" + headword, "type": "xpath"}
                    }
             }

    transformer = Transformer(name=xfname, dsid=dsid, entity_spec=xpath, transform=dummy, saved=saved)
    print('New transform {}'.format(transformer))
    db.session.add(transformer)
    db.session.commit()
    return transformer.id


def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i:i + n]


def describe_transform(xfid, page):
    result_transform = Transformer.query.filter_by(id=xfid).first()
    try:
        result_transform.transform = json.loads(result_transform.transform)
    except:
        pass
    result_dse = Datasets_single_entry.query.filter_by(xfid=str(xfid)).order_by(sqlalchemy.asc(Datasets_single_entry.entry_text)).all()
    for i in range(len(result_dse)):
        result_dse[i] = Datasets_single_entry.to_dict(result_dse[i])
        result_dse[i]['name'] = result_dse[i]['entry_head']
        result_dse[i]['hw'] = result_dse[i]['entry_text']
        result_dse[i]['is_short_name'] = result_dse[i]['entry_name'] is not None
        for j in ['entry_head', 'entry_text', 'entry_name', 'contents', 'xfid']:
            result_dse[i].pop(j)

    pages = list(chunks(result_dse, 100))
    if page > len(pages):
        page = len(pages)
    try:
        entities_page = pages[page - 1]
    except IndexError:
        entities_page = []
    db.session.close()
    return {'transform': [Transformer.to_dict(result_transform)], 'entities': entities_page, 'pages': len(pages)}


def delete_transform(uid, xfid):
    transform = Transformer.query.filter_by(id=xfid).first()
    print('Delete {0}, uid: {1}'.format(transform, uid))
    db.session.query(Transformer).filter(Transformer.id == xfid).delete()
    db.session.commit()
    return True


def update_transform(xfid, xfspec, name, saved):
    transformer = Transformer.query.filter_by(id=xfid).first()

    for key in xfspec:  # removing .// prepend if .. selector
        # only
        if 'selector' in xfspec[key] and 'expr' in xfspec[key]['selector'] and '..' == xfspec[key]['selector']['expr'][-2:]:
            xfspec[key]['selector']['expr'] = '..'
        # union
        elif 'selector' in xfspec[key] and 'selectors' in xfspec[key]['selector']:
            for i in range(len(xfspec[key]['selector']['selectors'])):
                if '..' == xfspec[key]['selector']['selectors'][i]['expr'][-2:]:
                    xfspec[key]['selector']['selectors'][i]['expr'] = '..'

    # if headword changed
    if xfspec['hw'] != transformer.transform['hw']:
        transformer.entity_spec = xfspec['entry']['expr'][3:]
        # update datasets single entry
        print("Updating Datasets_single_entry XFID: {0:d}".format(xfid))
        update_single_entries(xfid, xfspec)

    transformer.transform = xfspec
    transformer.saved = saved
    if name:
        transformer.name = name
    db.session.commit()
    return 1


def update_single_entries(xfid, transform):
    entries = Datasets_single_entry.query.filter_by(xfid=str(xfid)).all()

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


def search_dataset_entries(db, dsid, xfid, pattern):
    xfid = str(xfid)
    if len(pattern) == 0:
        entries = Datasets_single_entry.query.filter_by(xfid=xfid).order_by(sqlalchemy.asc(Datasets_single_entry.entry_text)).limit(100).all()
    else:
        pattern = pattern + '%'
        entries = Datasets_single_entry.query.filter_by(xfid=xfid).filter(Datasets_single_entry.entry_text.like(pattern)).order_by(sqlalchemy.asc(Datasets_single_entry.entry_text)).limit(100).all()
    db.session.close()
    entries = [{'id': x.id, 'entry_text': x.entry_text, 'is_short_name': x.entry_name, 'entry_head': x.entry_head} for x in entries]
    return entries


def get_ds_and_xf(xfid, dsid):
    dataset = Datasets.query.filter_by(id=dsid).first()
    xf = Transformer.query.filter_by(id=xfid).first()
    db.session.close()
    try:
        transform = json.loads(xf.transform)
    except:
        transform = None
    return (transform, dataset.file_path, dataset.name, None, None, None)


def transformer_download_status(xfid, set=False, download_status=None):
    transformer = Transformer.query.filter_by(id=xfid).first()
    if set:
        transformer.file_download_status = download_status
    else:
        download_status = transformer.file_download_status
    db.session.commit()
    return download_status