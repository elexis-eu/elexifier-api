import lxml
import lxml.etree
import re
from transformator import dictTransformations3 as transformator

def clean_tag(xml_tag):
    pattern = re.compile("\{http:\/\/")
    if pattern.match(xml_tag):
        m = re.search('\}.{1,10000}', xml_tag)
        if m:
            return m.group(0)[1:]
    else:
        return xml_tag


def prepare_dataset(xml, xpath, hw):
    
    tree = lxml.etree.parse(xml)
    #print(tree)
    #root = tree.getroot()
    #for el in root:
    #    print(el.text)
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

    entries = []
    for entry in nodes:
        headword = entry.findall('.//' + hw)
        if headword:
            text = headword[0].text
            #print(text)
        else:
            text = ''
        entry_str = lxml.etree.tostring(entry, encoding='unicode', xml_declaration=False)
        entry_head = clean_tag(entry_str.split('\n',1)[0])[:10]
        entries.append((text, entry_str))

        # Create
        #dataset = Datasets_single_entry(dsid=dsid, xfid=xfid, entry_head=entry_head, entry_text=text, contents=entry_str)
    
    return (entries)
    
def prepare_dataset2(xml, xf):
    
    orig_xml = open(xml, 'rb').read()
    parserLookup = lxml.etree.ElementDefaultClassLookup(element = transformator.TMyElement)
    myParser = lxml.etree.XMLParser()
    myParser.set_element_class_lookup(parserLookup)
    entity_xml = lxml.etree.fromstring(orig_xml, parser = myParser)
    mapping = transformator.TMapping(xf)
    mapper = transformator.TMapper()
    out_TEI, out_aug = mapper.Transform(mapping, [], [lxml.etree.ElementTree(entity_xml)], makeAugmentedInputTrees=True, stripForValidation=True)
    

    target_xml = lxml.etree.tostring(out_TEI, pretty_print=True, encoding='unicode')
    
    return out_aug
    
    
entries = prepare_dataset('Oxford_test01.xml', 'se', 'hw')

xf = {
  "entry": {
    "expr": ".//se",
    "type": "xpath"
  },
  "hw": {
    "attr": "{http://elex.is/wp1/teiLex0Mapper/meta}innerText",
    "selector": {
      "expr": ".//hw",
      "type": "xpath"
    },
    "type": "simple"
  },
  "sense": {
    "expr": "dummy",
    "type": "xpath"
  }
}


entries2 = prepare_dataset2('Oxford_test01.xml', xf)

#print(entries[0])

#print('\n')

xmlstr = lxml.etree.tostring(entries2[0], encoding='utf8', method='xml')
#print(xmlstr)



