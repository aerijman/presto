#!/usr/bin/env python3
"""
Calculates annotation set error rates
"""
# Info
__author__ = 'Jason Anthony Vander Heiden, Namita Gupta, Ruoyi Jiang'
from presto import __version__, __date__

# Imports
import os
import sys
import numpy as np
import pandas as pd
from argparse import ArgumentParser
from collections import OrderedDict, Counter
from textwrap import dedent
from time import time
from scipy.spatial.distance import pdist, squareform

from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

# Presto imports
from presto.Defaults import default_barcode_field, default_missing_chars, \
                            default_consensus_min_freq, default_consensus_min_qual, default_out_args
from presto.Commandline import CommonHelpFormatter, checkArgs, getCommonArgParser, parseCommonArgs
from presto.IO import countSeqFile, getFileType, countSeqSets, getOutputHandle, printLog, printProgress, readSeqFile
from presto.Sequence import getDNAScoreDict, calculateDiversity, qualityConsensus, \
                            frequencyConsensus, indexSeqSets
from presto.Multiprocessing import SeqResult, manageProcesses, feedSeqQueue
from presto.Annotation import parseAnnotation


# Defaults
default_bin_count = 50
default_min_count = 10
default_headers = ['mismatch', 'q_sum', 'total']
default_headers_dist = ['all']
default_nucleotides = ['A', 'C', 'G', 'T']
    


# Helper functions    
def initializeMismatchDictionary(seq_len):
    """
    Generates empty mismatch dictionary

    Arguments: 
      seq_len : the nt length of sequences in the set

    Returns: 
      dictionary : pandas.DataFrame objects containing [mismatch, qsum, total] counts  
    for {pos:sequence position, nuc:nucleotide pairs, qual:quality score, set:sequence set} 
    """
    # initialize the reference-sequence mismatch dictionary
    headers = default_headers
    nucleotides = default_nucleotides
    
    pos_dict = { header: {position:0 for position in range(seq_len)} for header in headers }
    nuc_dict = { header: \
        { nucleotide: {nucleotide:0 for nucleotide in nucleotides} for nucleotide in nucleotides} for header in headers }
    qual_dict = { header: {quality:0 for quality in range(94)} for header in headers }
    set_dict = { header: None for header in headers }
    
    # initialize the pairwise-distance mismatch dictionary
    bin_count = default_bin_count

    dist_dict = { header: np.zeros(bin_count) for header in default_headers_dist}

    # output the dictionary
    return { 'pos': pos_dict, 'nuc': nuc_dict, 'qual': qual_dict, 'set': set_dict, 'dist': dist_dict }


def calculateDistances(seq_iter, bin_count):
    """
    Computes and histograms the pairwise distance matrix from a set of sequences

    Arguments: 
      seq_iter : an iterable of strings
      bin_count : number of bins to use when computing histogram

    Returns: 
      dictionary : np.arrays for {all:all pairwise, dtn:distance to nearest} 
    """

    # Compute the distance matrix
    seq_array = np.array([[ord(nt) for nt in seq] for seq in seq_iter])
    pairwise_dist = squareform(pdist(seq_array, metric='hamming'))
    
    # Compute distance to nearest and upper triangular of all pairwise distance matrix
    all_pairwise = pairwise_dist[np.triu_indices_from(pairwise_dist, k=1)]

    return { 
        'all' : np.histogram(all_pairwise, bins=bin_count, range=(0.0, 1.0), density=False)[0]
    }


def countMismatches(seq_list, ref_seq, ignore_chars=default_missing_chars, 
                    score_dict=getDNAScoreDict(mask_score=(1, 1), gap_score=(1, 1))):
    """
    Counts the occurrence of nucleotide mismatches in a set of sequences

    Arguments: 
      seq_list : a list of SeqRecord objects with aligned sequences
      ref_seq : a SeqRecord object containing the reference sequence to match against
      ignore_chars : list of characters to exclude from mismatch counts
      score_dict : optional dictionary of alignment scores as {(char1, char2): score}

    Returns: 
      dictionary : dictionaries containing [mismatch, qsum, total] counts  
    for {pos:sequence position, nuc:nucleotide pairs, qual:quality score, set:sequence set, dist:sequence distances} 
    """

    # Define position mismatch DataFrame
    mismatch = initializeMismatchDictionary(len(ref_seq))

    for seq in seq_list:
        qual = seq.letter_annotations['phred_quality']
        for i, b in enumerate(seq):
            
            a = ref_seq[i]
            q = qual[i]
            
            if a not in ignore_chars and b not in ignore_chars:
                mismatch['pos']['total'][i] += 1
                mismatch['pos']['q_sum'][i] += q
                
                # Add nt counts, including for mismatches
                mismatch['nuc']['mismatch'][b][b] += 1
                for a_i in mismatch['nuc']['total'][b]: mismatch['nuc']['total'][b][a_i] += 1
                for a_i in mismatch['nuc']['q_sum'][b]: mismatch['nuc']['q_sum'][b][a_i] += q
            
                mismatch['qual']['total'][q] += 1
                mismatch['qual']['q_sum'][q] += q
            
            if score_dict[(a, b)] == 0:
                mismatch['pos']['mismatch'][i] += 1
                mismatch['nuc']['mismatch'][a][b] += 1
                #@ Remove nt if mismatch from previous count
                mismatch['nuc']['mismatch'][b][b] -= 1
                mismatch['qual']['mismatch'][q] += 1

    
    # defaults
    headers = default_headers
    headers_dist = default_headers_dist 
    bin_count = default_bin_count
    
    # Generate the set counter (for a given number of sequences in umi group, these are the mismatch values)
    mismatch['set'] = { header : { len(seq_list) : \
        sum(mismatch['pos'][header].values()) } for header in headers }
    
    # Calculate distances
    distance_mismatch = calculateDistances(seq_list, bin_count=bin_count)
    mismatch['dist'] = { header : distance_mismatch[header] for header in headers_dist }

    return mismatch


def processEEQueue(alive, data_queue, result_queue, cons_func, cons_args={}, 
                   min_count=default_min_count, max_diversity=None):
    """
    Pulls from data queue, performs calculations, and feeds results queue

    Arguments: 
      alive : a multiprocessing.Value boolean controlling whether processing 
            continues; when False function returns
      data_queue : a multiprocessing.Queue holding data to process
      result_queue : a multiprocessing.Queue to hold processed results
      cons_func : the function to use for consensus generation 
      cons_args : a dictionary of optional arguments for the consensus function
      min_count : threshold number of sequences to retain a set
      max_diversity : the minimum diversity score to retain a set;
                    if None do not calculate diversity
                        
    Returns: 
      None
    """
    try:
        # Iterator over data queue until sentinel object reached
        while alive.value:
            # Get data from queue
            if data_queue.empty():  continue
            else:  data = data_queue.get()
            # Exit upon reaching sentinel
            if data is None:  break
            
            # Define result dictionary for iteration
            result = SeqResult(data.id, data.data)
            result.results = {'pos':None, 
                              'nuc':None, 
                              'qual':None, 
                              'set':None}
            
            # Define sequences set
            seq_list = data.data
            seq_count = len(data)
            
            # Update log
            result.log['SET'] = data.id
            result.log['SEQCOUNT'] = seq_count
            for i, s in enumerate(seq_list):
                result.log['SEQ%i' % (i + 1)] = str(s.seq)
            
            # Check count threshold and continue if failed
            if len(data) < min_count:
                result_queue.put(result)
                continue
                
            #@ Check all sequences in group have the same length and continue if failed
            init_len = len(seq_list[0])
            if any(len(seq) != init_len for seq in seq_list):
                result_queue.put(result)
                continue
                
            # Calculate average pairwise error rate
            if max_diversity is not None:
                diversity = calculateDiversity(seq_list)
                result.log['DIVERSITY'] = diversity
                # Check diversity threshold and continue if failed
                if diversity > max_diversity:
                    result_queue.put(result)
                    continue
                
            # Define reference sequence by consensus
            ref_seq = cons_func(seq_list, **cons_args)
            
            # Count mismatches against consensus
            mismatch = countMismatches(seq_list, ref_seq)
            
            # Calculate average reported and observed error
            reported_q = mismatch['set']['q_sum'][len(seq_list)] / mismatch['set']['total'][len(seq_list)]
            error_rate = mismatch['set']['mismatch'][len(seq_list)] / mismatch['set']['total'][len(seq_list)]
    
            # Update log
            result.log['REFERENCE'] = str(ref_seq.seq)
            result.log['MISMATCH'] = ''.join(['*' if x > 0 else ' ' \
                                              for x in mismatch['pos']['mismatch']])
            result.log['ERROR'] = '%.6f' % error_rate
            result.log['REPORTED_Q'] = '%.2f' % reported_q
            result.log['EMPIRICAL_Q'] = '%.2f' % (-10 * np.log10(max(error_rate, 1e-9)))

            # Update results and feed result queue
            result.valid = True
            result.results.update(mismatch)
            result_queue.put(result)
        else:
            sys.stderr.write('PID %s> Error in sibling process detected. Cleaning up.\n' \
                             % os.getpid())
            return None
    except:
        alive.value = False
        printError('Error processing sequence set with ID: %s.' % data.id, exit=False)
        raise

    return None



def collectEEQueue(alive, result_queue, collect_queue, seq_file, out_args, cluster_field):
    """
    Pulls from results queue, assembles results and manages log and file IO

    Arguments: 
      alive : a multiprocessing.Value boolean controlling whether processing 
            continues; when False function returns
      result_queue : a multiprocessing.Queue holding worker results
      collect_queue : a multiprocessing.Queue to store collector return values
      seq_file : the sample sequence file name
      out_args : common output argument dictionary from parseCommonArgs
      cluster_field : the field defining set membership

    Returns:
      None : (adds a dictionary of {log: log object, out_files: output file names} to collect_queue)
    """

    # Helper function for adding together entries from 2 dictionaries by summation
    def _addCounterDict(dict1, dict2):
        join = Counter(dict1)
        join.update(Counter(dict2))
        return dict(join)

    # Helper function for adding a mismatch dictionary to the total_mismatch dictionary
    def _updateTotalMismatch(total_mismatch, mismatch):
        for header in default_headers:
            total_mismatch['qual'][header] = \
                _addCounterDict(total_mismatch['qual'][header], mismatch['qual'][header])
            total_mismatch['set'][header] = \
                _addCounterDict(total_mismatch['set'][header], mismatch['set'][header])
            total_mismatch['pos'][header] = \
                _addCounterDict(total_mismatch['pos'][header], mismatch['pos'][header])
            for nucleotide in mismatch['nuc']['mismatch']:
                total_mismatch['nuc'][header][nucleotide] = \
                _addCounterDict(total_mismatch['nuc'][header][nucleotide], mismatch['nuc'][header][nucleotide])
        for header in default_headers_dist:
            total_mismatch['dist'][header] = total_mismatch['dist'][header] + mismatch['dist'][header]
        
        return total_mismatch

    try:
        # Count sets
        result_count = countSeqSets(seq_file, cluster_field, out_args['delimiter'])
        
        # Define empty DataFrames to store assembled results
        total_mismatch = initializeMismatchDictionary(0)

        # Open log file
        if out_args['log_file'] is None:
            log_handle = None
        else:
            log_handle = open(out_args['log_file'], 'w')
    except:
        alive.value = False
        raise
    
    try:
        # Iterator over results queue until sentinel object reached
        start_time = time()
        set_count = seq_count = pass_count = fail_count = 0
        while alive.value:
            # Get result from queue
            if result_queue.empty():  continue
            else:  result = result_queue.get()
            # Exit upon reaching sentinel
            if result is None:  break

            # Print progress for previous iteration
            printProgress(set_count, result_count, 0.05, start_time=start_time)
            
            # Update counts for iteration
            set_count += 1
            seq_count += result.data_count

            # Sum results
            if result:
                pass_count += 1
                total_mismatch = _updateTotalMismatch(total_mismatch, result.results)
            else:
                fail_count += 1
                
            # Write log
            printLog(result.log, handle=log_handle)
        else:
            sys.stderr.write('PID %s:  Error in sibling process detected. Cleaning up.\n' \
                             % os.getpid())
            return None

        headers = default_headers
        nucleotides = default_nucleotides 
        
        # Rearrange the nuc_dict and remove A,A T,T C,C G,G entries
        nuc_dict = {header: {(n1,n2): total_mismatch['nuc'][header][n1][n2] \
            for n2 in nucleotides \
                for n1 in nucleotides if n1 != n2} for header in headers}

        # Convert total_mismatch dictionary to pd
        pos_df = pd.DataFrame.from_dict(total_mismatch['pos'])
        qual_df = pd.DataFrame.from_dict(total_mismatch['qual'])
        nuc_df = pd.DataFrame.from_dict(nuc_dict)
        if pass_count > 0:
            set_df = pd.DataFrame.from_dict(total_mismatch['set'])
        dist_df = pd.DataFrame.from_dict(total_mismatch['dist'])
        dist_df.index = dist_df.index/len(dist_df.index)

        # find the threshold (average minimum between max and 0.75)
        dist = total_mismatch['dist']['all']
        dist = dist[np.argmax(dist):]
        thresh_df = pd.DataFrame.from_dict({ 'thresh' : { 
                        'ALL': dist_df.index[np.argmax(dist) + \
                            int(np.mean([index for index in np.argsort(dist[:int(len(dist)*0.75)]) if dist[index] == np.min(dist)]))]}
                    })

        # Print final progress
        printProgress(set_count, result_count, 0.05, start_time=start_time)
        
        # Generate log
        log = OrderedDict()
        for i in range(5): 
            log['OUTPUT%i' % (i + 1)] = None
        log['SETS'] = set_count
        log['SEQUENCES'] = seq_count
        log['PASS'] = pass_count
        log['FAIL'] = fail_count
        log['POSITION_ERROR'] = None 
        log['NUCLEOTIDE_ERROR'] = None
        log['QUALITY_ERROR'] = None
        log['ERROR_SET'] = None
     
        # Return if no mismatch data
        if pass_count == 0:
            collect_dict = {'log':log, 'out_files': None}
            collect_queue.put(collect_dict)
            return None
    
        # Calculate error rates
        pos_df['error'] = pos_df['mismatch'] / pos_df['total']
        nuc_df['error'] = nuc_df['mismatch'] / nuc_df['total']
        qual_df['error'] = qual_df['mismatch'] / qual_df['total']
        set_df['error'] = set_df['mismatch'] / set_df['total']

        # Bound minimum error to Q=90
        pos_df.loc[pos_df['error'] == 0, 'error'] = 1e-9
        nuc_df.loc[nuc_df['error'] == 0, 'error'] = 1e-9
        qual_df.loc[qual_df['error'] == 0, 'error'] = 1e-9
        set_df.loc[set_df['error'] == 0, 'error'] = 1e-9

        # Convert error to empirical quality score
        pos_df['emp_q'] = -10 * np.log10(pos_df['error'])
        nuc_df['emp_q'] = -10 * np.log10(nuc_df['error'])
        qual_df['emp_q'] = -10 * np.log10(qual_df['error'])
        set_df['emp_q'] = -10 * np.log10(set_df['error'])
    
        # Calculate reported quality means
        pos_df['rep_q'] = pos_df['q_sum'] / pos_df['total'] 
        nuc_df['rep_q'] = nuc_df['q_sum'] / nuc_df['total']
        qual_df['rep_q'] = qual_df['q_sum'] / qual_df['total']
        set_df['rep_q'] = set_df['q_sum'] / set_df['total']
            
        # Calculate overall error rate
        pos_error = pos_df['mismatch'].sum() / pos_df['total'].sum() 
        qual_error = qual_df['mismatch'].sum() / qual_df['total'].sum() 
        nuc_error = nuc_df['mismatch'].sum() / nuc_df['total'].sum()
        set_error = set_df['mismatch'].sum() / set_df['total'].sum() 
    
        # Build results dictionary
        assembled = {'pos':pos_df, 'qual':qual_df, 'nuc':nuc_df, 'set':set_df, 'dist': dist_df, 'thresh': thresh_df}

        # Write assembled error counts to output files
        out_files = writeResults(assembled, seq_file, out_args)
        
        # Update log
        for i, f in enumerate(out_files): 
            log['OUTPUT%i' % (i + 1)] = os.path.basename(f)
        log['POSITION_ERROR'] = '%.6f' % pos_error
        log['NUCLEOTIDE_ERROR'] = '%.6f' % (nuc_error * 3)
        log['QUALITY_ERROR'] = '%.6f' % qual_error
        log['ERROR_SET'] = '%.6f' % set_error
        log['ALL_THRESH'] = '%.6f' % thresh_df['thresh']['ALL']

        # Update collector results
        collect_dict = {'log':log, 'out_files': out_files}
        collect_queue.put(collect_dict)
    except:
        alive.value = False
        raise
    
    return None


def writeResults(results, seq_file, out_args):
    """
    Formats results and writes to output files

    Arguments: 
    results = assembled results dictionary
    seq_file = the sample sequence file name
    out_args = common output argument dictionary from parseCommonArgs

    Returns:
      tuple : (position error, nucleotide pairwise error, quality error, sequence set) file names
    """
    pos_df = results['pos']
    nuc_df = results['nuc']
    qual_df = results['qual']
    set_df = results['set']
    dist_df = results['dist']
    thresh_df = results['thresh']

    # Type conversion to int of mismatch and total columns
    pos_df[['mismatch', 'total']] = pos_df[['mismatch', 'total']].astype(int) 
    nuc_df[['mismatch', 'total']] = nuc_df[['mismatch', 'total']].astype(int) 
    qual_df[['mismatch', 'total']] = qual_df[['mismatch', 'total']].astype(int) 
    set_df[['mismatch', 'total']] = set_df[['mismatch', 'total']].astype(int)     
    dist_df[['all']] = dist_df[['all']].astype(int)
    
    # Write to tab delimited files
    file_args = {'out_dir':out_args['out_dir'], 'out_name':out_args['out_name'], 'out_type':'tab'}
    with getOutputHandle(seq_file, 'error-position', **file_args) as pos_handle, \
            getOutputHandle(seq_file, 'error-quality', **file_args) as qual_handle, \
            getOutputHandle(seq_file, 'error-nucleotide', **file_args) as nuc_handle, \
            getOutputHandle(seq_file, 'error-set', **file_args) as set_handle, \
            getOutputHandle(seq_file, 'distance-set', **file_args) as dist_handle, \
            getOutputHandle(seq_file, 'thresh-set', **file_args) as thresh_handle:

        pos_df.to_csv(pos_handle, sep='\t', na_rep='NA', index=True,
                      index_label='POSITION',
                      columns=['rep_q', 'mismatch', 'total', 'error', 'emp_q'],
                      header=['REPORTED_Q', 'MISMATCHES', 'OBSERVATIONS', 'ERROR', 'EMPIRICAL_Q'],
                      float_format='%.6f')
        nuc_df.to_csv(nuc_handle, sep='\t', na_rep='NA', index=True,
                      index_label=['REFERENCE','OBSERVED'],
                      columns=['rep_q', 'mismatch', 'total', 'error', 'emp_q'],
                      header=['REPORTED_Q', 'MISMATCHES', 'OBSERVATIONS', 'ERROR', 'EMPIRICAL_Q'],
                      float_format='%.6f')
        qual_df.to_csv(qual_handle, sep='\t', na_rep='NA', index=True,
                       index_label='Q',
                       columns=['rep_q', 'mismatch', 'total', 'error', 'emp_q'],
                       header=['REPORTED_Q', 'MISMATCHES', 'OBSERVATIONS', 'ERROR', 'EMPIRICAL_Q'],
                       float_format='%.6f')
        set_df.to_csv(set_handle, sep='\t', na_rep='NA', index=True,
                      index_label='SET_COUNT',
                      columns=['rep_q', 'mismatch', 'total', 'error', 'emp_q'],
                      header=['REPORTED_Q', 'MISMATCHES', 'OBSERVATIONS', 'ERROR', 'EMPIRICAL_Q'],
                      float_format='%.6f')
        dist_df.to_csv(dist_handle, sep='\t', na_rep='NA', index=True,
                      index_label='DISTANCE',
                      columns=['all'],
                      header=['ALL'],
                      float_format='%.6f')
        thresh_df.to_csv(thresh_handle, sep='\t', na_rep='NA', index=True,
                      index_label='TYPE',
                      columns=['thresh'],
                      header=['THRESH'],
                      float_format='%.6f')

    return (pos_handle.name, qual_handle.name, nuc_handle.name, set_handle.name, dist_handle.name, thresh_handle.name)


def estimateSets(seq_file, cons_func=frequencyConsensus, cons_args={}, 
                  cluster_field=default_barcode_field, min_count=default_min_count, max_diversity=None, 
                  out_args=default_out_args, nproc=None, queue_size=None):
    """
    Calculates error rates of sequence sets

    Arguments: 
      seq_file : the sample sequence file name
      cons_func : the function to use for consensus generation 
      cons_args : a dictionary of arguments for the consensus function
      cluster_field : the annotation field containing set IDs
      min_count : threshold number of sequences to consider a set
      max_diversity : a threshold defining the average pairwise error rate required to retain a read group;
                    if None do not calculate diversity
      out_args : common output argument dictionary from parseCommonArgs
      nproc : the number of processQueue processes;
            if None defaults to the number of CPUs
      queue_size : maximum size of the argument queue;
                 if None defaults to 2*nproc
                    
    Returns: 
      tuple : (position error, quality error, nucleotide pairwise error) output file names
    """
    # Define subcommand label dictionary
    cmd_dict = {frequencyConsensus:'freq', qualityConsensus:'qual'}
    
    # Print parameter info
    log = OrderedDict()
    log['START'] = 'EstimateError'
    log['FILE'] = os.path.basename(seq_file)
    log['MODE'] = cmd_dict.get(cons_func, cons_func.__name__)
    log['CLUSTER_FIELD'] = cluster_field
    log['MIN_COUNT'] = min_count
    log['MAX_DIVERSITY'] = max_diversity
    log['NPROC'] = nproc
    printLog(log)
    
    # Check input file type
    in_type = getFileType(seq_file)
    if in_type != 'fastq':
        printError('Input file must be FASTQ.')
    
    # Define feeder function and arguments
    index_args = {'field': cluster_field, 'delimiter': out_args['delimiter']}
    feed_func = feedSeqQueue
    feed_args = {'seq_file': seq_file,
                 'index_func': indexSeqSets, 
                 'index_args': index_args}
    # Define worker function and arguments
    work_func = processEEQueue
    work_args = {'cons_func': cons_func, 
                 'cons_args': cons_args,
                 'min_count': min_count,
                 'max_diversity': max_diversity}
    # Define collector function and arguments
    collect_func = collectEEQueue
    collect_args = {'seq_file': seq_file,
                    'out_args': out_args,
                    'cluster_field': cluster_field}

    # Call process manager
    result = manageProcesses(feed_func, work_func, collect_func, 
                             feed_args, work_args, collect_args, 
                             nproc, queue_size)
        
    # Print log
    result['log']['END'] = 'EstimateError'
    printLog(result['log'])
        
    return result['out_files']


# TODO: keeping nproc because may eventually be used for distance calculation, parallels ClusterSets barcode implementation.
# TODO: see getCommonArgParser(multiproc=False)
def estimateBarcode(seq_file, barcode_field=default_barcode_field, out_args=default_out_args, nproc=None):
    """
    Calculates error rates of barcode sequences

    Arguments: 
      seq_file : the sample sequence file name
      barcode_field : the annotation field containing barcode sequences.
      out_args : common output argument dictionary from parseCommonArgs
      nproc : the number of processQueue processes;
                if None defaults to the number of CPUs
                        
    Returns: 
      str : the name of the df containing the statistics of interest
    """
    
    # Function to extract to make SeqRecord object from a barcode annotation
    def _barcode(seq, field=barcode_field, delimiter=out_args['delimiter']):
        header = parseAnnotation(seq.description, delimiter=delimiter)
        return header[field]

    # Print parameter info
    log = OrderedDict()
    log['START'] = 'EstimateError'
    log['COMMAND'] = 'barcode'
    log['FILE'] = os.path.basename(seq_file)
    log['BARCODE_FIELD'] = barcode_field
    printLog(log)
    
    # Count sequence file and parse into a list of SeqRecords
    result_count = countSeqFile(seq_file)
    barcode_iter = (_barcode(x) for x in readSeqFile(seq_file))
    
    # Compute bin_count defaults to the length of the barcode + 1
    bin_count = len(_barcode(next(readSeqFile(seq_file)))) + 1
    mismatch = initializeMismatchDictionary(0)
    headers_dist = default_headers_dist

    # Calculate distances
    distance_mismatch = calculateDistances(barcode_iter, bin_count=bin_count)
    mismatch['dist'] = { header : distance_mismatch[header] for header in headers_dist }

    # Generate a df
    dist_df = pd.DataFrame.from_dict(mismatch['dist'])
    dist_df.index = dist_df.index/len(dist_df.index)
    dist_df[['all']] = dist_df[['all']].astype(int)

    #find the threshold (average minimum between 0 and 0.75)
    dist = mismatch['dist']['all']
    thresh_df = pd.DataFrame.from_dict({ 'thresh' : { 
                        'ALL': dist_df.index[int(np.mean([index for index in np.argsort(dist[:int(len(dist)*0.75)]) if dist[index] == np.min(dist)]))]}
                    })

    file_args = {'out_dir':out_args['out_dir'], 'out_name':out_args['out_name'], 'out_type':'tab'}

    # Output as tsv
    with getOutputHandle(seq_file, 'distance-barcode', **file_args) as dist_handle, \
        getOutputHandle(seq_file, 'thresh-barcode', **file_args) as thresh_handle:
        
        dist_df.to_csv(dist_handle, sep='\t', na_rep='NA', index=True,
                      index_label='DISTANCE',
                      columns=['all'],
                      header=['ALL'],
                      float_format='%.6f')
        thresh_df.to_csv(thresh_handle, sep='\t', na_rep='NA', index=True,
                      index_label='TYPE',
                      columns=['thresh'],
                      header=['THRESH'],
                      float_format='%.6f')
                      
    # Update log
    log['OUTPUT 1'] = os.path.basename(dist_handle.name)
    log['OUTPUT 2'] = os.path.basename(thresh_handle.name)
    log['SEQUENCES'] = result_count
    log['ALL_THRESH'] = '%.6f' % thresh_df['thresh']['ALL']
    log['END'] = 'EstimateError'
    printLog(log)

    return (dist_handle.name, thresh_handle.name)



#TODO: yaml output with flag
def getArgParser():
    """
    Defines the ArgumentParser
                      
    Returns: 
      ArgumentParser : ArgumentParser object
    """
    # Define output file names and header fields
    fields = dedent(
             '''
             output files:
                 error-position
                     estimated error by read position.
                 error-quality
                     estimated error by the quality score assigned within the input file.
                 error-nucleotide
                     estimated error by nucleotide.
                 error-set
                     estimated error by barcode read group size.
                 distance-set
                     estimated error by pairwise hamming distances
                 thresh-set
                     thresholds from pairwise hamming distances for clustering groups

                 distance-barcode
                     estimated error by pairwise hamming distances
                 thresh-barcode
                     thresholds from pairwise hamming distances for clustering barcodes

             output fields:
                 POSITION
                     read position with base zero indexing.
                 Q
                     Phred quality score.
                 OBSERVED
                     observed nucleotide value.
                 REFERENCE
                     consensus nucleotide for the barcode read group.
                 SET_COUNT
                     barcode read group size.
                 REPORTED_Q
                     mean Phred quality score reported within the input file for the given
                     position, quality score, nucleotide or read group.
                 MISMATCHES
                     count of observed mismatches from consensus for the given position,
                     quality score, nucleotide or read group.
                 OBSERVATIONS
                     total count of observed values for each position, quality score,
                     nucleotide or read group size.
                 ERROR
                     estimated error rate.
                 EMPIRICAL_Q
                     estimated error rate converted to a Phred quality score.
                 ALL
                     histogram (count) of all pairwise distance distribution
                 DTN
                     histogram (count) of distance to nearest distribution
                 DISTANCE
                     length normalized hamming distance 
             ''')
    
    # Define ArgumentParser
    parser = ArgumentParser(description=__doc__, epilog=fields,
                            parents=[getCommonArgParser(seq_out=False,
                                                        failed=False,
                                                        multiproc=True)],
                            formatter_class=CommonHelpFormatter, add_help=False)
    group_help = parser.add_argument_group('help')
    group_help.add_argument('--version', action='version',
                            version='%(prog)s:' + ' %s-%s' %(__version__, __date__))
    group_help.add_argument('-h', '--help', action='help', help='show this help message and exit')
    subparsers = parser.add_subparsers(title='subcommands', dest='command', metavar='',
                                       help='Estimation method')
    # TODO:  This is a temporary fix for Python issue 9253
    subparsers.required = True
    
    # Parent parser
    parent_parser = getCommonArgParser(multiproc=True)

    # Error profiling arguments for sets
    parser_set = subparsers.add_parser('set', parents=[parent_parser],
                                       formatter_class=CommonHelpFormatter, add_help=False,
                                       help='Estimates error statistics within annotation sets.',
                                       description='Estimates error statistics within annotation sets.')
    group_set = parser_set.add_argument_group('grouped sequence error profiling arguments')
    group_set.add_argument('-f', action='store', dest='cluster_field', type=str, default=default_barcode_field,
                             help='The name of the annotation field to group sequences by')
    group_set.add_argument('-n', action='store', dest='min_count', type=int, default=default_min_count,
                             help='The minimum number of sequences needed to consider a set')
    group_set.add_argument('--mode', action='store', dest='mode', choices=('freq', 'qual'), default='freq',
                             help='''Specifies which method to use to determine the consensus
                                  sequence. The "freq" method will determine the consensus by
                                  nucleotide frequency at each position and assign the most
                                  common value.  The "qual" method will weight values by their
                                  quality scores to determine the consensus nucleotide at
                                  each position.''')
    group_set.add_argument('-q', action='store', dest='min_qual', type=float, default=default_consensus_min_qual,
                             help='''Consensus quality score cut-off under which an ambiguous
                                  character is assigned.''')
    group_set.add_argument('--freq', action='store', dest='min_freq', type=float, default=default_consensus_min_freq,
                             help='''Fraction of character occurrences under which an ambiguous
                                  character is assigned.''')
    group_set.add_argument('--maxdiv', action='store', dest='max_diversity', type=float, default=None,
                             help='''Specify to calculate the nucleotide diversity of each read
                                  group (average pairwise error rate) and exclude groups which
                                  exceed the given diversity threshold.''')
    parser_set.set_defaults(func=estimateSets)
    

    # Error profiling arguments for barcodes
    parser_barcode = subparsers.add_parser('barcode', parents=[parent_parser],
                                       formatter_class=CommonHelpFormatter, add_help=False,
                                       help='Calculates pairwise distance metrics of barcode sequences.',
                                       description='Calculates pairwise distance metrics of barcode sequences.')
    group_barcode = parser_barcode.add_argument_group('barcode sequence estimation arguments')
    group_barcode.add_argument('-f', action='store', dest='barcode_field', type=str, default=default_barcode_field,
                             help='The name of the barcode field')
    parser_barcode.set_defaults(func=estimateBarcode)
    
    return parser


if __name__ == '__main__':
    """
    Parses command line arguments and calls main function
    """
    # Parse arguments
    parser = getArgParser()
    checkArgs(parser)
    args = parser.parse_args()
    args_dict = parseCommonArgs(args)

    # Convert case of fields
    if args_dict['command'] == 'set':
        if args_dict['cluster_field']:  
              args_dict['cluster_field'] = args_dict['cluster_field'].upper()
    
        # Define cons_func and cons_args
        if args_dict['mode'] == 'freq':
            args_dict['cons_func'] = frequencyConsensus
            args_dict['cons_args'] = {'min_freq':args_dict['min_freq']}
        elif args_dict['mode'] == 'qual':
            args_dict['cons_func'] = qualityConsensus
            args_dict['cons_args'] = {'min_qual':args_dict['min_qual'], 
                                      'min_freq':args_dict['min_freq'], 
                                      'dependent':False}
        del args_dict['mode']
        if 'min_freq' in args_dict:  del args_dict['min_freq']
        if 'min_qual' in args_dict:  del args_dict['min_qual']
    
    # Call estimateError for each sample file    
    del args_dict['seq_files']
    del args_dict['func']
    del args_dict['command']
    for f in args.__dict__['seq_files']:
        args_dict['seq_file'] = f
        args.func(**args_dict)

