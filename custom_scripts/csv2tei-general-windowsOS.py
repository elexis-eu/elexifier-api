#!/usr/bin/env python3
import sys

import pandas as pd

input_filename = sys.argv[1]
df = pd.read_csv(input_filename, index_col=False,
                 sep='\t' if input_filename.endswith('.tsv') else None)

expected_columns = ['lemma', 'pos', 'definition']
if not all(col in df for col in expected_columns):
    sys.exit('ERROR: Table requires columns: ' + str(expected_columns))
expected_columns = ['entry_id', 'sense_id']
if not all(col in df for col in expected_columns):
    print('WARNING: Table could have (additionally) columns: ' + str(expected_columns))

try:
    head_xml = open('teiHeader.xml').read()
except IOError:
    print('WARNING: Missing ./teiHeader.xml (containing `<teiHeader/>`). '
          'Will use blank.', file=sys.stderr)
    head_xml = '\n'
else:
    if not head_xml.strip().startswith('<teiHeader>'):
        sys.exit('ERROR: File teiHeader.xml does not start with "<teiHeader>"')
    if not head_xml.strip().endswith('</teiHeader>'):
        sys.exit('ERROR: File teiHeader.xml does not end with "</teiHeader>"')


UD_POS = ['ADJ', 'ADP', 'ADV', 'AUX', 'CCONJ',
          'DET', 'INTJ', 'NOUN', 'NUM', 'PART',
          'PRON', 'PROPN', 'PUNCT', 'SCONJ',
          'SYM', 'VERB', 'X']
for pos in df['pos'].unique():
    if pos.upper() not in UD_POS:
        sys.exit(f'ERROR: POS values must be from Univ.Deps.v2. '
                 f'Got {pos!r}, expected one of: {UD_POS}')

sort_keys = (
    (['entry_id'] if 'entry_id' in df else []) +
    ['lemma', 'pos'] +
    (['sense_id'] if 'sense_id' in df else [])
)
df.sort_values(sort_keys, inplace=True, ignore_index=True)

have_entry_id = 'entry_id' in df
have_sense_id = 'sense_id' in df

if have_entry_id:
    assert df['entry_id'].nunique() == df['lemma'].nunique(),\
        'Number of `entry_id` must match number of distinct `lemma`'
if have_sense_id:
    assert df['sense_id'].nunique() == len(df), \
        'Every sense requires unique `sense_id`'


def write_entries(write_out):
    for (lemma, pos), subdf in df.groupby(['lemma', 'pos']):
        entry_id = f' xml:id="{subdf["entry_id"].iloc[0]}"' if have_entry_id else ''
        senses = []
        for n, sense in enumerate(subdf.itertuples(index=False), 1):
            sense_id = f' xml:id="{sense.sense_id}"' if have_sense_id else ''
            senses.append(f'<sense n="{n}"{sense_id}><def>{sense.definition}</def></sense>')
        senses = '\n'.join(senses)
        write_out(f'''\
<entry{entry_id}>
<form type="lemma"><orth>{lemma}</orth></form>
<gramGrp><gram type="pos">{pos}</gram></gramGrp>
{senses}
</entry>
''')


with open('output.xml', 'w', encoding="utf-8") as fd:
    fd.write('''
<?xml version="1.0" encoding="UTF-8"?>
<?xml-model href="http://www.tei-c.org/release/xml/tei/custom/schema/relaxng/tei_all.rng"
            schematypens="http://relaxng.org/ns/structure/1.0" type="application/xml"?>
<!-- Validate with `xmllint -relaxng $model-href $file` -->
<TEI xmlns="http://www.tei-c.org/ns/1.0">
''')
    fd.write(head_xml)
    fd.write('\n<text><body>\n')
    write_entries(fd.write)
    fd.write('</body></text></TEI>\n')
