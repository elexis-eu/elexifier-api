import lxml
from lxml import etree
import re


def clean_tokens(node, char_map):
    if len(node) > 0 and node[-1].text:
        if node[-1].text[-1] in [',', ':', ';']:
            dictScrap = lxml.etree.fromstring('<dictScrap></dictScrap>')
            dictScrap.text = node[-1].text[-1]
            node[-1].text = node[-1].text[:-1]
            node.addnext(dictScrap)

    for child in node:
        if child.tag == 'TOKEN':
            for key in char_map:
                child.text = re.sub(key, char_map[key], child.text)

            for v in child.attrib:
                child.attrib.pop(v)
        clean_tokens(child, char_map)


def xml_walk3(node):
    for child in node:
        # Skip nodes without name attribute
        if 'name' not in child.attrib:
            xml_walk3(child)
            continue

        name = child.attrib['name']
        if name in ['entry', 'sense', 'form', 'headword', 'pos', 'translation', 'noise']:
            child.attrib.pop('name')

        if name == 'entry':
            child.tag = 'entry'

        elif name == 'sense':
            child.tag = 'sense'

        elif name == 'form' or name == 'headword':
            orth = lxml.etree.fromstring('<orth></orth>')
            for inner_child in child:
                if orth.text is None:
                    orth.text = inner_child.text
                else:
                    orth.text += ' ' + str(inner_child.text)
                child.remove(inner_child)
            child.tag = 'form'
            child.attrib['type'] = 'lemma'
            child.append(orth)

        elif name == 'pos':
            gram = lxml.etree.fromstring('<gram type="pos"></gram>')
            for inner_child in child:
                if gram.text is None:
                    gram.text = inner_child.text
                else:
                    gram.text += ' ' + inner_child.text
                child.remove(inner_child)
            child.tag = 'gramGrp'
            child.append(gram)

        elif name == 'translation':
            quote = lxml.etree.fromstring('<quote></quote>')
            for inner_child in child:
                if quote.text is None:
                    quote.text = inner_child.text
                else:
                    quote.text += ' ' + inner_child.text
                child.remove(inner_child)
            child.append(quote)
            child.tag = 'cit'
            child.attrib['type'] = 'translationEquivalent'

        elif name == 'example':
            quote = lxml.etree.fromstring('<quote></quote>')
            for inner_child in child:
                if quote.text is None:
                    quote.text = inner_child.text
                else:
                    quote.text += ' ' + inner_child.text
                child.remove(inner_child)
            child.append(quote)
            child.tag = 'cit'
            child.attrib['type'] = 'example'

        elif name == 'dictScrap' or name == 'noise':
            child.tag = 'dictScrap'

        xml_walk3(child)


def tokenized2TEI(in_file, out_file, char_map):
    tree = etree.parse(in_file)
    root = tree.getroot()

    if char_map is None:
        char_map = {}

    clean_tokens(root, char_map)
    xml_walk3(root)

    out_xml = lxml.etree.tostring(root, pretty_print=True, encoding='unicode')
    formatting_char_map = {
        '\n': ' ',
        '> +': '>',
        ' +<': '<',
        '<TOKEN>': '',
        '</TOKEN>': ' ',
        ' <': '<',
        '><': '>\n<',
        '- ': ''
    }
    for key in formatting_char_map:
        out_xml = re.sub(key, formatting_char_map[key], out_xml)

    out_xml = lxml.etree.tostring(lxml.etree.fromstring(out_xml), pretty_print=True, encoding='unicode')

    file = open(out_file, 'w')
    file.write(out_xml)
    file.close()
    return
