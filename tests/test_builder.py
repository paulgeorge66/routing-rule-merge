import unittest

from routing_merge.builder import (
    ParsedRule,
    dedupe_rules,
    normalize_rule_line,
    prune_shadowed_rules,
    render_domain_behavior_text,
    render_expanded_rules_yaml,
    render_ipcidr_behavior_text,
    render_text,
    split_rules_by_behavior,
)


class BuilderTests(unittest.TestCase):
    def test_normalize_cidr_adds_no_resolve(self):
        rule = normalize_rule_line("1.2.3.0/24", "test", "proxy", 1)
        self.assertEqual(rule, ParsedRule("IP-CIDR", "1.2.3.0/24", "test", "proxy", 1, True))

    def test_normalize_explicit_rule_keeps_no_resolve(self):
        rule = normalize_rule_line("IP-CIDR,10.0.0.0/8,no-resolve", "test", "direct", 1)
        self.assertEqual(rule.render(), "IP-CIDR,10.0.0.0/8,no-resolve")

    def test_dedupe_prefers_more_specific_rule_type(self):
        suffix = ParsedRule("DOMAIN-SUFFIX", "example.com", "a", "direct", 1)
        exact = ParsedRule("DOMAIN", "example.com", "b", "direct", 2)
        self.assertEqual(dedupe_rules([suffix, exact])[0].rule_type, "DOMAIN")

    def test_prune_removes_domain_shadowed_by_suffix_baseline(self):
        baseline = [ParsedRule("DOMAIN-SUFFIX", "example.com", "a", "top-proxy", 1)]
        rules = [ParsedRule("DOMAIN", "api.example.com", "b", "direct", 2)]
        self.assertEqual(prune_shadowed_rules(rules, baseline), [])

    def test_render_text_uses_two_part_rule_provider_format(self):
        text = render_text(
            [
                ParsedRule("DOMAIN-SUFFIX", "example.com", "a", "proxy", 1),
                ParsedRule("IP-CIDR", "1.2.3.0/24", "b", "proxy", 2, True),
            ]
        )
        self.assertEqual(text, "DOMAIN-SUFFIX,example.com\nIP-CIDR,1.2.3.0/24,no-resolve\n")

    def test_render_expanded_rules_yaml_uses_worker_order(self):
        sections = {
            "top-proxy": [ParsedRule("DOMAIN-SUFFIX", "proxy.example.com", "a", "top-proxy", 1)],
            "top-direct": [ParsedRule("DOMAIN-SUFFIX", "direct.example.com", "b", "top-direct", 2)],
            "direct": [ParsedRule("IP-CIDR", "10.0.0.0/8", "c", "direct", 3, True)],
            "proxy": [],
        }
        text = render_expanded_rules_yaml(sections)

        self.assertEqual(
            text,
            "  - DOMAIN-SUFFIX,proxy.example.com,PROXY\n"
            "  - DOMAIN-SUFFIX,direct.example.com,DIRECT\n"
            "  - IP-CIDR,10.0.0.0/8,DIRECT,no-resolve\n"
            "  - MATCH,PROXY\n",
        )

    def test_split_rules_by_behavior_groups_by_type(self):
        rules = [
            ParsedRule("DOMAIN-SUFFIX", "example.com", "a", "direct", 1),
            ParsedRule("DOMAIN", "api.example.com", "b", "direct", 2),
            ParsedRule("IP-CIDR", "1.2.3.0/24", "c", "direct", 3, True),
            ParsedRule("IP-CIDR6", "::1/128", "d", "direct", 4, True),
            ParsedRule("PROCESS-NAME", "curl", "e", "direct", 5),
        ]
        domains, cidrs, misc = split_rules_by_behavior(rules)
        self.assertEqual([r.value for r in domains], ["example.com", "api.example.com"])
        self.assertEqual([r.value for r in cidrs], ["1.2.3.0/24", "::1/128"])
        self.assertEqual([r.value for r in misc], ["curl"])

    def test_render_domain_behavior_text_uses_plus_prefix_for_suffix(self):
        text = render_domain_behavior_text(
            [
                ParsedRule("DOMAIN-SUFFIX", "example.com", "a", "direct", 1),
                ParsedRule("DOMAIN", "exact.example.com", "b", "direct", 2),
            ]
        )
        self.assertEqual(text, "+.example.com\nexact.example.com\n")

    def test_render_ipcidr_behavior_text_drops_no_resolve_suffix(self):
        text = render_ipcidr_behavior_text(
            [
                ParsedRule("IP-CIDR", "10.0.0.0/8", "a", "direct", 1, True),
                ParsedRule("IP-CIDR6", "fc00::/7", "b", "direct", 2, True),
            ]
        )
        self.assertEqual(text, "10.0.0.0/8\nfc00::/7\n")


if __name__ == "__main__":
    unittest.main()
