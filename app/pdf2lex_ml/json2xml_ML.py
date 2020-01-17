import xml.etree.ElementTree as ET
import json


def json2xml( json_in_file, xml_raw, xml_out_file ):

    json_data = json.load( open( json_in_file, 'r' ) )

    tree_raw = ET.parse( xml_raw )
    root_raw = tree_raw.getroot()
    tokens_raw = list( root_raw.iter( 'TOKEN' ) )

    page_level_tokens = json_data['page_level'][0]
    page_level_labels = json_data['page_level'][1]
    # entry_level_tokens = json_data['entry_level'][0]
    # entry_level_labels = json_data['entry_level'][1]
    # sense_level_tokens = json_data['sense_level'][0]
    # sense_level_labels = json_data['sense_level'][1]

    doc_elm = ET.Element( 'document' )
    body_elm = ET.SubElement( doc_elm, 'body' )
    cur_elm = body_elm

    label_prev = ""
    i_p = 0
    # i_e = 0
    # i_s = 0
    i_pt = 0
    prev_page = int( tokens_raw[0].attrib['page'] )
    for token_r in tokens_raw:

        if token_r.text is None:        # empty tokens were skipped
            continue

        cur_page = int( token_r.attrib['page'] )

        if prev_page != cur_page:
            i_p += 1
            i_pt = 0
            prev_page = cur_page

        token_pl = page_level_tokens[i_p][i_pt]
        token_pl_text = token_pl[4][6:]

        if token_r.text != token_pl_text:
            print( "error! misaligned data!" )
            break

        label_cur = page_level_labels[i_p][i_pt]

        if label_cur == 'SCRAP':
            if cur_elm.tag == 'container' and cur_elm.attrib['name'] == 'dictScrap':
                cur_elm.append( token_r )
            else:
                scrap_cont = ET.SubElement( cur_elm, 'container', attrib={'name' : 'dictScrap'} )
                cur_elm = scrap_cont
                cur_elm.append( token_r )

        elif label_cur == 'ENTRY_START':
            entry_cont = ET.SubElement( body_elm, 'container', attrib={'name' : 'entry'} )
            cur_elm = entry_cont
            cur_elm.append( token_r )

        elif label_cur == 'ENTRY_INSIDE':
            if cur_elm.tag != 'container' or (cur_elm.tag == 'container' and cur_elm.attrib['name'] != 'entry'):
                entry_cont = ET.SubElement( body_elm, 'container', attrib={'name': 'entry'} )
                cur_elm = entry_cont

            # TODO implement other levels, ENTRY and SENSE levels here

            cur_elm.append( token_r )

        i_pt += 1


    xml_string = ET.tostring( doc_elm, encoding='unicode', method='xml' )
    with open( xml_out_file, 'w' ) as f:
        f.write( xml_string )

    return xml_string





### The following main stub demonstrates the usage of this script. There are 3 variables to be specified:
#       - json_ml_results_file: path to .json file containing the results set prepared by the functions in train_ML.py
#       - xml_raw_file: path to .xml file containing the raw pdf2xml transformation. Only tokens inside with all the
#       attributes. This is the same raw file as used in the first step, xml2json_ML.py
#       - xml_out_file: path to final result of the ML pipeline: .xml file in lexonomy format, meaning tokens
#       encapsulated in containers specifying the different layers of dictionary entries.

if __name__ == "__main__":

    # inputs
    json_ml_results_file = ''
    xml_raw_file = ''
    # outputs
    xml_out_file = ''
    # run
    json2xml( json_ml_results_file, xml_raw_file, xml_out_file )


