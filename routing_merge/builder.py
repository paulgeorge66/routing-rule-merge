from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCES = ROOT / "sources.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "dist"
DEFAULT_REPORT = DEFAULT_OUTPUT_DIR / "build-report.json"
DEFAULT_EXPANDED_RULES = DEFAULT_OUTPUT_DIR / "routing-expanded-rules.yaml"

CIDR_V4_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+/\d+$")
CIDR_V6_RE = re.compile(r"^[0-9a-fA-F:]+/\d+$")

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

# These two sections are large enough (tens to hundreds of thousands of rules)
# that mihomo's linear "classical" rule-provider scan becomes a real per-connection
# cost. Splitting them by rule type lets mihomo use its trie-based "domain" and
# "ipcidr" rule-provider behaviors instead. The remaining sections stay well under
# a thousand rules each, so a single classical file is not worth the extra files.
SPLIT_BEHAVIOR_SECTIONS = {"direct", "proxy"}
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


def fetch_text(url: str, retries: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "routing-rule-merge/0.1 (+https://github.com/paulgeorge66/routing-rule-merge)",
                    "Connection": "close",
                },
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            if attempt == retries:
                break
            time.sleep(attempt)
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if curl:
        try:
            curl_command = [curl, "-L", "--fail", "--retry", "3", "--retry-delay", "2", url]
            if os.name == "nt":
                curl_command.insert(1, "--ssl-no-revoke")
            result = subprocess.run(
                curl_command,
                check=True,
                capture_output=True,
                timeout=90,
            )
            return result.stdout.decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def load_sources(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ValueError(f"{path} must contain sources")
    if not isinstance(data.get("source_order"), list):
        raise ValueError(f"{path} must contain source_order")
    return data


def load_previous_source_counts(report_path: Path) -> dict[str, int]:
    if not report_path.exists():
        return {}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return {
            name: int(details["parsed_rules"])
            for name, details in report.get("sources", {}).items()
            if isinstance(details, dict) and isinstance(details.get("parsed_rules"), int)
        }
    except (OSError, ValueError, TypeError):
        return {}


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
    payload: list[str] = []
    in_payload = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if not in_payload:
            if stripped == "payload:":
                in_payload = True
                continue
            payload.append(_unquote(stripped))
            continue
        if stripped.startswith("- "):
            payload.append(_unquote(stripped[2:].strip()))
    return payload


def _unquote(item: str) -> str:
    if (item.startswith("'") and item.endswith("'")) or (item.startswith('"') and item.endswith('"')):
        return item[1:-1]
    return item


def normalize_rule_line(item: str, source: str, section: str, source_index: int) -> ParsedRule | None:
    item = item.strip()
    if not item or item.startswith(("#", "!", "[")):
        return None
    if item.startswith("+."):
        return ParsedRule("DOMAIN-SUFFIX", item[2:].strip(), source, section, source_index)
    if CIDR_V4_RE.match(item):
        return ParsedRule("IP-CIDR", item, source, section, source_index, True)
    if CIDR_V6_RE.match(item):
        return ParsedRule("IP-CIDR6", item, source, section, source_index, True)

    parts = [part.strip() for part in item.split(",") if part.strip()]
    if not parts:
        return None
    rule_type = parts[0].upper()
    if len(parts) == 1:
        return ParsedRule("DOMAIN-SUFFIX", parts[0], source, section, source_index)
    value = parts[1]
    no_resolve = any(part == "no-resolve" for part in parts[2:])
    if rule_type in TYPE_ORDER:
        if rule_type in {"IP-CIDR", "IP-CIDR6"}:
            no_resolve = True if no_resolve or len(parts) == 2 else no_resolve
        return ParsedRule(rule_type, value, source, section, source_index, no_resolve)
    return None


def parse_source(source: dict, source_index: int) -> list[ParsedRule]:
    parser = source.get("parser")
    section = source["section"]
    name = source["name"]
    if parser == "inline":
        items = source.get("rules", [])
    else:
        try:
            text = fetch_text(source["url"])
        except Exception as exc:
            raise RuntimeError(f"failed to fetch source {name}: {source['url']}") from exc
        items = extract_payload_lines(text)

    rules: list[ParsedRule] = []
    for item in items:
        rule = normalize_rule_line(str(item), name, section, source_index)
        if rule is not None:
            rules.append(rule)
    return rules


def better_rule(candidate: ParsedRule, current: ParsedRule) -> bool:
    if candidate.section != current.section:
        return SECTION_PRIORITY.get(candidate.section, 0) > SECTION_PRIORITY.get(current.section, 0)
    candidate_score = (TYPE_PRIORITY.get(candidate.rule_type, 0), -candidate.source_index)
    current_score = (TYPE_PRIORITY.get(current.rule_type, 0), -current.source_index)
    return candidate_score > current_score


def dedupe_rules(rules: Iterable[ParsedRule]) -> list[ParsedRule]:
    by_exact: dict[tuple[str, str], ParsedRule] = {}
    for rule in rules:
        key = (rule.rule_type, rule.value.lower())
        current = by_exact.get(key)
        if current is None or better_rule(rule, current):
            by_exact[key] = rule

    by_value: dict[str, ParsedRule] = {}
    for rule in by_exact.values():
        key = rule.value.lower()
        current = by_value.get(key)
        if current is None or better_rule(rule, current):
            by_value[key] = rule

    return sorted(
        by_value.values(),
        key=lambda rule: (
            TYPE_ORDER.get(rule.rule_type, 99),
            rule.value.lower(),
        ),
    )


def prune_shadowed_rules_with_stats(
    rules: Iterable[ParsedRule],
    baseline_rules: Iterable[ParsedRule] | None = None,
) -> tuple[list[ParsedRule], dict[str, int]]:
    baseline = list(baseline_rules or [])
    current = list(rules)
    reference = current + baseline
    baseline_exact = {(rule.rule_type, rule.value.lower()): rule for rule in baseline}
    suffix_rules = {
        rule.value.lower(): rule
        for rule in reversed(reference)
        if rule.rule_type == "DOMAIN-SUFFIX"
    }
    pruned: list[ParsedRule] = []
    stats = {"same_action": 0, "opposite_action": 0}

    for rule in current:
        value = rule.value.lower()
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
) -> tuple[dict[str, list[ParsedRule]], dict]:
    section_order = config["source_order"]
    by_section: dict[str, list[ParsedRule]] = {section: [] for section in section_order}
    source_report: dict[str, dict] = {}
    previous_source_counts = previous_source_counts or {}

    for index, source in enumerate(config["sources"], start=1):
        parsed = parse_source(source, index)
        validate_source_count(source, len(parsed), previous_source_counts.get(source["name"]))
        by_section[source["section"]].extend(parsed)
        source_report[source["name"]] = {
            "section": source["section"],
            "parser": source["parser"],
            "url": source.get("url"),
            "parsed_rules": len(parsed),
        }

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
    args = parser.parse_args(argv)

    config = load_sources(args.sources)
    previous_source_counts = load_previous_source_counts(args.report)
    sections, report = build_sections(config, previous_source_counts)
    write_outputs(sections, report, args.output_dir, args.report, args.expanded_rules)
    print(f"Wrote {args.output_dir}")
    print(f"Wrote {args.report}")
    print(f"Total rules: {report['total_rules']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
