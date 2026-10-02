import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from routing_merge.source_io import SourceFetcher, payload_items, normalize_cidr, previous_counts, validate_rules
from routing_merge.builder import normalize_rule_line, ParsedRule

class SourceValidationTests(unittest.TestCase):
    def test_html_and_behavior_mismatch_fail(self):
        for text, parser in [("<html>error</html>", "domain_payload"), ("payload:\n  - DOMAIN,a.test\n", "domain_payload"), ("payload:\n  - a.test\n", "classical_payload")]:
            with self.subTest(parser=parser), self.assertRaises(ValueError):
                payload_items(text, parser)
    def test_invalid_cidr_and_family_fail(self):
        for value, version in [("999.1.2.3/99", None), ("::/0", 4)]:
            with self.assertRaises(ValueError): normalize_cidr(value, version)
    def test_cache_recovers_only_recent_validated_same_source(self):
        source = {"name": "fixture", "url": "https://example.com/list", "min_rules": 1}
        parse = lambda text: text.splitlines()
        validate = lambda rules: None if rules == ["good"] else (_ for _ in ()).throw(ValueError("bad"))
        with tempfile.TemporaryDirectory() as directory:
            fetcher = SourceFetcher(Path(directory))
            with patch("routing_merge.source_io.download", return_value=("good", {"etag": "one"})):
                self.assertEqual(fetcher.load(source, parse, validate)[1]["fetch_status"], "validated")
            with patch("routing_merge.source_io.download", side_effect=RuntimeError("offline")):
                self.assertEqual(fetcher.load(source, parse, validate)[1]["fetch_status"], "stale")
                path = next(Path(directory).glob("*.json"))
                snapshot=json.loads(path.read_text());snapshot["validated_at"] = time.time()-25*3600;path.write_text(json.dumps(snapshot))
                with self.assertRaises(RuntimeError): fetcher.load(source, parse, validate)
    def test_invalid_download_does_not_poison_snapshot(self):
        source = {"name": "fixture", "url": "https://example.com/list"}
        with tempfile.TemporaryDirectory() as directory:
            fetcher=SourceFetcher(Path(directory));parse=lambda text:[text]
            def validate(rules):
                if rules != ["good"]: raise ValueError("invalid")
            with patch("routing_merge.source_io.download", return_value=("good", {})): fetcher.load(source,parse,validate)
            with patch("routing_merge.source_io.download", return_value=("html", {})):
                rules,meta=fetcher.load(source,parse,validate)
            self.assertEqual(rules,["good"]);self.assertEqual(meta["fetch_status"],"stale")
            self.assertEqual(json.loads(next(Path(directory).glob("*.json")).read_text())["text"],"good")
    def test_keywords_suffixes_and_processes_retain_separate_semantics(self):
        from routing_merge.builder import dedupe_rules, prune_shadowed_rules
        rules=[ParsedRule(t,"onedrive","fixture","top-proxy",1) for t in ["DOMAIN-SUFFIX","DOMAIN-KEYWORD","PROCESS-NAME"]]
        self.assertEqual(len(prune_shadowed_rules(dedupe_rules(rules))),3)
    def test_process_case_is_not_silently_merged(self):
        from routing_merge.builder import dedupe_rules
        rules=[ParsedRule("PROCESS-NAME",v,"fixture","proxy",1) for v in ["OneDrive","onedrive"]]
        self.assertEqual(len(dedupe_rules(rules)),2)

    def test_build_pipeline_preserves_real_collision_types(self):
        from routing_merge.builder import build_sections, render_expanded_rules_yaml
        config={"source_order":["top-proxy","top-direct","proxy"],"sources":[
            {"name":"onedrive","section":"top-proxy","parser":"inline","rules":["DOMAIN-KEYWORD,onedrive","PROCESS-NAME,OneDrive"]},
            {"name":"microsoft","section":"top-direct","parser":"inline","rules":["DOMAIN-SUFFIX,microsoft","DOMAIN-KEYWORD,microsoft"]},
            {"name":"google","section":"proxy","parser":"inline","rules":["DOMAIN-SUFFIX,google","DOMAIN-KEYWORD,google"]}]}
        sections,_=build_sections(config)
        text=render_expanded_rules_yaml(sections)
        for expected in ["PROCESS-NAME,OneDrive,PROXY","DOMAIN-KEYWORD,onedrive,PROXY","DOMAIN-KEYWORD,microsoft,DIRECT","DOMAIN-SUFFIX,microsoft,DIRECT","DOMAIN-KEYWORD,google,PROXY","DOMAIN-SUFFIX,google,PROXY"]:
            self.assertIn(expected,text)
    def test_count_growth_and_critical_types_are_checked(self):
        rules=[ParsedRule("DOMAIN-SUFFIX","example.com","a","proxy",1)]
        for source,previous in [({"name":"a","min_rules":2},None),({"name":"a","required_types":["IP-CIDR"]},None),({"name":"a","required_rules":["DOMAIN-SUFFIX,critical.test"]},None),({"name":"a"},10)]:
            with self.assertRaises(RuntimeError): validate_rules(source,rules,previous)
        with self.assertRaises(RuntimeError):validate_rules({"name":"a","max_growth_ratio":0.1},rules*3,1)
