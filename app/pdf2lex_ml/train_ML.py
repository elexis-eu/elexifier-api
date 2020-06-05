import json
import numpy as np
from keras.preprocessing import sequence
from keras.models import Model
from keras.layers import Input, Masking, Dense, Bidirectional, LSTM, TimeDistributed, Concatenate, Dropout
from keras.optimizers import Adam, SGD, RMSprop
import argparse
from datetime import datetime
from time import time
import os
import sys




def extract_tokens( dataset ):
    # Extracts all tokens from the dataset and prepares a dictionary (lookup table) for them and the  characters within
    # them. The dictionary acts as transformation table from tokens/chars to their number codes, used in the model.
    tokens = set()
    chars = set()
    for sequence in dataset:
        for instance in sequence:
          for feature in instance:
              if feature.startswith('TOKEN'):
                  tokens.add(feature)
              for c in feature[6:]:
                  chars.add(c)
    idx_t = {f:(i+1) for i, f in enumerate(tokens)}
    idx_c = {c:(i+1) for i, c in enumerate(chars)}
    return tokens, idx_t, idx_c



def one_hot_and_chars( dataset, idx={}, idx_c={} ):
    # Transforms dataset into one hot encoded features and sequence of character number codes. Also constructs a lookup
    # table for the one-hot encoded features (which position means which token).
    if len(idx)==0:
        lexicon=set()
        for sequence in dataset:
            for instance in sequence:
                for feature in instance:
                    if not feature.startswith('TOKEN'):
                        lexicon.add(feature)
        idx = {f:i for i,f in enumerate(lexicon)}
    oh_dataset=[]
    chars_dataset = []
    for sequence in dataset:
        oh_sequence=[]
        char_arrays_sequence = []
        for instance in sequence:
            oh_instance=np.zeros(len(idx))
            char_array = []
            for feature in instance:
                if feature in idx:
                    oh_instance[idx[feature]]=1
                    continue
                if len(idx_c)>0 and feature.startswith('TOKEN'):
                    for c in feature[6:]:
                        if c in idx_c.keys():
                            char_array.append(idx_c[c])
                        else:
                            char_array.append(0)

            oh_sequence.append(oh_instance)
            char_arrays_sequence.append(char_array)
        oh_dataset.append(oh_sequence)
        chars_dataset.append(char_arrays_sequence)
    return oh_dataset, chars_dataset, idx



def one_hot_target( dataset, idx={} ):
    # Transforms labels into one-hot encoded dataset and constructs a lookup table for the labels.
    if len(idx)==0:
        lexicon=set()
        for sequence in dataset:
            for label in sequence:
                lexicon.add(label)
        idx={l:i for i,l in enumerate(lexicon)}
    cat_dataset=[]
    for sequence in dataset:
        cat_sequence=[]
        for label in sequence:
            oh_label=np.zeros(len(idx))
            oh_label[idx[label]]=1
            cat_sequence.append(oh_label)
        cat_dataset.append(cat_sequence)
    return np.array(cat_dataset),idx



def model_cLSTM( input_shape_feat, input_shape_char, output_len, dropout=0.4, verbose=True ):
    # Constructs a char-LSTM model
    features_input = Input( shape=input_shape_feat )
    chars_input = Input( shape=input_shape_char )
    chars_masked = Masking( 0 ) (chars_input)
    features_masked = Masking( 0 ) (features_input)
    chars_embed = Bidirectional( LSTM( 8, return_sequences=True ) ) (chars_masked)
    chars_embed = Dropout( dropout ) (chars_embed)
    features_merged = Concatenate( axis=-1 ) ([features_masked, chars_embed])

    h = Bidirectional( LSTM( 20, return_sequences=True ) ) (features_merged)
    h = Dropout( dropout ) (h)
    # # optional second biLSTM layer (did not perform better in initial test)
    # h = Bidirectional( LSTM( 8, return_sequences=True ) ) (h)
    # h = Dropout( dropout ) (h)
    y = TimeDistributed( Dense( output_len, activation='softmax' ) ) (h)
    model = Model( inputs=[features_input, chars_input], outputs=y )
    if verbose: print( model.summary() )

    return model



def train_on_data( data, n_rounds=10, verbose=True, logdir="", batch_size=5, max_sequence_len=None ):
    # prepares training and testing data, then trains the model for <n_rounds>.

    dt = datetime.now().strftime( "%Y%m%d-%H%M%S" )
    logfile = None
    if verbose and logdir is not "":
        if not os.path.exists( logdir ):
            os.makedirs( logdir )
        logfile = os.path.join( logdir, "train_c-lstm_{}.log".format(dt) )

    # data preparation
    # data = json.load( open( data_file, 'r' ) )
    # have to do two iterations - one 75:25, another 100:0
    n_train = int( round( len( data )*0.75 ) )
    train = data[:n_train]
    test = data[n_train:]
    #print len(train),len(test)
    #print data
    #print [e[1] for e in test]
    #print sum([len(e[1]) for e in test])
    if sum([len(e[1]) for e in test]) > 100:
        x_train = [e[0] for e in train]
        y_train = [e[1] for e in train]
        x_test = [e[0] for e in test]
        y_test = [e[1] for e in test]

        # check that all labels from test are present in train, else discard test data
        train_labels = set([f for e in y_train for f in e])
        test_labels = set([f for e in y_test for f in e])
        #print train_labels
        #print test_labels
        if len(train_labels)<len(train_labels.union(test_labels)):
            test=[]

    x = [e[0] for e in data]
    y = [e[1] for e in data]
    
    all_tokens, idx_t, idx_c = extract_tokens( x )
    if sum([len(e[1]) for e in test]) > 100:
        x_train_oh, x_train_chars, idx = one_hot_and_chars( x_train, idx_c=idx_c )
        x_test_oh, x_test_chars, _ = one_hot_and_chars( x_test, idx, idx_c )
        x_oh, x_chars, _ = one_hot_and_chars( x, idx, idx_c)
    else:
        x_oh, x_chars, idx = one_hot_and_chars( x, idx_c=idx_c)

    if max_sequence_len==None:
        max_sequence_len = max( [len(e) for e in x_oh] )*2
    
    if sum([len(e[1]) for e in test]) > 100:
        x_train_oh = sequence.pad_sequences( x_train_oh, max_sequence_len )
        x_test_oh = sequence.pad_sequences( x_test_oh, max_sequence_len )
    x_oh = sequence.pad_sequences( x_oh, max_sequence_len )

    max_carray_len = 0
    for seq in x_chars:
        max_cur = max( [len(arr) for arr in seq] )
        if max_cur > max_carray_len:
            max_carray_len = max_cur
    max_carray_len *= 2

    if sum([len(e[1]) for e in test]) > 100:
        x_train_chars_pad = [sequence.pad_sequences( seq, max_carray_len ) for seq in x_train_chars]
        x_train_chars = sequence.pad_sequences( x_train_chars_pad, max_sequence_len )
        x_test_chars_pad = [sequence.pad_sequences( seq, max_carray_len ) for seq in x_test_chars]
        x_test_chars = sequence.pad_sequences( x_test_chars_pad, max_sequence_len )
        X_train = [x_train_oh, x_train_chars]
        X_test = [x_test_oh, x_test_chars]
    x_chars_pad = [sequence.pad_sequences( seq, max_carray_len ) for seq in x_chars]
    x_chars = sequence.pad_sequences( x_chars_pad, max_sequence_len )
    X = [x_oh, x_chars]

    if sum([len(e[1]) for e in test]) > 100:
        y_train_oh, idx_label = one_hot_target( y_train )
        y_test_oh, _ = one_hot_target( y_test, idx_label )
        y_train_oh = sequence.pad_sequences( y_train_oh, max_sequence_len )
        y_test_oh = sequence.pad_sequences( y_test_oh, max_sequence_len )
        y_oh, _ = one_hot_target( y, idx_label )
        y_oh = sequence.pad_sequences( y_oh, max_sequence_len )
    else:
         y_oh, idx_label = one_hot_target( y )
         y_oh = sequence.pad_sequences( y_oh, max_sequence_len )
    
    rev_idx_label = {v:k for k, v in idx_label.items()}

    data_infos = {'idx': idx,
                  'idx_c': idx_c,
                  'idx_label': idx_label,
                  'max_sequence_len': max_sequence_len,
                  'max_carray_len': max_carray_len}

    model = model_cLSTM( (max_sequence_len, len( idx )), (max_sequence_len, max_carray_len), len( idx_label ) )
#    optim = Adam( lr=0.005 )
#    optim = SGD( lr=0.01, momentum=0.9, nesterov=True )
    optim = RMSprop( lr=0.005 )     # RMSprop seems to yield best results, according to preliminary tests
    model.compile( loss='categorical_crossentropy', optimizer=optim, metrics=['accuracy'] )
    # best_acc = 0
    # best_model_path = 'best_models/best_model_' + dt + '.h5'

    report=''
    t1 = time()
    for i_round in range(n_rounds):
        if i_round==0 and (sum([len(e[1]) for e in test]) <= 100 or len(y_test_oh)==0):
            continue
        if verbose: print('ROUND', i_round)
        t_r0 = time()
        #print y_oh
        if i_round==0:
            h = model.fit( X_train, y_train_oh, batch_size=batch_size, epochs=10, validation_data=(X_test, y_test_oh), shuffle=True )
        else:
            h = model.fit( X, y_oh, batch_size=batch_size, epochs=10, shuffle=True )

        # # possible best model saving mechanism.
        # score, acc = model.evaluate( X_test, y_test_oh, batch_size=5 )
        # if acc > best_acc:
        #     print( "best model accuracy,", acc, ", saving..." )
        #     best_acc = acc
        #     model.save_weights( best_model_path )

        if i_round == 0:#verbose:
            y_test_pred = model.predict( X_test )

            def to_tags(sequence):
                result=[]
                for label in sequence:
                    result.append(rev_idx_label[np.argmax(label)])
                return result

            lf = None
            if logfile is not None:
                lf = open(logfile, "a+")
                lf.write("ROUND {}\n\n".format(i_round))

            pred=[]
            true=[]
            from sklearn.metrics import confusion_matrix,classification_report,accuracy_score
            for p,t,f in zip(y_test_pred, y_test_oh, x_test):
                for i,u in enumerate(t):
                    if sum(u)>0:
                        break
                if verbose:
                    for a,b,c in zip(to_tags(p[i:]),to_tags(t[i:]),f):
                        if a!=b:
                            # print('!',a,b,'|'.join(c))
                            if lf: lf.write('! {} {} {}\n'.format(a, b, '|'.join(c)))
                        else:
                            # print(a,b,'|'.join(c))
                            if lf: lf.write('{} {} {}\n'.format(a, b, '|'.join(c)))
                    # print("")
                    if lf: lf.write("\n")
                pred.extend(to_tags(p[i:]))
                true.extend(to_tags(t[i:]))

            report+=str(confusion_matrix(true,pred))+'\n'
            report+=str(classification_report(true,pred))+'\n'
            report+='Approximate running time '+str((time()-t_r0)*4)+'\n'
            print(report)
            print("Accuracy:", accuracy_score(true,pred))
            print("ROUND time:", (time()-t_r0), "s")
            print("")

            if lf:
                lf.write("{}\n".format(confusion_matrix(true,pred)))
                lf.write("{}\n".format(classification_report(true,pred)))
                lf.write("Accuracy: {}\n".format(accuracy_score(true,pred)))
                lf.write("ROUND time: {} s\n".format((time()-t_r0)))
                lf.write("\n")
                lf.close()

    # in the end load the model with the best score (if saving best models)
    # model.load_weights( best_model_path )
    if verbose: print("Training time:", (time()-t1), "s")
    return model, data_infos, report



def train_ML( data_packed_file, json_out_file, logdir ):
    # main method that takes care of training and prediction on all three levels.

    data = json.load( open( data_packed_file, 'r' ) )
    
    msl=max([len(e) for e in data['unlabelled']])
    # train on 1st level data
    model_pages, pages_infos, report1 = train_on_data( data['level_1'], n_rounds=4, verbose=True, logdir=logdir, batch_size=4, max_sequence_len=msl )


    # predict on unlabelled data

    # 1.) pages level prediction
    # prepare new data
    level1_tokens = data['unlabelled']
    print(str(len(level1_tokens)))
    x_new = level1_tokens
    x_new_oh, x_new_chars, _ = one_hot_and_chars( x_new, pages_infos['idx'], pages_infos['idx_c'] )
    x_new_oh = sequence.pad_sequences( x_new_oh, pages_infos['max_sequence_len'] )
    x_new_chars_pad = [sequence.pad_sequences( seq, pages_infos['max_carray_len'] ) for seq in x_new_chars]
    x_new_chars = sequence.pad_sequences( x_new_chars_pad, pages_infos['max_sequence_len'] )
    X_new = [x_new_oh, x_new_chars]
    rev_idx_label_pages = {v: k for k, v in pages_infos['idx_label'].items()}

    # predict
    y_pred_pages = model_pages.predict( X_new )
    print(str(y_pred_pages.shape))
    print(str(pages_infos['max_sequence_len']))
    # get 1st level labels and prepare 2nd level data based on predictions
    level1_labels = []
    level2_tokens = []
    entry = []
    for i_p in range( len( level1_tokens ) ):

        n_tokens_in = len( level1_tokens[i_p] )

        page_labels = []
        for i_t in range( n_tokens_in ):

            # take care of correct indices with regard to padding and max_sequence_len
            if n_tokens_in <= pages_infos['max_sequence_len']:
                i_t_pad = i_t + pages_infos['max_sequence_len'] - n_tokens_in
            else:
                #what to do with far too long instances? esp. if just parts of pages are annotated
                #page_labels.append( label_cur )
                #continue
                i_t_pad = i_t
            #print y_pred_pages.shape,i_p,i_t_pad
            #print y_pred_pages[i_p][i_t_pad]
            token_cur = level1_tokens[i_p][i_t]
            label_cur = rev_idx_label_pages[np.argmax( y_pred_pages[i_p][i_t_pad] )]
            page_labels.append( label_cur )
            

            if label_cur == 'scrap':
                continue

            if label_cur == 'entry_start':

                if len( entry ) != 0:
                    level2_tokens.append( entry )
                entry = []

            entry.append( token_cur )
        
        level1_labels.append( page_labels )

    if len( entry ) != 0:
        level2_tokens.append( entry )


    # 2.) entries level prediction
    # train on 2nd level data
    model_entries, entries_infos, report2 = train_on_data( data['level_2'], n_rounds=4, verbose=True, logdir=logdir, batch_size=8 )

    # prepare new data
    x_new = level2_tokens
    x_new_oh, x_new_chars, _ = one_hot_and_chars( x_new, entries_infos['idx'], entries_infos['idx_c'] )
    x_new_oh = sequence.pad_sequences( x_new_oh, entries_infos['max_sequence_len'] )
    x_new_chars_pad = [sequence.pad_sequences( seq, entries_infos['max_carray_len'] ) for seq in x_new_chars]
    x_new_chars = sequence.pad_sequences( x_new_chars_pad, entries_infos['max_sequence_len'] )
    X_new = [x_new_oh, x_new_chars]
    rev_idx_label_entries = {v: k for k, v in entries_infos['idx_label'].items()}

    # predict
    y_pred_entries = model_entries.predict( X_new )

    # get 2nd level labels and prepare 3rd level data based on predictions
    level2_labels = []
    level3_tokens = []
    sense = []
    for i_e in range( len( y_pred_entries ) ):

        n_tokens_in = len( level2_tokens[i_e] )
        entry_labels = []
        for i_t in range( n_tokens_in ):

            # take care of correct indices with regard to padding and max_sequence_len
            if n_tokens_in <= entries_infos['max_sequence_len']:
                i_t_pad = i_t + entries_infos['max_sequence_len'] - n_tokens_in
            else:
                i_t_pad = i_t

            token_cur = level2_tokens[i_e][i_t]
            if i_t_pad < entries_infos['max_sequence_len']:
                label_cur = rev_idx_label_entries[np.argmax( y_pred_entries[i_e][i_t_pad] )]
            else:
                label_cur = entry_labels[-1] # this is probably the reason for "0" labels at some points?

            entry_labels.append( label_cur )

            if 'sense' not in label_cur:
                continue

            if label_cur == 'sense_start':

                if len( sense ) != 0:
                    level3_tokens.append( sense )
                sense = []

            sense.append( token_cur )

        level2_labels.append( entry_labels )

    if len( sense ) != 0:
        level3_tokens.append( sense )


    # 3.) senses level prediction
    # train on third level data
    if len( data['level_3'][0][0] ) > 0:
        
        if len(set([item for sublist in [e[1] for e in data['level_3']] for item in sublist]))<2:
            report3='no annotations given'
            level3_tokens=[]
        else:
            model_senses, senses_infos, report3 = train_on_data( data['level_3'], n_rounds=4, verbose=True, logdir=logdir, batch_size=8 )

            # prepare new data
            x_new = level3_tokens
            x_new_oh, x_new_chars, _ = one_hot_and_chars( x_new, senses_infos['idx'], senses_infos['idx_c'] )
            x_new_oh = sequence.pad_sequences( x_new_oh, senses_infos['max_sequence_len'] )
            x_new_chars_pad = [sequence.pad_sequences( seq, senses_infos['max_carray_len'] ) for seq in x_new_chars]
            x_new_chars = sequence.pad_sequences( x_new_chars_pad, senses_infos['max_sequence_len'] )
            X_new = [x_new_oh, x_new_chars]
            rev_idx_label_senses = {v: k for k, v in senses_infos['idx_label'].items()}

            # predict
            y_pred_senses = model_senses.predict( X_new )

    else:
        report3='no annotations given'

    # get 3rd level labels
    level3_labels = []
    for i_s in range( len( level3_tokens ) ):
        n_tokens_in = len( level3_tokens[i_s] )
        sense_labels = []
        for i_t in range( n_tokens_in ):
            # hacky way of resolving the situation where there is no level3 training data
            if len( data['level_3'][0][0] ) == 0:
                sense_labels.append('scrap')
                continue

            # take care of correct indices with regard to padding and max_sequence_len
            if n_tokens_in <= senses_infos['max_sequence_len']:
                i_t_pad = i_t + senses_infos['max_sequence_len'] - n_tokens_in
            else:
                i_t_pad = i_t

            # token_cur = level3_tokens[i_s][i_t]
            if i_t_pad < senses_infos['max_sequence_len']:
                label_cur = rev_idx_label_senses[np.argmax( y_pred_senses[i_s][i_t_pad] )]
            else:
                label_cur = sense_labels[-1] # this is probably the reason for "0" labels at some points?
            sense_labels.append( label_cur )

        level3_labels.append( sense_labels )


    # save the prediction results to json
    json_data = {'level_1': (level1_tokens, level1_labels) ,
                 'level_2': (level2_tokens, level2_labels),
                 'level_3': (level3_tokens, level3_labels)
                }
 
    json.dump( json_data, open( json_out_file, 'w' ), indent=4 )

    return json_data, "LEVEL 1\n\n"+report1+"\n\nLEVEL 2\n\n"+report2+"\n\nLEVEL 3\n\n"+report3






### The following main stub demonstrates the usage of this script. There are 2 variables to be specified:
#       - json_in_file: path to .json file containing the dataset prepared by the functions in xml2json_ML.py
#       - json_out_file: path to .json file into which the results of the ML will be written. Ensure all directories
#       on the path exist.
#       - logdir: optional (set to '' for it to be ignored) directory where logs will be saved.

if __name__ == "__main__":

    # input file path (output of xml2json_ML script)
    json_in_file = sys.argv[1]
    # output file path (input into json2xml_ML script)
    json_out_file = sys.argv[2]
    # log directory path
    logdir = ''

    jdata, report = train_ML( json_in_file, json_out_file, logdir )
    open('report.temp','w').write(report)



