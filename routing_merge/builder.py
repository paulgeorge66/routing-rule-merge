from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from .source_io import SourceFetcher, normalize_domain, normalize_cidr, payload_items, previous_counts, validate_rules
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCES = ROOT / "sources.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "dist"
DEFAULT_REPORT = DEFAULT_OUTPUT_DIR / "build-report.json"
DEFAULT_EXPANDED_RULES = DEFAULT_OUTPUT_DIR / "routing-expanded-rules.yaml"

TYPE_ORDER = {
    "DOMAIN": 1,
    "DOMAIN-SUFFIX": 2,
    "DOMAIN-KEYWORD": 3,
    "PROCESS-NAME": 4,
    "IP-ASN": 5,
    "IP-CIDR": 6,
    "IP-CIDR6": 7,
}
TYPE_PRIORITY = {
    "DOMAIN-SUFFIX": 7,
    "DOMAIN": 6,
    "DOMAIN-KEYWORD": 5,
    "PROCESS-NAME": 4,
    "IP-ASN": 3,
    "IP-CIDR": 2,
    "IP-CIDR6": 2,
}
SECTION_PRIORITY = {
    "top-proxy": 60,
    "top-direct": 60,
    "apple-proxy": 50,
    "apple-direct": 50,
    "proxy": 40,
    "direct": 30,
}
SECTION_ACTION = {
    "top-proxy": "PROXY",
    "top-direct": "DIRECT",
    "apple-proxy": "PROXY",
    "apple-direct": "DIRECT",
    "proxy": "PROXY",
    "direct": "DIRECT",
}

# Compile large general sections and the complete Apple domain collection to MRS.
SPLIT_BEHAVIOR_SECTIONS = {"direct", "proxy", "apple-direct"}
DOMAIN_TYPES = {"DOMAIN", "DOMAIN-SUFFIX"}
CIDR_TYPES = {"IP-CIDR", "IP-CIDR6"}


@dataclass(frozen=True)
class ParsedRule:
    rule_type: str
    value: str
    source: str
    section: str
    source_index: int
    no_resolve: bool = False

    def render(self) -> str:
        base = f"{self.rule_type},{self.value}"
        if self.no_resolve and self.rule_type in {"IP-CIDR", "IP-CIDR6"}:
            return f"{base},no-resolve"
        return base


def load_sources(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ValueError(f"{path} must contain sources")
    if not isinstance(data.get("source_order"), list):
        raise ValueError(f"{path} must contain source_order")
    return data


def validate_source_count(source: dict, parsed_count: int, previous_count: int | None = None) -> None:
    name = source["name"]
    min_rules = int(source.get("min_rules", 1))
    if parsed_count < min_rules:
        raise RuntimeError(f"source {name} produced {parsed_count} rules; minimum is {min_rules}")

    if previous_count is None or previous_count <= 0:
        return
    max_drop_ratio = float(source.get("max_drop_ratio", 0.35))
    if not 0 <= max_drop_ratio < 1:
        raise ValueError(f"source {name} max_drop_ratio must be between 0 and 1")
    minimum_from_previous = math.ceil(previous_count * (1 - max_drop_ratio))
    if parsed_count < minimum_from_previous:
        raise RuntimeError(
            f"source {name} dropped from {previous_count} to {parsed_count} rules; "
            f"maximum allowed drop is {max_drop_ratio:.0%}"
        )


def extract_payload_lines(text: str) -> list[str]:
    return payload_items(text, "auto")


def normalize_rule_line(item: str, source: str, section: str, source_index: int) -> ParsedRule | None:
    item = item.strip()
    if not item or item.startswith(("#", "!", "[")):
        return None
    if item.startswith("+."):
        return ParsedRule("DOMAIN-SUFFIX", normalize_domain(item[2:]), source, section, source_index)
    if "/" in item and "," not in item:
        cidr = normalize_cidr(item)
        return ParsedRule("IP-CIDR6" if ":" in cidr else "IP-CIDR", cidr, source, section, source_index, True)
    parts = [part.strip() for part in item.split(",")]
    if len(parts) == 1:
        return ParsedRule("DOMAIN-SUFFIX", normalize_domain(parts[0]), source, section, source_index)
    rule_type, value = parts[:2]
    rule_type = rule_type.upper()
    if rule_type not in TYPE_ORDER or not value or any(p not in {"no-resolve"} for p in parts[2:]):
        raise ValueError("unsupported or malformed classical rule")
    if rule_type in DOMAIN_TYPES:
        value = normalize_domain(value)
    elif rule_type in CIDR_TYPES:
        value = normalize_cidr(value, 4 if rule_type == "IP-CIDR" else 6)
    elif rule_type == "IP-ASN":
        if not value.isdigit() or not 0 < int(value) <= 4294967295:
            raise ValueError("invalid ASN")
    elif any(c in value for c in ("\r", "\n", ",", chr(34), chr(39))):
        raise ValueError("invalid rule value")
    elif rule_type == "DOMAIN-KEYWORD":
        value = value.lower()
    return ParsedRule(rule_type, value, source, section, source_index, rule_type in CIDR_TYPES)


def parse_source(source: dict, source_index: int, fetcher=None, previous=None) -> tuple[list[ParsedRule], dict]:
    def parse(text):
        items = payload_items(text, source.get("parser", "auto"))
        return [r for item in items if (r := normalize_rule_line(item, source["name"], source["section"], source_index)) is not None]
    def validate(rules):
        validate_rules(source, rules, previous)
    if source.get("parser") == "inline":
        rules = [normalize_rule_line(item, source["name"], source["section"], source_index) for item in source["rules"]]
        validate(rules)
        return rules, {"fetch_status": "inline"}
    fetcher = fetcher or SourceFetcher(ROOT / ".cache" / "sources")
    return fetcher.load(source, parse, validate)


def better_rule(candidate: ParsedRule, current: ParsedRule) -> bool:
    if candidate.section != current.section:
        return SECTION_PRIORITY.get(candidate.section, 0) > SECTION_PRIORITY.get(current.section, 0)
    candidate_score = (TYPE_PRIORITY.get(candidate.rule_type, 0), -candidate.source_index)
    current_score = (TYPE_PRIORITY.get(current.rule_type, 0), -current.source_index)
    return candidate_score > current_score


def dedupe_rules(rules: Iterable[ParsedRule]) -> list[ParsedRule]:
    by_exact: dict[tuple[str, str], ParsedRule] = {}
    for rule in rules:
        key = (rule.rule_type, rule.value if rule.rule_type == "PROCESS-NAME" else rule.value.lower())
        current = by_exact.get(key)
        if current is None or better_rule(rule, current):
            by_exact[key] = rule

    # Different rule types have different match semantics; never merge by value alone.
    return sorted(by_exact.values(), key=lambda rule: (TYPE_ORDER.get(rule.rule_type, 99), rule.value.lower(), rule.value))


def prune_shadowed_rules_with_stats(
    rules: Iterable[ParsedRule],
    baseline_rules: Iterable[ParsedRule] | None = None,
) -> tuple[list[ParsedRule], dict[str, int]]:
    baseline = list(baseline_rules or [])
    current = list(rules)
    reference = current + baseline
    baseline_exact = {(rule.rule_type, rule.value if rule.rule_type == "PROCESS-NAME" else rule.value.lower()): rule for rule in baseline}
    suffix_rules = {
        rule.value.lower(): rule
        for rule in reversed(reference)
        if rule.rule_type == "DOMAIN-SUFFIX"
    }
    pruned: list[ParsedRule] = []
    stats = {"same_action": 0, "opposite_action": 0}

    for rule in current:
        value = rule.value if rule.rule_type == "PROCESS-NAME" else rule.value.lower()
        shadower = baseline_exact.get((rule.rule_type, value))
        if shadower is None and rule.rule_type == "DOMAIN":
            labels = value.split(".")
            shadower = next(
                (suffix_rules[suffix] for index in range(len(labels)) if (suffix := ".".join(labels[index:])) in suffix_rules),
                None,
            )
        if shadower is None and rule.rule_type == "DOMAIN-SUFFIX":
            labels = value.split(".")
            shadower = next(
                (suffix_rules[suffix] for index in range(1, len(labels)) if (suffix := ".".join(labels[index:])) in suffix_rules),
                None,
            )
        if shadower is not None:
            key = (
                "same_action"
                if SECTION_ACTION.get(rule.section) == SECTION_ACTION.get(shadower.section)
                else "opposite_action"
            )
            stats[key] += 1
            continue
        pruned.append(rule)
    return pruned, stats


def prune_shadowed_rules(rules: Iterable[ParsedRule], baseline_rules: Iterable[ParsedRule] | None = None) -> list[ParsedRule]:
    pruned, _ = prune_shadowed_rules_with_stats(rules, baseline_rules)
    return pruned


def build_sections(
    config: dict,
    previous_source_counts: dict[str, int] | None = None,
    cache_dir: Path | None = None,
) -> tuple[dict[str, list[ParsedRule]], dict]:
    section_order = config["source_order"]
    by_section: dict[str, list[ParsedRule]] = {section: [] for section in section_order}
    source_report: dict[str, dict] = {}
    previous_source_counts = previous_source_counts or {}

    fetcher = SourceFetcher(cache_dir or ROOT / ".cache" / "sources")
    def load(index_source):
        index, source = index_source
        return parse_source(source, index, fetcher, previous_source_counts.get(source["name"]))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(load, enumerate(config["sources"], start=1)))
    # Merge in configured order, independent of download completion order.
    for source, (parsed, metadata) in zip(config["sources"], results):
        by_section[source["section"]].extend(parsed)
        source_report[source["name"]] = {"section": source["section"], "parser": source["parser"], "url": source.get("url"), "parsed_rules": len(parsed), **metadata}

    rendered_sections: dict[str, list[ParsedRule]] = {}
    cumulative: list[ParsedRule] = []
    section_report: dict[str, dict] = {}
    for section in section_order:
        deduped = dedupe_rules(by_section[section])
        pruned, shadowed = prune_shadowed_rules_with_stats(deduped, baseline_rules=cumulative)
        rendered_sections[section] = pruned
        cumulative.extend(pruned)
        section_report[section] = {
            "input_rules": len(by_section[section]),
            "deduped_rules": len(deduped),
            "output_rules": len(pruned),
            "shadowed_rules": shadowed,
        }

    report = {
        "sources": source_report,
        "sections": section_report,
        "total_rules": sum(len(rules) for rules in rendered_sections.values()),
    }
    return rendered_sections, report


def render_text(rules: Iterable[ParsedRule]) -> str:
    lines = [rule.render() for rule in rules]
    return "\n".join(lines) + ("\n" if lines else "")


def split_rules_by_behavior(
    rules: Iterable[ParsedRule],
) -> tuple[list[ParsedRule], list[ParsedRule], list[ParsedRule]]:
    domains: list[ParsedRule] = []
    cidrs: list[ParsedRule] = []
    misc: list[ParsedRule] = []
    for rule in rules:
        if rule.rule_type in DOMAIN_TYPES:
            domains.append(rule)
        elif rule.rule_type in CIDR_TYPES:
            cidrs.append(rule)
        else:
            misc.append(rule)
    return domains, cidrs, misc


def render_domain_behavior_text(rules: Iterable[ParsedRule]) -> str:
    lines = []
    for rule in rules:
        if rule.rule_type == "DOMAIN-SUFFIX":
            lines.append(f"+.{rule.value}")
        else:
            lines.append(rule.value)
    return "\n".join(lines) + ("\n" if lines else "")


def render_ipcidr_behavior_text(rules: Iterable[ParsedRule]) -> str:
    lines = [rule.value for rule in rules]
    return "\n".join(lines) + ("\n" if lines else "")


def render_expanded_rule(raw_line: str, action: str) -> str | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    parts = [part.strip() for part in line.split(",") if part.strip()]
    if len(parts) < 2:
        return None
    no_resolve = "no-resolve" in parts[2:]
    rule = f"{parts[0]},{parts[1]},{action}"
    if no_resolve and parts[0] in {"IP-CIDR", "IP-CIDR6"}:
        return f"{rule},no-resolve"
    return rule


def render_expanded_rules_yaml(sections: dict[str, list[ParsedRule]]) -> str:
    lines: list[str] = []
    seen: set[str] = set()

    def add_rule(rule: str | None) -> None:
        if not rule or rule in seen:
            return
        seen.add(rule)
        lines.append(f"  - {rule}")

    for section, action in [
        ("top-proxy", "PROXY"),
        ("top-direct", "DIRECT"),
        ("apple-proxy", "PROXY"),
        ("apple-direct", "DIRECT"),
        ("direct", "DIRECT"),
        ("proxy", "PROXY"),
    ]:
        for rule in sections.get(section, []):
            add_rule(render_expanded_rule(rule.render(), action))

    add_rule("MATCH,PROXY")
    return "\n".join(lines) + "\n"


def write_outputs(
    sections: dict[str, list[ParsedRule]],
    report: dict,
    output_dir: Path,
    report_path: Path,
    expanded_rules_path: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    behavior_report: dict[str, dict] = {}
    for section, rules in sections.items():
        if section not in SPLIT_BEHAVIOR_SECTIONS:
            (output_dir / f"{section}.list").write_text(render_text(rules), encoding="utf-8", newline="\n")
            continue

        if section == "apple-direct":
            (output_dir / "apple-direct.list").write_text(render_text(rules), encoding="utf-8", newline="\n")
        domains, cidrs, misc = split_rules_by_behavior(rules)
        (output_dir / f"{section}-domains.list").write_text(
            render_domain_behavior_text(domains), encoding="utf-8", newline="\n"
        )
        (output_dir / f"{section}-cidr.list").write_text(
            render_ipcidr_behavior_text(cidrs), encoding="utf-8", newline="\n"
        )
        (output_dir / f"{section}-misc.list").write_text(
            render_text(misc), encoding="utf-8", newline="\n"
        )
        behavior_report[section] = {
            "domains": len(domains),
            "cidr": len(cidrs),
            "misc": len(misc),
        }
    if behavior_report:
        report["behavior_split"] = behavior_report
    expanded_rules_text = render_expanded_rules_yaml(sections)
    expanded_rules_path.write_text(expanded_rules_text, encoding="utf-8", newline="\n")
    (output_dir / "routing-expanded-fragment.yaml").write_text(expanded_rules_text.removesuffix("  - MATCH,PROXY\n"), encoding="utf-8", newline="\n")
    dns_rules = [rule for section in ("top-proxy", "apple-proxy", "proxy") for rule in sections.get(section, []) if rule.rule_type in DOMAIN_TYPES]
    dns_lines = render_domain_behavior_text(prune_shadowed_rules(dedupe_rules(dns_rules))).splitlines()
    (output_dir / "proxy-dns-domains.yaml").write_text("".join(f"      - {item}\n" for item in dns_lines), encoding="utf-8", newline="\n")
    report["expanded_rules"] = {
        "path": str(expanded_rules_path.relative_to(ROOT)),
        "rules": expanded_rules_text.count("\n"),
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build non-ad routing rule-provider lists.")
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--expanded-rules", type=Path, default=DEFAULT_EXPANDED_RULES)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".cache" / "sources")
    args = parser.parse_args(argv)

    config = load_sources(args.sources)
    previous_source_counts = previous_counts(args.report, config["sources"])
    sections, report = build_sections(config, previous_source_counts, args.cache_dir)
    write_outputs(sections, report, args.output_dir, args.report, args.expanded_rules)
    print(f"Wrote {args.output_dir}")
    print(f"Wrote {args.report}")
    print(f"Total rules: {report['total_rules']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
