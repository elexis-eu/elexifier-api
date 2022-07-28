import sys
from lxml import etree

HELP = """
USAGE:
python3 remap_pos.py [command] <FILE_NAME> <ACRONYM>

COMMANDS:
export: Exports all pos element values from <gramGrp><gram type="pos"> into .csv file as original_pos.
        Ouput file FILE_NAME-export.csv is saved into the same directory as input file.

remap:  First run export command and add new tei_pos values to FILE_NAME-export.csv file. Remember to save it as .csv
        format and keep it in the same directory as input file. This script will remap all pos values from
        FILE_NAME-export.csv file and save them into FILE_NAME-remapped.xml file in the same directory.
        Add <ACRONYM> to be used in the ids of entries and senses.

DEPENDENCIES:
Make sure you have lxml installed. You can install it with the following command:
pip3 install lxml
"""


def prepare_ns(xml_tree):
    nsmap = xml_tree.getroot().nsmap
    try:
        nsmap["_"] = nsmap[None]
        nsmap.pop(None)
    except:
        nsmap["_"] = None
    return nsmap


def xpath_ns(xml_tree, xpath, nsmap):
    if nsmap["_"] is None:
        #result = xml_tree.xpath(".//gramGrp/gram[@type='pos']")
        result = xml_tree.xpath(xpath)
    else:
        #result = xml_tree.xpath(".//_:gramGrp/_:gram[@type='pos']", namespaces=nsmap)
        result = xml_tree.xpath(xpath.replace("/", "/_:").replace("./_:", "./"), namespaces=nsmap)
    return result


def export(filename):
    parser = etree.XMLParser(encoding='utf-8')
    xml_tree = lxml.etree.parse(filename, parser)
    nsmap = prepare_ns(xml_tree)
    """
    if nsmap["_"] is None:
        result = xml_tree.xpath(".//gramGrp/gram[@type='pos']")
    else:
        result = xml_tree.xpath(".//_:gramGrp/_:gram[@type='pos']", namespaces=nsmap)
    """
    result = xpath_ns(xml_tree, ".//gramGrp/gram[@type='pos']", nsmap)
    out_filename = filename[:-4] + "-export.csv"
    pos = set()
    for r in result:
        pos.add(r.text)
    with open(out_filename, 'w', encoding='utf-8') as file:
        file.write("original_pos, tei_pos\n")   
        for r in pos:
            r = "" if r is None else r
            file.write(f"{r},\n")
    print(f"Exports have been saved to {out_filename}. Remember to save it as .csv format after editing.")


def remap(filename, acronym):
    csv_filename = filename[:-4] + "-export.csv"
    pos_map = dict()
    with open(csv_filename, encoding='utf-8') as file:
        csv_line = file.readlines()
    for line in csv_line[1:]:
        if line.strip() == "":
            continue
        k = ",".join(line.split(",")[:-1]).strip()
        v = line.split(",")[-1].strip()
        pos_map[k] = v
        #pos_map[line.split(",")[0].strip()] = line.split(",")[1].strip()
    parser = etree.XMLParser(encoding='utf-8')
    xml_tree = lxml.etree.parse(filename, parser)
    nsmap = prepare_ns(xml_tree)
    """
    if nsmap["_"] is None:
        result = xml_tree.xpath(".//gramGrp/gram[@type='pos']")
    else:
        result = xml_tree.xpath(".//_:gramGrp/_:gram[@type='pos']", namespaces=nsmap)
    """
    result = xpath_ns(xml_tree, ".//gramGrp/gram[@type='pos']", nsmap)
    for r in result:
        r.attrib["orig"] = "pos" if r.text is None else str(r.text).strip()
        k = str(r.text).strip()
        try:
            r.text = pos_map[k]
        except:
            continue
        #r.text = pos_map[r.text.split(",")[0].strip()]
    out_filename = filename[:-4] + "-remapped.xml"
    add_ids(xml_tree, acronym)
    xml_tree.write(out_filename, encoding='utf-8', pretty_print=True)
    print(f"Your xml has been remapped and saved to {out_filename}")


def add_ids(xml_tree, acronym):
    nsmap = prepare_ns(xml_tree)
    result = xpath_ns(xml_tree, ".//entry", nsmap)
    entry_counter = 1
    for entry in result:
        hw = xpath_ns(entry, ".//form/orth", nsmap)[0].text
        try:
            pos = xpath_ns(entry, ".//gramGrp/gram", nsmap)[0].text
        except:
            pos = "pos"
        if pos is None:
            pos = "pos"
        # try to remap old id
        try:
            entry.attrib["{http://www.w3.org/XML/1998/namespace}orig_id"] = entry.attrib["{http://www.w3.org/XML/1998/namespace}id"]
        except:
            pass
        id_str = f"{acronym}_{hw}_{entry_counter}_{pos}"
        entry.attrib["{http://www.w3.org/XML/1998/namespace}id"] = id_str
        sense_counter = 1
        sense_result = xpath_ns(entry, ".//sense", nsmap)
        for sense in sense_result:
            # try to remap old id
            try:
                sense.attrib["{http://www.w3.org/XML/1998/namespace}orig_id"] = sense.attrib["{http://www.w3.org/XML/1998/namespace}id"]
            except:
                pass
            sense.attrib["{http://www.w3.org/XML/1998/namespace}id"] = f"{id_str}_{sense_counter}"
            sense_counter += 1
        entry_counter += 1


if __name__ == "__main__":
    if ("export" not in sys.argv and "remap" not in sys.argv) or len(sys.argv) < 3:
        print(HELP)
        sys.exit(0)

    import lxml.etree

    if "export" in sys.argv:
        export(sys.argv[2])
    elif "remap" in sys.argv:
        if len(sys.argv) != 4:
            sys.argv.append("ACRO")
        remap(sys.argv[2], sys.argv[3])
    else:
        print("You shouldn't be here...")