import xml.etree.ElementTree as ET
import json



def get_parent_container( e, parent_map ):
    # avoid self
    if e.tag.lower() == 'container':
        if e not in parent_map.keys():
            return None
        e = parent_map[e]
    # find container
    while True:
        if e.tag.lower() == 'container':
            return e
        if e not in parent_map.keys():
            return None
        e = parent_map[e]


def xml2json( xml_raw_file, xml_lex_file, json_out_file ):


    tree_raw = ET.parse( xml_raw_file )
    root_raw = tree_raw.getroot()
    tokens_raw = list( root_raw.iter( 'TOKEN' ) )

    tree_lex = ET.parse( xml_lex_file )
    parent_map = {c:p for p in tree_lex.iter() for c in p}
    root_lex = tree_lex.getroot()
    tokens_lex = list( root_lex.iter( 'TOKEN' ) )


    pages_data = []
    entries_data = []
    senses_data = []
    feats_page = []
    feats_entry = []
    feats_sense = []
    labels_page = []
    labels_entry = []
    labels_sense = []

    prev_entry = None
    prev_sense = None

    page_n = int( tokens_raw[0].attrib['page'] )
    line_n = 0
    # iterate over the annotated data that will be used for ML training
    for idx, token_a in enumerate( tokens_lex ):

        token_r = tokens_raw[idx]
        if not token_r.text == token_a.text:
            print( 'Misaligned data at token {}:{}!\nBreaking...'.format( idx, token_a ) )
            break

        page_token = int( token_r.attrib['page'] )
        if page_token != page_n:
            pages_data.append( (feats_page, labels_page) )
            # pages_data.append(feats_pages)
            feats_page = []
            labels_page = []
            page_n = page_token

        # extract features
        feat = ['SIZE=' + token_r.attrib['font-size'], 'BOLD=' + token_r.attrib['bold'], 'ITALIC=' + token_r.attrib['italic'], 'FONT=' + token_r.attrib['font-name'], 'TOKEN=' + token_r.text]

        # newline feature
        line_token = int( token_r.attrib['line'] )
        if line_token != line_n:
            feat.append( 'NEWLINE' )
            line_n = line_token


        # define containers
        entry = None
        form = None
        pos = None
        sense = None
        cit = None

        # collect all the containers
        container = get_parent_container( token_a, parent_map )
        while container is not None:

            if container.attrib['name'] == 'entry':
                entry = container
            elif container.attrib['name'] == 'form':
                form = container
            elif container.attrib['name'] == 'pos':
                pos = container
            elif container.attrib['name'] == 'sense':
                sense = container
            elif container.attrib['name'] == 'cit':
                cit = container

            container = get_parent_container( container, parent_map )

        # page level labels
        if entry is not None:

            if token_a == list( entry )[0]:
                label_p = 'ENTRY_START'
            else:
                label_p = 'ENTRY_INSIDE'

            # entry level labels
            if form is not None:
                label_e = 'FORM'
            elif pos is not None:
                label_e = 'POS'
            elif sense is not None:

                if token_a == list( sense )[0]:
                    label_e = 'SENSE_START'
                else:
                    label_e = 'SENSE_INSIDE'

                # sense level labels
                if cit is not None:
                    label_s = 'CIT'
                else:
                    label_s = 'INSIDE'

                # write the complete sense and start a new one
                if sense != prev_sense and prev_sense is not None:
                    senses_data.append( (feats_sense, labels_sense) )
                    feats_sense = []
                    labels_sense = []

                feats_sense.append( feat )
                labels_sense.append( label_s )
                prev_sense = sense

            else:
                label_e = 'INSIDE'

            # write the complete entry and start a new one
            if entry != prev_entry and prev_entry is not None:
                entries_data.append( (feats_entry, labels_entry) )
                feats_entry = []
                labels_entry = []

            feats_entry.append( feat )
            labels_entry.append( label_e )
            prev_entry = entry

        else:

            label_p = 'SCRAP'

        feats_page.append( feat )
        labels_page.append( label_p )



    # add all the training data that is not yet added
    pages_data.append( (feats_page, labels_page) )
    entries_data.append( (feats_entry, labels_entry) )
    senses_data.append( (feats_sense, labels_sense) )


    # save training data into JSONs
    # deprecated
    # json.dump( pages_data, open( json_pages, 'w' ), indent=4 )
    # json.dump( entries_data, open( json_entries, 'w' ), indent=4 )
    # json.dump( senses_data, open( json_senses, 'w' ), indent=4 )




    # prepare the rest of the data that will go into ML for prediction
    index_start = 0
    page_n = int( tokens_raw[0].attrib['page'] )
    unlabelled_pages = []   # order by pages, such will be the 1st level input
    feats_page = []
    line_n = 0
    for token_p in tokens_raw:

        if token_p.text is None:        # sometimes empty tokens appear
            continue

        page_token = int( token_p.attrib['page'] )
        if page_token != page_n and len( feats_page ) != 0:
            unlabelled_pages.append( feats_page )
            feats_page = []
        feat = ['SIZE=' + token_p.attrib['font-size'], 'BOLD=' + token_p.attrib['bold'], 'ITALIC=' + token_p.attrib['italic'], 'FONT=' + token_p.attrib['font-name'], 'TOKEN=' + token_p.text]

        line_token = int( token_p.attrib['line'] )
        if line_token != line_n:
            feat.append( 'NEWLINE' )
            line_n = line_token

        feats_page.append( feat )
        page_n = page_token


    unlabelled_pages.append( feats_page )
    # deprecated
    # json.dump( unlabelled_pages, open( json_unlabelled, 'w' ), indent=4 )

    json_dict = {'pages' : pages_data,
                 'entries' : entries_data,
                 'senses' : senses_data,
                 'unlabelled' : unlabelled_pages}

    json.dump( json_dict, open( json_out_file, 'w' ), indent=4 )
    return json_dict







### The following main stub demonstrates the usage of this script. There are 3 variables to be specified:
#       - xml_raw: path to .xml file containing the raw pdf2xml transformation. Only tokens inside with all the attributes.
#       - xml_lex: path to .xml file containing the annotation from Lexonomy. Tokens encapsulated in containers which
#       serve as true labels for ML.
#       - json_out: path to where the JSON of the prepared dataset for ML training will be saved. Ensure all directories
#       on the path exist.

if __name__ == "__main__":

    # inputs
    xml_raw = ''
    xml_lex = ''
    # outputs
    json_out = ''
    # run
    xml2json( xml_raw, xml_lex, json_out )



