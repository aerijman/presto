"""
Unit tests for AssemblePairs
"""

__author__    = 'Jason Anthony Vander Heiden'
__copyright__ = 'Copyright 2014 Kleinstein Lab, Yale University. All rights reserved.'
__license__   = 'Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported'
__version__   = '0.4.5'
__date__      = '2014.12.11'

# Imports
import time, unittest
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from IgCore import readSeqFile
import AssemblePairs as mod


class TestAssemblePairs(unittest.TestCase):

    def setUp(self):
        print '-> %s()' % self._testMethodName
        self.ref_file = 'IMGT_Human_IGV.fasta'
        self.ref_dict = {s.id:s.upper() for s in readSeqFile(self.ref_file)}
        # MISEQ:121:000000000-A7VDM:1:1101:10041:1280
        #self.head_seq = Seq("CCACGTTTTAGTAATTAATACGGGAGCAAAAACCAGGGAAAGCCCCTAAGCTCCTGCTCTATGCTGCATCCACTTTGCAAAGTGTGGTCCCATCACGGTTCAGCGGCAGTGGATCTGGGACAGAATTCACTCTCACAATCAGCAGCCTGCAGCCTGAAGATTTTGCAACTTATTACTGTCAACAGCTTACTCCTTACCCTCCTACGTTCGCCCCAGGCCCCACGGTCGACCTCCACCCCCCTCTCGCTGCCCCCTCTCTCCCCTCCGACCCGCCTC")
        #self.tail_seq = Seq("GGCAAGAAGAAGAGGGGATACGAGAGCCAAGGGGGAGTGGAGTGGAGAGGTGTGCGCTTACGATCTACAAGTGTGAGTAATGAATACGGGAGCAAAAACGAGGGAAAGCCCCGAAGCTCCTGATCTATGCTGAATCCACTTTGCAAAGTGGGGTCCCATCAAGGTTCAGCGGCAGTGGATCTGGGACAGAATTCACTCTCACAATCAGCAGCCTGCAGCCTGAAGATTTTGCAACTTATTACTGTCAACAGCTTAATACTTACCCTCGGACGTTCGGCCAAGGGACCAAGGTGGAAATCAAACGAACTGTGGCTGCACCATCTGTC")

        # MISEQ:121:000000000-A7VDM:1:1101:13900:1538
        #self.head_seq = Seq("GGAGCTTGCATTAGCATCGATACGGGGAGCTGTGGGCTCAGAAGCAGAGTTCTGGGGTGTCTCCACCATGGCCTGGACCCCTCTCTGGCTCACTCTCCTCACTCTTTGCATAGGTTCTGTGGTTTCTTCTGAGCTGACTCAGGACCCTGCTGTGTCTGTGGCCTTGGGACAGACAGTCAGGATCACATGCCAAGGAGACCGCCTCAGAAGCTATTATGCAAGCTGGTCCCCGCAGAATCCAGGACAGGCCCCCCTCCTTCTCATCTATGGTATAAC")
        #self.tail_seq = Seq("CTTGGGACAGACAGTCAGGATCACAGGCCAAGGAGACAGGCTCAGAAGCTAGTATGCAAGCGGGTACCAGCAGAAGCCAGGACAGGCCCCTGTACTTGTCATCTATGGTAAAAACAACCGGCCCTCAGGGATCCCAGACCGATTCTCTGGCTTCAGCTCAGGAAACACAGCTTCCTTGACCATCACTGGGGCTCAGGCGGAAGATGAGGCTGACTATTACTGTAACTCCCGGGACAGCAGTGGTAACCATCCATTCGGCGGAGGGACCAAGCTGACCGTCCTAGGTCAGCCCAAGGCTGCCCCCTCGGTCACTCTGTTCCCACCCT")

        # Non-Overlmodping MISEQ:121:000000000-A7VDM:1:1101:13900:1538
        self.head_seq = Seq("GGAGCTTGCATTAGCATCGATACGGGGAGCTGTGGGCTCAGAAGCAGAGTTCTGGGGTGTCTCCACCATGGCCTGGACCCCTCTCTGGCTCACTCTCCTCACTCTTTGCATAGGTTCTGTGGTTTCTTCTGAGCTGACTCAGGACCCTGCTGTGTCTGTGGCCTTGGGACAGACAGTCAGGAC")
        self.tail_seq = Seq("TTGTCATCTATGGTAAAAACAACCGGCCCTCAGGGATCCCAGACCGATTCTCTGGCTTCAGCTCAGGAAACACAGCTTCCTTGACCATCACTGGGGCTCAGGCGGAAGATGAGGCTGACTATTACTGTAACTCCCGGGACAGCAGTGGTAACCATCCATTCGGCGGAGGGACCAAGCTGACCGTCCTAGGTCAGCCCAAGGCTGCCCCCTCGGTCACTCTGTTCCCACCCT")

        # MISEQ:121:000000000-A7VDM:1:1101:22042:1446
        #self.head_seq = Seq("GTCTCAACAAAATACCATCTACGGGATGTGTATTGGTACCAGCAACTCCCAGGATCGGCCCCCAAGCTCCTCATTTATAGTAGTAGCCAGCCGCCCTCAGGGGTCCCTGACCGATTCTCTGGCTCCAAGTCTGGCACCTCAGCCTCCCTGGCCCTCCGTGTGCTCCGTTCCGAAGATGACGCCGCTTATTCCTGTTCAGCCTGGGCTTACCCCCTGATTCGTCTTTCCTTGTTCGCCCCACCGTCCCCTCCCCCCCTCCTACCTCCGCCCCACGCC")
        #self.tail_seq = Seq("GAGAGGTGGGAGGAGCCGATCTGGGTCAACAAAATAGGATAGACGGGAAGGGTATTGGTACAAGCAACTCCCAGGAGCGGAGCCCAAGCTCGTCATTTATAGGAGAAGCCAGGGGCCCTCAGGGGTACCTGACCGATTCTCTGGCTCCAAGTCTGGAAGCTAAGCCTCCCTGGCCATCAGTGGGCTCCGGTACGAAGATGAGGCTGATTATTACTGTGCAGCATGGGATGACAGCCTGAGTGGTCTTTGGGTGTTCGGCGGAGGGACCAGGCTGACCGTCCTAGGTCAGCCCAAGGCTGCCCCCTCGGTCACTCTGTTCCCACCCT")


        self.head_rec = SeqRecord(self.head_seq, id='HEAD', name='HEAD', description='')
        self.tail_rec = SeqRecord(self.tail_seq, id='TAIL', name='TAIL', description='')
        #self.head_rec = SeqRecord(self.tail_seq, id='HEAD', name='HEAD', description='')
        #self.tail_rec = SeqRecord(self.head_seq, id='TAIL', name='TAIL', description='')

        self.start = time.time()

    def tearDown(self):
        t = time.time() - self.start
        print "<- %s() %.3f" % (self._testMethodName, t)

    #@unittest.skip("-> getUBlastAlignment() skipped\n")
    def test_getUBlastAlignment(self):
        head_df = mod.getUblastAlignment(self.head_rec, self.ref_file)
        tail_df = mod.getUblastAlignment(self.tail_rec, self.ref_file)
        print head_df
        print tail_df
        self.fail()

    #@unittest.skip("-> getBlastnAlignment() skipped\n")
    def test_getBlastnAlignment(self):
        head_df = mod.getBlastnAlignment(self.head_rec, self.ref_file)
        tail_df = mod.getBlastnAlignment(self.tail_rec, self.ref_file)
        print head_df
        print tail_df
        self.fail()

    #@unittest.skip("-> referenceAssembly() skipped\n")
    def test_referenceAssembly(self):
        stitch = mod.referenceAssembly(self.head_rec, self.tail_rec, self.ref_dict, self.ref_file)
        #print tuple(stitch.evalue)
        self.fail()

    #@unittest.skip("-> alignAssembly() skipped\n")
    def test_alignAssembly(self):
        head = SeqRecord(Seq("TTTCCGG"), id="HEAD",
                         letter_annotations={'phred_quality':[40,40,40,20,20,40,40]})
        tail = SeqRecord(Seq("CTGGAAA"), id="TAIL",
                         letter_annotations={'phred_quality':[40,20,40,40,40,40,40]})

        stitch = mod.alignAssembly(head, tail, alpha=0.1)
        print '    HEAD> %s' % head.seq
        print '    TAIL>    %s\n' % tail.seq
        print 'ASSEMBLY>', stitch.seq.seq
        print '   ERROR>', stitch.error
        print '  PVALUE>', stitch.pvalue, '\n'
        self.fail()