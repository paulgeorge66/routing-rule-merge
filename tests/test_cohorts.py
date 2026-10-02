import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from routing_merge.cohorts import CohortFetcher


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.fetcher=CohortFetcher(self.root)
        self.entries=[(i,{'name':name,'url':f'https://raw.githubusercontent.com/owner/repo/main/{name}.txt'}) for i,name in enumerate(['one','two'],1)]
        self.parse=lambda source,index,text:[text]
        self.validate=lambda source,rules:None

    def seed(self):
        def download(url,*args,**kwargs):
            return (json.dumps({'sha':'a'*40}),{}) if 'api.github.com' in url else ('old-'+url.rsplit('/',1)[1],{})
        with patch('routing_merge.cohorts.download',side_effect=download):
            return self.fetcher.load(self.entries,self.parse,self.validate)

    def test_partial_new_revision_recovers_entire_previous_cohort(self):
        old=self.seed()
        snapshot=next(self.root.glob('*.json')).read_text()
        def download(url,*args,**kwargs):
            if 'api.github.com' in url:return json.dumps({'sha':'b'*40}),{}
            if url.endswith('two.txt'):raise RuntimeError('offline')
            return 'new-one.txt',{}
        with patch('routing_merge.cohorts.download',side_effect=download):
            results=self.fetcher.load(self.entries,self.parse,self.validate)
        self.assertEqual([x[0] for x in results],[x[0] for x in old])
        self.assertTrue(all(x[1]['fetch_status']=='stale' and x[1]['revision_sha']=='a'*40 for x in results))
        self.assertEqual(next(self.root.glob('*.json')).read_text(),snapshot)

    def test_same_verified_revision_reuses_validated_files_without_download(self):
        self.seed()
        with patch('routing_merge.cohorts.download',return_value=(json.dumps({'sha':'a'*40}),{})) as download:
            results=self.fetcher.load(self.entries,self.parse,self.validate)
        self.assertEqual(download.call_count,1)
        self.assertTrue(all(x[1]['fetch_status']=='not_modified' for x in results))

    def test_old_or_corrupt_cohort_cannot_hide_an_outage(self):
        self.seed()
        path=next(self.root.glob('*.json'))
        snapshot=json.loads(path.read_text());snapshot['validated_at']=time.time()-25*3600;path.write_text(json.dumps(snapshot))
        with patch('routing_merge.cohorts.download',side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):self.fetcher.load(self.entries,self.parse,self.validate)
        snapshot['validated_at']=time.time();snapshot['files'][self.entries[0][1]['url']]['text']='tampered';path.write_text(json.dumps(snapshot))
        with patch('routing_merge.cohorts.download',side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):self.fetcher.load(self.entries,self.parse,self.validate)

    def test_invalid_new_file_does_not_replace_validated_cohort(self):
        self.seed()
        def validate(source,rules):
            if rules==['invalid']:raise ValueError('malformed source')
        def download(url,*args,**kwargs):
            return (json.dumps({'sha':'b'*40}),{}) if 'api.github.com' in url else ('invalid',{})
        with patch('routing_merge.cohorts.download',side_effect=download):
            results=self.fetcher.load(self.entries,self.parse,validate)
        self.assertTrue(all(x[1]['revision_sha']=='a'*40 for x in results))
