import xml.etree.ElementTree as ET
import json
import sys

def json2xml( json_in_file, xml_raw, xml_out_file ):
    # Constructs final .xml file from the output of train_ML script and with tokens from raw .xml file, and output into
    # file at <xml_file_out>.

    json_data = json.load( open( json_in_file, 'r' ) )

    tree_raw = ET.parse( xml_raw )
    root_raw = tree_raw.getroot()
    tokens_raw = list( root_raw.iter( 'TOKEN' ) )

    page_level_tokens = json_data['level_1'][0]
    page_level_labels = json_data['level_1'][1]
    entry_level_tokens = json_data['level_2'][0]
    entry_level_labels = json_data['level_2'][1]
    sense_level_tokens = json_data['level_3'][0]
    sense_level_labels = json_data['level_3'][1]


    # get label for each token in the raw file
    token_labels = []

    i_lvl1 = 0
    i_lvl2 = 0
    i_lvl3 = 0
    i_t_lvl1 = 0
    i_t_lvl2 = 0
    i_t_lvl3 = 0
    prev_page = int( tokens_raw[0].attrib['page'] )
    for token_r in tokens_raw:

        label_cur = ["", "", ""]

        if token_r.text is None:  # empty tokens were skipped
            continue

        cur_page = int( token_r.attrib['page'] )

        if prev_page != cur_page:
            i_lvl1 += 1
            i_t_lvl1 = 0
            prev_page = cur_page

        token_lvl1 = page_level_tokens[i_lvl1][i_t_lvl1]
        token_lvl1_text = token_lvl1[4][6:]

        if token_r.text != token_lvl1_text:
            print( "error! misaligned data!" )
            break

        label_cur[0] = page_level_labels[i_lvl1][i_t_lvl1]

        if i_lvl2 < len( entry_level_tokens ):
            token_lvl2 = entry_level_tokens[i_lvl2][i_t_lvl2]
            token_lvl2_text = token_lvl2[4][6:]

            if token_r.text == token_lvl2_text:
                label_cur[1] = entry_level_labels[i_lvl2][i_t_lvl2]
                i_t_lvl2 += 1
                if i_t_lvl2 == len( entry_level_tokens[i_lvl2] ):
                    i_lvl2 += 1
                    i_t_lvl2 = 0

                if i_lvl3 < len( sense_level_tokens ):

                    token_lvl3 = sense_level_tokens[i_lvl3][i_t_lvl3]
                    token_lvl3_text = token_lvl3[4][6:]

                    if token_r.text == token_lvl3_text:
                        label_cur[2] = sense_level_labels[i_lvl3][i_t_lvl3]
                        i_t_lvl3 += 1
                        if i_t_lvl3 == len( sense_level_labels[i_lvl3] ):
                            i_lvl3 += 1
                            i_t_lvl3 = 0

        token_labels.append( label_cur )
        i_t_lvl1 += 1
    #print(len(token_labels))
    #print(len(tokens_raw))
    added_tokens = 0
    #print(token_labels[:100])
    # construct XML tree based on labels for each token
    body_elm = ET.Element( 'body' )
    # current elements by level
    cur_elm_lvl1 = None
    cur_elm_lvl2 = None
    cur_elm_lvl3 = None
    labels_prev = ['', '', '']

    for i, token_r in enumerate( tokens_raw ):

        if i > 0: labels_prev = token_labels[i-1]

        lbl_lvl1 = token_labels[i][0]
        lbl_lvl2 = token_labels[i][1]
        lbl_lvl3 = token_labels[i][2]

        """
        if lbl_lvl1 == 'noise':
            if cur_elm_lvl1 is not None and cur_elm_lvl1.tag == 'container' and cur_elm_lvl1.attrib['name'] == 'noise':
                cur_elm_lvl1.append( token_r )
                continue
            else:
                cur_elm_lvl1 = ET.SubElement( body_elm, 'container', attrib={'name' : 'noise'} )
                cur_elm_lvl1.append( token_r )
                continue

        """
        if 'entry' in lbl_lvl1:
            
            # if the lvl1 label is entry_start, or the current lvl1 element is not given (start of the data) or the current lvl1 element is a container, but not an entry, create a new entry container
            if lbl_lvl1 == 'entry_start' or cur_elm_lvl1 is None or (cur_elm_lvl1.tag == 'container' and cur_elm_lvl1.attrib['name'] != 'entry'):
                cur_elm_lvl1 = ET.SubElement( body_elm, 'container', attrib={'name': 'entry'} )
            # if the lvl2 label is scrap or none, just add the token to the lvl1 container and continue to the next token
            if lbl_lvl2 == 'scrap' or lbl_lvl2 == '':
                cur_elm_lvl1.append( token_r )
                added_tokens +=1
                continue
            # if the lvl2 label is noise, (if the lvl2 container is not noise, open a noise container,) add the token and continue
            elif lbl_lvl2 == 'noise':
                if cur_elm_lvl2 is None or (cur_elm_lvl2.tag == 'container' and cur_elm_lvl2.attrib['name'] != 'noise'):
                    cur_elm_lvl2 = ET.SubElement( cur_elm_lvl1, 'container', attrib={'name': 'noise'} )
                cur_elm_lvl2.append( token_r )
                added_tokens +=1
                continue
            else:
                # if there is a start label on the lvl2, open the new container
                # we go deeper only if this is a start tag, otherwise we disregard level 3 - might be a problem :-D
                if lbl_lvl2.endswith('_start'):
                    cur_elm_lvl2 = ET.SubElement( cur_elm_lvl1, 'container', attrib={'name': lbl_lvl2.split('_')[0]} )
                    # if the label is scrap or none, just add the token and continue
                else:
                    if labels_prev[1].split('_')[0] != lbl_lvl2.split('_')[0] or cur_elm_lvl2 is None:
                        cur_elm_lvl2 = ET.SubElement( cur_elm_lvl1, 'container', attrib={'name': lbl_lvl2.split('_')[0]} )
                if lbl_lvl3 == 'scrap' or lbl_lvl3 == '':
                    cur_elm_lvl2.append( token_r )
                    added_tokens += 1
                    continue
                else:
                    if lbl_lvl3 == 'noise':
                        if cur_elm_lvl3 is None or (cur_elm_lvl3.tag == 'container' and cur_elm_lvl3.attrib['name'] != 'noise'):
                            cur_elm_lvl3 = ET.SubElement( cur_elm_lvl2, 'container', attrib={'name': 'noise'} )
                        cur_elm_lvl3.append( token_r )
                        added_tokens +=1
                        continue
                    else:
                        if lbl_lvl3.endswith('_start'):
                            cur_elm_lvl3 = ET.SubElement( cur_elm_lvl2, 'container', attrib={'name': lbl_lvl3.split('_')[0]} )
                            cur_elm_lvl3.append( token_r )
                            added_tokens +=1
                            continue
                        else:
                            if labels_prev[2].split('_')[0] != lbl_lvl3.split('_')[0] or cur_elm_lvl3 is None:
                                cur_elm_lvl3 = ET.SubElement( cur_elm_lvl2, 'container', attrib={'name': lbl_lvl3.split('_')[0]} )
                            cur_elm_lvl3.append( token_r )
                            added_tokens += 1
                            continue
            """
            elif 'sense' in lbl_lvl2:

                if lbl_lvl2 == 'sense_start' or cur_elm_lvl2 is None or (cur_elm_lvl2.tag == 'container' and cur_elm_lvl2.attrib['name'] != 'sense'):
                    cur_elm_lvl2 = ET.SubElement( cur_elm_lvl1, 'container', attrib={'name': 'sense'} )

                if lbl_lvl3 == 'scrap':
                    cur_elm_lvl2.append( token_r )
                    continue
                else:
                    if labels_prev[2] != lbl_lvl3 or cur_elm_lvl3 is None:
                        cur_elm_lvl3 = ET.SubElement( cur_elm_lvl2, 'container', attrib={'name': lbl_lvl3} )
                    cur_elm_lvl3.append( token_r )

            else:
                if labels_prev[1] != lbl_lvl2 or cur_elm_lvl2 is None:
                    cur_elm_lvl2 = ET.SubElement( cur_elm_lvl1, 'container', attrib={'name': lbl_lvl2} )
                cur_elm_lvl2.append( token_r )
                continue
            """
        else:   # in case there is another level 1 container that is not entry or dictScrap
            if labels_prev[0].split('_')[0] != lbl_lvl1.split('_')[0] or cur_elm_lvl1 is None:
                cur_elm_lvl1 = ET.SubElement( body_elm, 'container', attrib={'name': lbl_lvl1} )
            cur_elm_lvl1.append( token_r )
            added_tokens +=1
        
    #print(added_tokens)


    # saved the constructed XML tree into the output .xml file
    xml_string = ET.tostring( body_elm, encoding='unicode', method='xml' )
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

    # input (output from train_ML script)
    json_ml_results_file = sys.argv[1]

    # input (raw .xml file path)
    xml_raw_file = sys.argv[2]

    # output file path
    xml_out_file = sys.argv[3]

    xml_str = json2xml( json_ml_results_file, xml_raw_file, xml_out_file )


