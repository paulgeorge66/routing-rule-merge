"""Validate generated artifacts and the pinned Mihomo core before publication."""
from __future__ import annotations
import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
import tempfile
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
LIMITS = {"reject-domains.mrs": 4_000_000, "direct-domains.mrs": 2_000_000, "proxy-domains.mrs": 1_000_000}


def validate_artifacts(dist: Path) -> dict:
    artifacts = {}
    for path in sorted(dist.iterdir()):
        if path.suffix not in {".list", ".yaml", ".mrs"}:
            continue
        data = path.read_bytes()
        limit = LIMITS.get(path.name, 25_000_000 if path.suffix == ".yaml" else 20_000_000 if path.name in {"reject.list", "direct-domains.list"} else 5_000_000 if path.name.startswith("reject-with-action") else 500_000 if path.suffix == ".mrs" or "misc" in path.name or path.name.startswith(("top-", "apple-")) else 10_000_000)
        if len(data) > limit:
            raise RuntimeError(f"{path.name} exceeds consumer limit {limit}")
        if path.suffix != ".mrs":
            text = data.decode("utf-8")
            if "\r" in text or (text and not text.endswith("\n")):
                raise ValueError(f"{path.name} must use complete LF lines")
            lines = text.splitlines()
            if len(lines) != len(set(lines)):
                raise ValueError(f"{path.name} contains duplicate rules")
            if path.suffix == ".yaml":
                dns = path.name == "proxy-dns-domains.yaml"
                prefix = "      - " if dns else "  - "
                if not lines or any(not line.startswith(prefix) for line in lines):
                    raise ValueError(f"invalid fragment: {path.name}")
                values = yaml.safe_load(("domain:\n" if dns else "rules:\n") + text)
                if not all(isinstance(rule, str) for rule in next(iter(values.values()))):
                    raise ValueError("fragment entries must be strings")
                matches = [line for line in lines if line.startswith("  - MATCH,")]
                if path.name == "routing-expanded-rules.yaml":
                    if matches != ["  - MATCH,PROXY"] or lines[-1] != matches[0]:
                        raise ValueError("invalid final MATCH")
                elif matches:
                    raise ValueError("stream fragments must not contain MATCH")
            if path.name.endswith("expanded.yaml") or path.name == "routing-expanded-fragment.yaml":
                for line in lines:
                    parts = line[4:].split(",")
                    if len(parts) < 3 or parts[2] not in {"PROXY", "DIRECT", "REJECT"}:
                        raise ValueError("invalid expanded rule action")
        artifacts[path.name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "rules": None if path.suffix == ".mrs" else len(data.splitlines())}
    return artifacts


def validate_core(core: Path, dist: Path) -> None:
    providers = {}
    rules = []
    for path in sorted(dist.glob("*.list")):
        if path.name.startswith("reject-with-action") or path.name in {"reject.list", "apple-direct.list"}:
            continue
        behavior = "domain" if "domains" in path.stem else "ipcidr" if "cidr" in path.stem else "classical"
        artifact = path.with_suffix(".mrs") if behavior != "classical" else path
        if not artifact.exists():
            raise RuntimeError(f"missing binary {artifact.name}")
        if behavior != "classical":
            # Roundtrip verifies convert-ruleset did not silently skip invalid entries.
            with tempfile.TemporaryDirectory(dir=ROOT / ".cache") as directory:
                decoded = Path(directory) / "roundtrip.list"
                result = subprocess.run([str(core), "convert-ruleset", behavior, "mrs", str(artifact), str(decoded)], capture_output=True, text=True, timeout=90)
                if result.returncode != 0 or any(word in (result.stdout+result.stderr).lower() for word in ("invalid", "unsupported", "error")):
                    raise RuntimeError("MRS roundtrip failed: " + result.stdout + result.stderr)
                original = {line for line in path.read_text().splitlines() if line}
                roundtrip = {line for line in decoded.read_text().splitlines() if line and not line.startswith("#")}
                if behavior == "ipcidr":
                    def coverage(lines):
                        networks = [ipaddress.ip_network(line, strict=False) for line in lines]
                        return {str(network) for family in (4, 6) for network in ipaddress.collapse_addresses([n for n in networks if n.version == family])}
                    original, roundtrip = coverage(original), coverage(roundtrip)
                if original != roundtrip:
                    raise RuntimeError(f"MRS conversion changed {path.name}")
        providers[path.stem] = {"type": "file", "behavior": behavior, "format": "mrs" if artifact.suffix == ".mrs" else "text", "path": str(artifact)}
        rules.append(f"RULE-SET,{path.stem},DIRECT")
    rules.append("MATCH,DIRECT")
    config = {"mode": "rule", "rules": rules, "rule-providers": providers, "dns": {"enable": False}}
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    check = cache / "core-check.yaml"
    check.write_text(yaml.safe_dump(config, sort_keys=False))
    result = subprocess.run([str(core), "-t", "-d", str(ROOT), "-f", str(check)], capture_output=True, text=True, timeout=120)
    if result.returncode != 0 or "invalid" in (result.stdout + result.stderr).lower():
        raise RuntimeError("Mihomo config check failed: " + result.stdout + result.stderr)
    print(result.stdout.strip())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", type=Path, required=True)
    args = parser.parse_args()
    dist = ROOT / "dist"
    (ROOT / ".cache").mkdir(exist_ok=True)
    artifacts = validate_artifacts(dist)
    validate_core(args.core.resolve(), dist.resolve())
    report = json.loads((dist / "build-report.json").read_text())
    report["validation"] = {"mihomo": "v1.19.29", "artifacts": "passed", "core": "passed"}
    (dist / "build-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    manifest = {"schema": 1, "artifacts": artifacts, "degraded": any(source.get("fetch_status") == "stale" for source in report["sources"].values())}
    (dist / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Validated {len(artifacts)} artifacts and wrote manifest")

if __name__ == "__main__":
    main()
