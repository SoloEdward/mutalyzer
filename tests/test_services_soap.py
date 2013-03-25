"""
Tests for the SOAP interface to Mutalyzer.
"""


from mutalyzer.util import monkey_patch_suds; monkey_patch_suds()

import os
from datetime import datetime, timedelta
import time
import mutalyzer
from mutalyzer.output import Output
from mutalyzer.sync import CacheSync
from mutalyzer import Db
from mutalyzer.util import slow
import logging
import urllib2
from suds.client import Client
from suds import WebFault
from nose.tools import *


# Suds logs an awful lot of things with level=DEBUG, including entire WSDL
# files and SOAP responses. On any error, this is all dumped to the console,
# which is very unconvenient. The following suppresses most of this.
logging.raiseExceptions = 0
logging.basicConfig(level=logging.INFO)
for logger in ('suds.metrics', 'suds.wsdl', 'suds.xsd.schema',
               'suds.xsd.sxbasic', 'suds.xsd.sxbase', 'suds.xsd.query',
               'suds.transport.http', 'suds.xsd.deplist', 'suds.mx.core',
               'suds.mx.literal', 'suds.resolver', 'suds.client',
               'suds.umx.typed'):
    logging.getLogger(logger).setLevel(logging.ERROR)


WSDL_URL = 'http://localhost/mutalyzer/services/?wsdl'


class TestWSDL():
    """
    Test the Mutalyzer SOAP interface WSDL description.
    """
    def test_wsdl(self):
        """
        Test if the WSDL is available and looks somewhat sensible.
        """
        wsdl = urllib2.urlopen(WSDL_URL).read()
        assert wsdl.startswith("<?xml version='1.0' encoding='UTF-8'?>")
        assert 'name="Mutalyzer"' in wsdl


class TestServicesSoap():
    """
    Test the Mutalyzer SOAP interface.
    """
    def setUp(self):
        """
        Initialize web service entrypoint.

        @todo: Start the standalone server and stop it in self.tearDown
        instead of depending on some running instance at a fixed address.
        """
        self.client = Client(WSDL_URL, cache=None)
        #self.client.options.cache.setduration(seconds=120)

    def test_checksyntax_valid(self):
        """
        Running checkSyntax with a valid variant name should return True.
        """
        r = self.client.service.checkSyntax('AB026906.1:c.274G>T')
        assert_equal(r.valid, True)

    def test_checksyntax_invalid(self):
        """
        Running checkSyntax with an invalid variant name should return False
        and give at least one error message.
        """
        r = self.client.service.checkSyntax('0:abcd')
        assert_equal(r.valid, False)
        assert len(r.messages.SoapMessage) >= 1

    @raises(WebFault)
    def test_checksyntax_empty(self):
        """
        Running checkSyntax with no variant name should raise exception.
        """
        self.client.service.checkSyntax()

    def test_transcriptinfo_valid(self):
        """
        Running transcriptInfo with valid arguments should get us a Transcript
        object.
        """
        r = self.client.service.transcriptInfo(LOVD_ver='123', build='hg19',
                                               accNo='NM_002001.2')
        assert_equal(r.trans_start, -99)
        assert_equal(r.trans_stop, 1066)
        assert_equal(r.CDS_stop, 774)

    def test_numberconversion_gtoc_valid(self):
        """
        Running numberConversion with valid g variant should give a list of
        c variant names.
        """
        r = self.client.service.numberConversion(build='hg19',
                                                 variant='NC_000001.10:g.159272155del')
        assert_equal(type(r.string), list)
        assert 'NM_002001.2:c.1del' in r.string

    def test_numberconversion_ctog_valid(self):
        """
        Running numberConversion with valid c variant should give a list of
        g variant names.
        """
        r = self.client.service.numberConversion(build='hg19',
                                                 variant='NM_002001.2:c.1del')
        assert_equal(type(r.string), list)
        assert 'NC_000001.10:g.159272155del' in r.string

    def test_numberconversion_gtoc_gene(self):
        """
        Running numberConversion with valid g variant and a gene name should
        give a list of c variant names on transcripts for the given gene.
        """
        r = self.client.service.numberConversion(build='hg19',
                                                 variant='NC_000011.9:g.111959693G>T',
                                                 gene='C11orf57')
        assert_equal(type(r.string), list)
        # Fix for r536: disable the -u and +d convention.
        #assert 'NM_001082969.1:c.*2178+d3819G>T' in r.string
        #assert 'NM_001082970.1:c.*2178+d3819G>T' in r.string
        #assert 'NM_018195.3:c.*2178+d3819G>T' in r.string
        assert 'NM_001082969.1:c.*5997G>T' in r.string
        assert 'NM_001082970.1:c.*5997G>T' in r.string
        assert 'NM_018195.3:c.*5997G>T' in r.string

    def test_numberconversion_gtoc_no_transcripts(self):
        """
        Running numberConversion with valid g variant but no transcripts
        close to it should give an empty list.
        """
        r = self.client.service.numberConversion(build='hg19',
                                                 variant='chr7:g.345T>C')
        assert_false(r)

    def test_numberconversion_gtoc_required_gene(self):
        """
        Running numberConversion with valid g variant but no transcripts
        close to it, but with a gene name, should give a list of c variant
        names on transcripts for the given gene.
        """
        r = self.client.service.numberConversion(build='hg19',
                                                 variant='chr7:g.345T>C',
                                                 gene='LOC100132858')
        assert_equal(type(r.string), list)
        # Fix for r536: disable the -u and +d convention.
        #assert 'XM_001715131.2:c.1155+d19483A>G' in r.string
        assert 'XM_001715131.2:c.*19483A>G' in r.string

    def test_gettranscriptsbygenename_valid(self):
        """
        Running getTranscriptsByGeneName with valid gene name should give a
        list of transcripts.
        """
        r = self.client.service.getTranscriptsByGeneName(build='hg19',
                                                         name='DMD')
        assert_equal(type(r.string), list)
        for t in ['NM_004006.2',
                  'NM_000109.3',
                  'NM_004021.2',
                  'NM_004009.3',
                  'NM_004007.2',
                  'NM_004018.2',
                  'NM_004022.2']:
            assert t in r.string

    def test_gettranscriptsbygenename_invalid(self):
        """
        Running getTranscriptsByGeneName with invalid gene name should not
        give a result.
        """
        r = self.client.service.getTranscriptsByGeneName(build='hg19',
                                                         name='BOGUSGENE')
        assert_false(r)

    def test_gettranscriptsandinfo_valid(self):
        """
        Running getTranscriptsAndInfo with a valid genomic reference should
        give a list of TranscriptInfo objects.
        """
        r = self.client.service.getTranscriptsAndInfo('AL449423.14')
        assert_equal(type(r.TranscriptInfo), list)
        names = [t.name for t in r.TranscriptInfo]
        for t in ['CDKN2B_v002',
                  'CDKN2B_v001',
                  'MTAP_v005',
                  'CDKN2A_v008',
                  'CDKN2A_v007',
                  'C9orf53_v001',
                  'CDKN2A_v001']:
            assert t in names

    def test_gettranscriptsandinfo_restricted_valid(self):
        """
        Running getTranscriptsAndInfo with a valid genomic reference and a
        gene name should give a list of TranscriptInfo objects restricted
        to the gene.
        """
        r = self.client.service.getTranscriptsAndInfo('AL449423.14', 'CDKN2A')
        assert_equal(type(r.TranscriptInfo), list)
        names = [t.name for t in r.TranscriptInfo]
        for t in ['CDKN2A_v008',
                  'CDKN2A_v007']:
            assert t in names
        for t in ['CDKN2B_v002',
                  'CDKN2B_v001',
                  'MTAP_v005',
                  'C9orf53_v001']:
            assert_false(t in names)

    def test_gettranscriptsmapping(self):
        """
        Running getTranscriptsMapping should give a list of
        TranscriptMappingInfo objects.
        """
        r = self.client.service.getTranscriptsMapping('hg19', 'chr16', 70680470, 70807150, 1)
        assert_equal(type(r.TranscriptMappingInfo), list)
        names = [t.name for t in r.TranscriptMappingInfo]
        for t in ('NM_152456',
                  'NM_138383',
                  'NM_018052',
                  'NR_034083'):
            assert t in names

    def test_mappinginfo(self):
        """
        Running mappingInfo should give a Mapping object.
        """
        r = self.client.service.mappingInfo('3.0-beta-06', 'hg19', 'NM_001100.3', 'g.112037014G>T')
        assert_equal(r.endoffset, 117529978)
        assert_equal(r.start_g, 112037014)
        assert_equal(r.startoffset, 117529978)
        assert_equal(r.mutationType, "subst")
        assert_equal(r.end_g, 112037014)
        assert_equal(r.startmain, 1388)
        assert_equal(r.endmain, 1388)

    def test_mappinginfo(self):
        """
        Running mappingInfo should give a Mapping object.
        """
        r = self.client.service.mappingInfo('3.0-beta-06', 'hg19', 'NM_001008541.1', 'g.112039014G>T')
        assert_equal(r.endoffset, 0)
        assert_equal(r.start_g, 112039014)
        assert_equal(r.startoffset, 0)
        assert_equal(r.mutationType, 'subst')
        assert_equal(r.end_g, 112039014)
        assert_equal(r.startmain, 175)
        assert_equal(r.endmain, 175)

    def test_mappinginfo_compound(self):
        """
        Running mappingInfo with compound variant should give a Mapping object.
        """
        r = self.client.service.mappingInfo('3.0-beta-06', 'hg19', 'NM_001008541.1', 'g.[112039014G>T;112039018T>A]')
        assert_equal(r.endoffset, 0)
        assert_equal(r.start_g, 112039014)
        assert_equal(r.startoffset, 0)
        assert_equal(r.mutationType, 'compound')
        assert_equal(r.end_g, 112039018)
        assert_equal(r.startmain, 175)
        assert_equal(r.endmain, 179)

    def test_mappinginfo_reverse(self):
        """
        Running mappingInfo on a reverse transcript should give a Mapping object.
        """
        r = self.client.service.mappingInfo('3.0-beta-06', 'hg19', 'NM_000035.3', 'g.104184170_104184179del')
        assert_equal(r.endoffset, 0)
        assert_equal(r.start_g, 104184170)
        assert_equal(r.startoffset, 0)
        assert_equal(r.mutationType, 'del')
        assert_equal(r.end_g, 104184179)
        assert_equal(r.startmain, 1016)
        assert_equal(r.endmain, 1007)

    def test_mappinginfo_compound_reverse(self):
        """
        Running mappingInfo with compound variant on a reverse transcript should give a Mapping object.
        """
        r = self.client.service.mappingInfo('3.0-beta-06', 'hg19', 'NM_000035.3', 'g.[104184170_104184179del;104184182_104184183del]')
        assert_equal(r.endoffset, 0)
        assert_equal(r.start_g, 104184170)
        assert_equal(r.startoffset, 0)
        assert_equal(r.mutationType, 'compound')
        assert_equal(r.end_g, 104184183)
        assert_equal(r.startmain, 1016)
        assert_equal(r.endmain, 1003)

    def test_info(self):
        """
        Running the info method should give us some version information.
        """
        r = self.client.service.info()
        assert_equal(type(r.versionParts.string), list)
        assert_equal(r.version, mutalyzer.__version__)

    def test_getcache(self):
        """
        Running the getCache method should give us the expected number of
        cache entries.
        """
        created_since = datetime.today() - timedelta(days=14)

        database = Db.Cache()
        output = Output(__file__)
        sync = CacheSync(output, database)
        cache = sync.local_cache(created_since)

        r = self.client.service.getCache(created_since)
        if len(cache) > 0:
            assert_equal(len(r.CacheEntry), len(cache))

    def test_getdbsnpdescriptions(self):
        """
        Running getdbSNPDescriptions method should give us the expected HGVS
        descriptions for the given dbSNP id.
        """
        r = self.client.service.getdbSNPDescriptions('rs9919552')
        assert 'NC_000011.9:g.111959625C>T' in r.string
        assert 'NG_012337.1:g.7055C>T' in r.string
        assert 'NM_003002.2:c.204C>T' in r.string
        assert 'NP_002993.1:p.Ser68=' in r.string

    def test_gettranscripts(self):
        """
        Running getTranscripts should give a list of transcripts.
        """
        r = self.client.service.getTranscripts(build='hg19', chrom='chrX',
                                               pos=32237295)
        assert_equal(type(r.string), list)
        for t in ['NM_000109',
                  'NM_004006',
                  'NM_004007',
                  'NM_004009',
                  'NM_004010',
                  'NM_004011',
                  'NM_004012']:
            assert t in r.string

    def test_gettranscripts_with_versions(self):
        """
        Running getTranscripts with versions=True should give a list
        of transcripts with version numbers.
        """
        r = self.client.service.getTranscripts(build='hg19', chrom='chrX',
                                               pos=32237295, versions=True)
        assert_equal(type(r.string), list)
        for t in ['NM_000109.3',
                  'NM_004006.2',
                  'NM_004007.2',
                  'NM_004009.3',
                  'NM_004010.3',
                  'NM_004011.3',
                  'NM_004012.3']:
            assert t in r.string

    def test_ping(self):
        """
        Running the ping method should return 'pong'.
        """
        r = self.client.service.ping()
        assert_equal(r, 'pong')

    def test_runmutalyzer(self):
        """
        Just a runMutalyzer test.
        """
        r = self.client.service.runMutalyzer('NM_003002.2:c.274G>T')
        assert_equal(r.errors, 0)
        assert_equal(r.genomicDescription, 'NM_003002.2:n.335G>T')
        assert 'NM_003002.2(SDHD_v001):c.274G>T' in r.transcriptDescriptions.string

    def test_runmutalyzer_reference_info_nm(self):
        """
        Get reference info for an NM variant without version.
        """
        r = self.client.service.runMutalyzer('NM_003002:c.274G>T')
        assert_equal(r.errors, 0)
        assert_equal(r.referenceId, 'NM_003002')
        assert_equal(r.sourceId, 'NM_003002.3')
        assert_equal(r.sourceAccession, 'NM_003002')
        assert_equal(r.sourceVersion, '2')
        assert_equal(r.sourceGi, '222352156')
        assert_equal(r.molecule, 'n')

    def test_runmutalyzer_reference_info_nm_version(self):
        """
        Get reference info for an NM variant with version.
        """
        r = self.client.service.runMutalyzer('NM_003002.2:c.274G>T')
        assert_equal(r.errors, 0)
        assert_equal(r.referenceId, 'NM_003002.2')
        assert_equal(r.sourceId, 'NM_003002.2')
        assert_equal(r.sourceAccession, 'NM_003002')
        assert_equal(r.sourceVersion, '2')
        assert_equal(r.sourceGi, '222352156')
        assert_equal(r.molecule, 'n')

    def test_runmutalyzer_reference_info_ud(self):
        """
        Get reference info for a UD variant after creating it.

            UD_129433404385: NC_000023.10 31135344 33362726 2 NULL 2011-10-04 13:15:04
        """
        ud = str(self.client.service.sliceChromosome('NC_000023.10', 31135344, 33362726, 2))
        r = self.client.service.runMutalyzer(ud + ':g.1del')
        assert_equal(r.errors, 0)
        assert_equal(r.referenceId, ud)
        assert_equal(r.sourceId, 'NC_000023.10')
        assert_equal(r.sourceAccession, 'NC_000023')
        assert_equal(r.sourceVersion, '10')
        assert_equal(r.sourceGi, '224589822')
        assert_equal(r.molecule, 'g')

    def test_runmutalyzer_reference_info_lrg(self):
        """
        Get reference info for an LRG variant.
        """
        r = self.client.service.runMutalyzer('LRG_1t1:c.266G>T')
        assert_equal(r.errors, 0)
        assert_equal(r.referenceId, 'LRG_1')
        assert_equal(r.sourceId, 'LRG_1')
        assert_equal(r.molecule, 'g')

    def test_runmutalyzer_reference_info_ng(self):
        """
        Get reference info for an NG variant without version.
        """
        r = self.client.service.runMutalyzer('NG_012772:g.18964del')
        assert_equal(r.errors, 0)
        assert_equal(r.referenceId, 'NG_012772')
        assert_equal(r.sourceId, 'NG_012772.3')
        assert_equal(r.sourceAccession, 'NG_012772')
        assert_equal(r.sourceVersion, '3')
        assert_equal(r.sourceGi, '388428999')
        assert_equal(r.molecule, 'g')

    def test_runmutalyzer_reference_info_ng_version(self):
        """
        Get reference info for an NG variant with version.
        """
        r = self.client.service.runMutalyzer('NG_012772.3:g.18964del')
        assert_equal(r.errors, 0)
        assert_equal(r.referenceId, 'NG_012772.3')
        assert_equal(r.sourceId, 'NG_012772.3')
        assert_equal(r.sourceAccession, 'NG_012772')
        assert_equal(r.sourceVersion, '3')
        assert_equal(r.sourceGi, '388428999')
        assert_equal(r.molecule, 'g')

    def test_runmutalyzer_reference_info_gi(self):
        """
        Get reference info for a GI variant.
        """
        self.client.service.runMutalyzer('NG_012772.1:g.1del') # Make sure the server has this reference cached
        r = self.client.service.runMutalyzer('gi256574794:g.18964del')
        assert_equal(r.errors, 0)
        assert_equal(r.referenceId, 'NG_012772.1')
        assert_equal(r.sourceId, 'NG_012772.1')
        assert_equal(r.sourceAccession, 'NG_012772')
        assert_equal(r.sourceVersion, '1')
        assert_equal(r.sourceGi, '256574794')
        assert_equal(r.molecule, 'g')

    def test_runmutalyzer_exons(self):
        """
        Exon table in runMutalyzer output.
        """
        r = self.client.service.runMutalyzer('NM_004959.4:c.630_636del')
        assert_equal(r.errors, 0)
        expected_exons = [(1, 172, '-187', '-16'),
                          (173, 289, '-15', '102'),
                          (290, 431, '103', '244'),
                          (432, 1057, '245', '870'),
                          (1058, 1177, '871', '990'),
                          (1178, 1325, '991', '1138'),
                          (1326, 3095, '1139', '*1522')]
        assert_equal(len(r.exons.ExonInfo), len(expected_exons))
        for exon, expected_exon in zip(r.exons.ExonInfo, expected_exons):
            assert_equal((exon.gStart, exon.gStop, exon.cStart, exon.cStop),
                         expected_exon)

    def test_gettranscriptsandinfo_slice(self):
        """
        Running getTranscriptsAndInfo on a chromosomal slice should include
        chromosomal positions.

        slice: 48284000 - 48259456 (COL1A1 with 5001 and 2001 borders)
        translation start: 48284000 - 5001 + 1 = 48279000
        translation end: 48259456 + 2001 = 48261457
        """
        ud = str(self.client.service.sliceChromosomeByGene('COL1A1', 'human', 5000, 2000))
        r = self.client.service.getTranscriptsAndInfo(ud)
        assert_equal(type(r.TranscriptInfo), list)
        names = [t.name for t in r.TranscriptInfo]
        assert 'COL1A1_v001' in names
        for t in r.TranscriptInfo:
            if t.name != 'COL1A1_v001':
                continue
            assert_equal(t.cTransStart, '-126')
            assert_equal(t.gTransStart, 5001)
            assert_equal(t.chromTransStart, 48279000)
            assert_equal(t.cTransEnd, '*1406')
            assert_equal(t.gTransEnd, 22544)
            assert_equal(t.chromTransEnd, 48261457)
            assert_equal(t.sortableTransEnd, 5801)
            assert_equal(t.cCDSStart, '1')
            assert_equal(t.gCDSStart, 5127)
            assert_equal(t.chromCDSStart, 48278874)
            assert_equal(t.cCDSStop, '4395')
            assert_equal(t.gCDSStop, 21138)
            assert_equal(t.chromCDSStop, 48262863)

    def test_batchjob(self):
        """
        Submit a batch job.
        """
        variants = ['AB026906.1(SDHD):g.7872G>T',
                    'NM_003002.1:c.3_4insG',
                    'AL449423.14(CDKN2A_v002):c.5_400del']
        data = '\n'.join(variants).encode('base64')

        result = self.client.service.submitBatchJob(data, 'NameChecker')
        job_id = int(result)

        for _ in range(50):
            try:
                result = self.client.service.getBatchJob(job_id)
                break
            except WebFault:
                result = self.client.service.monitorBatchJob(job_id)
                assert int(result) <= len(variants)
                time.sleep(1)
        else:
            assert False

        assert_equal(len(result.decode('base64').strip().split('\n')) - 1,
                     len(variants))

    @slow
    def test_batchjob_toobig(self):
        """
        Submit the batch name checker with a too big input file.
        """
        seed = """
Lorem ipsum dolor sit amet, consectetuer adipiscing elit, sed diam nonummy
nibh euismod tincidunt ut laoreet dolore magna aliquam erat volutpat. Ut wisi
enim ad minim veniam, quis nostrud exerci tation ullamcorper suscipit lobortis
nisl ut aliquip ex ea commodo consequat. Duis autem vel eum iriure dolor in
hendrerit in vulputate velit esse molestie consequat, vel illum dolore eu
feugiat nulla facilisis at vero eros et accumsan et iusto odio dignissim qui
blandit praesent luptatum zzril delenit augue duis dolore te feugait nulla
facilisi."""
        data = seed
        # Very crude way of creating something at least 6MB in size
        while len(data) < 6000000:
            data += data

        try:
            self.client.service.submitBatchJob(data.encode('base64'), 'NameChecker')
            assert False
        except WebFault as e:
            # - senv:Client.RequestTooLong: Raised by Spyne, depending on
            #     the max_content_length argument to the HttpBase constructor.
            # - EMAXSIZE: Raised by Mutalyzer, depending on the
            #     batchInputMaxSize configuration setting.
            assert e.fault.faultcode in ('senv:Client.RequestTooLong', 'EMAXSIZE')
