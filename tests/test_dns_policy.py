import tempfile
import unittest
from pathlib import Path

import yaml

from routing_merge.builder import (
    ParsedRule, build_sections, dns_inline_providers, render_dns_providers_fragment,
    validate_behavior_checks,
)


class DnsPolicyTests(unittest.TestCase):
    def test_proxy_scope_guard_stops_new_keyword_process_or_asn_rules(self):
        for rule in ['DOMAIN-KEYWORD,shared','PROCESS-NAME,TV','IP-ASN,12345']:
            config={'source_order':['proxy'], 'forbid_proxy_types':['DOMAIN-KEYWORD','PROCESS-NAME','IP-ASN'],
                    'sources':[{'name':'future','section':'proxy','parser':'inline','rules':[rule]}]}
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(RuntimeError,'proxy scope guard'):
                    build_sections(config,cache_dir=Path(tmp))

    def test_mixed_upstream_keeps_only_specific_overseas_services_in_proxy(self):
        config = {
            'source_order': ['apple-proxy', 'apple-direct'],
            'sources': [{
                'name':'mixed', 'section':'apple-direct', 'parser':'inline', 'min_rules':4,
                'rules':['DOMAIN-SUFFIX,cdn-apple.com','DOMAIN-SUFFIX,apple.news',
                         'DOMAIN-KEYWORD,1drv','PROCESS-NAME,TV'],
                'exclude_types':['DOMAIN-KEYWORD','PROCESS-NAME'],
                'section_overrides':{'DOMAIN-SUFFIX,apple.news':'apple-proxy'},
            }],
            'behavior_checks':[
                {'domain':'updates.cdn-apple.com','action':'DIRECT'},
                {'domain':'apple.news','action':'PROXY'},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            sections, report = build_sections(config, cache_dir=Path(tmp))
        self.assertEqual(report['sources']['mixed']['parsed_rules'],4)
        self.assertEqual(report['sources']['mixed']['excluded_rules'],2)
        self.assertEqual(report['sources']['mixed']['routed_sections'],{'apple-direct':1,'apple-proxy':1})
        self.assertEqual(len(validate_behavior_checks(config,sections)),2)

    def test_exact_exclusion_does_not_remove_other_vendor_services(self):
        config={'source_order':['top-proxy'], 'sources':[{
            'name':'vendor','section':'top-proxy','parser':'inline',
            'rules':['DOMAIN-SUFFIX,sharepoint.com','DOMAIN-SUFFIX,onedrive.live.com'],
            'exclude_rules':['DOMAIN-SUFFIX,sharepoint.com'],
        }]}
        with tempfile.TemporaryDirectory() as tmp:
            sections, _ = build_sections(config,cache_dir=Path(tmp))
        self.assertEqual([r.render() for r in sections['top-proxy']],['DOMAIN-SUFFIX,onedrive.live.com'])

    def test_invalid_override_cannot_silently_drop_or_redirect_rules(self):
        config={'source_order':['direct'], 'sources':[{
            'name':'vendor','section':'direct','parser':'inline',
            'rules':['DOMAIN,example.com'],
            'section_overrides':{'DOMAIN,example.com':'typo'},
        }]}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'invalid section override'):
                build_sections(config,cache_dir=Path(tmp))

    def test_dns_fragment_preserves_scope_regex_and_order_without_process_or_ip_rules(self):
        sections={
            'top-proxy':[ParsedRule('DOMAIN-REGEX',r'^service-\S+\.example$', 'a','top-proxy',1)],
            'top-direct':[ParsedRule('DOMAIN-SUFFIX','example','b','top-direct',2)],
            'apple-direct':[
                ParsedRule('DOMAIN','exact.test','c','apple-direct',3),
                ParsedRule('DOMAIN-SUFFIX','suffix.test','c','apple-direct',3),
                ParsedRule('DOMAIN-KEYWORD','apple.edgekey','c','apple-direct',3),
                ParsedRule('PROCESS-NAME','TV','c','apple-direct',3),
                ParsedRule('IP-CIDR','17.0.0.0/8','c','apple-direct',3),
            ],
        }
        providers=dns_inline_providers(sections)
        restored=yaml.safe_load('rule-providers:\n'+render_dns_providers_fragment(providers))['rule-providers']
        self.assertEqual(providers,restored)
        self.assertEqual(list(restored)[:2],['dns-routing-top-proxy','dns-routing-top-direct'])
        self.assertEqual(restored['dns-routing-apple-direct-domains']['payload'],['exact.test','+.suffix.test'])
        self.assertEqual(restored['dns-routing-apple-direct-misc']['payload'],['DOMAIN-KEYWORD,apple.edgekey'])
        self.assertEqual(restored['dns-routing-top-proxy']['payload'],[r'DOMAIN-REGEX,^service-\S+\.example$'])


if __name__=='__main__': unittest.main()
