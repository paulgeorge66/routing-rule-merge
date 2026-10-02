"""Bounded public-source downloads and validated last-good snapshots."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml


def normalize_domain(value: str) -> str:
    value = value.strip().strip('.').lower()
    if value.startswith('*.'):
        value = value[2:]
    try:
        value = value.encode('idna').decode('ascii')
    except UnicodeError as exc:
        raise ValueError('invalid domain') from exc
    if not value or len(value) > 253 or any(
        not re.fullmatch(r'[a-z0-9_-]{1,63}', label) for label in value.split('.')
    ):
        raise ValueError('invalid domain')
    return value


def normalize_cidr(value: str, version: int | None = None) -> str:
    network = ipaddress.ip_network(value, strict=False)
    if version is not None and network.version != version:
        raise ValueError('CIDR address family does not match rule type')
    return str(network)


def payload_items(text: str, parser: str) -> list[str]:
    if parser == 'auto':
        if not re.search(r'^payload\s*:', text, re.M):
            return [line.strip() for line in text.splitlines() if line.strip()]
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or not isinstance(data.get('payload'), list):
        raise ValueError('source must contain a YAML payload list')
    if not all(isinstance(item, str) for item in data['payload']):
        raise ValueError('payload entries must be strings')
    items = data['payload']
    for item in items:
        if not item or item.startswith(('#', '!')):
            continue
        if parser == 'classical_payload' and ',' not in item:
            raise ValueError('classical payload contains an untyped rule')
        if parser in {'domain_payload', 'cidr_payload'} and ',' in item:
            raise ValueError('payload does not match declared behavior')
        if parser == 'cidr_payload':
            normalize_cidr(item)
        if parser == 'domain_payload':
            normalize_domain(item[2:] if item.startswith('+.') else item)
    return items


def validate_rules(source: dict, rules: list, previous: int | None = None) -> None:
    count = len(rules)
    minimum = int(source.get('min_rules', 1))
    maximum = int(source.get('max_rules', 1_000_000))
    if count < minimum or count > maximum:
        raise RuntimeError(f"source {source['name']} produced {count} rules; allowed {minimum}..{maximum}")
    if previous:
        drop = float(source.get('max_drop_ratio', 0.35))
        growth = float(source.get('max_growth_ratio', 1.0))
        if not 0 <= drop < 1 or growth < 0:
            raise ValueError('invalid source change thresholds')
        if count < previous * (1 - drop) or count > previous * (1 + growth):
            raise RuntimeError(f"source {source['name']} changed unexpectedly: {previous} -> {count}")
    types = {r.rule_type for r in rules}
    if set(source.get('required_types', [])) - types:
        raise RuntimeError(f"source {source['name']} is missing required rule types")
    rendered = {r.render() for r in rules}
    if set(source.get('required_rules', [])) - rendered:
        raise RuntimeError(f"source {source['name']} is missing required rules")


def download(url: str, headers: dict | None = None, limit: int = 20_000_000) -> tuple[str | None, dict]:
    headers = {'User-Agent': 'public-rule-builder/0.2', **(headers or {})}
    error = None
    for attempt in range(2):
        try:
            started = time.monotonic()
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=15) as response:
                length = response.headers.get('Content-Length')
                if length and int(length) > limit:
                    raise ValueError('source exceeds byte limit')
                chunks = []
                size = 0
                while chunk := response.read(65536):
                    size += len(chunk)
                    if size > limit or time.monotonic() - started > 45:
                        raise ValueError('source exceeded byte or time limit')
                    chunks.append(chunk)
                text = b''.join(chunks).decode('utf-8-sig')
                return text, {'etag': response.headers.get('ETag'), 'last_modified': response.headers.get('Last-Modified')}
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return None, {}
            error = exc
        except ValueError:
            raise
        except Exception as exc:
            error = exc
        if attempt < 1:
            time.sleep(1 + attempt)
    # curl uses the platform certificate store on macOS and remains bounded.
    with tempfile.TemporaryDirectory() as directory:
        body = Path(directory) / 'body'
        response_headers = Path(directory) / 'headers'
        command = ['curl', '--silent', '--show-error', '--location', '--fail', '--connect-timeout', '10', '--max-time', '45', '--max-filesize', str(limit), '--output', str(body), '--dump-header', str(response_headers), '--write-out', '%{http_code}']
        for key, value in headers.items():
            command.extend(['--header', f'{key}: {value}'])
        command.append(url)
        try:
            result = subprocess.run(command, check=True, capture_output=True, timeout=50)
            if result.stdout == b'304':
                return None, {}
            raw = body.read_bytes()
            if len(raw) > limit:
                raise ValueError('source exceeds byte limit')
            pairs = {}
            for line in response_headers.read_text().splitlines():
                if ':' in line:
                    key, value = line.split(':', 1)
                    pairs[key.lower()] = value.strip()
            return raw.decode('utf-8-sig'), {'etag': pairs.get('etag'), 'last_modified': pairs.get('last-modified')}
        except Exception as exc:
            raise RuntimeError('source download failed') from (error or exc)


class SourceFetcher:
    def __init__(self, cache_dir: Path, max_age_hours: int = 24):
        self.cache_dir = cache_dir
        self.max_age = max_age_hours * 3600

    def load(self, source: dict, parser, validator) -> tuple[list, dict]:
        url = source['url']
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache_dir / f'{key}.json'
        cached = None
        try:
            candidate = json.loads(path.read_text())
            cached = candidate if isinstance(candidate, dict) and isinstance(candidate.get("validated_at"), (int, float)) else None
            if cached is None or cached.get('url') != url or hashlib.sha256(cached['text'].encode()).hexdigest() != cached['sha256']:
                cached = None
        except (OSError, ValueError, KeyError, TypeError):
            pass
        conditional = {}
        if cached:
            if cached.get('etag'):
                conditional['If-None-Match'] = cached['etag']
            if cached.get('last_modified'):
                conditional['If-Modified-Since'] = cached['last_modified']
        try:
            text, metadata = download(url, conditional, int(source.get('max_bytes', 20_000_000)))
            if text is None:
                if cached is None:
                    raise RuntimeError('304 without a validated snapshot')
                text = cached['text']
                metadata = {key: cached.get(key) for key in ('etag', 'last_modified')}
            rules = parser(text)
            validator(rules)
            snapshot = {'url': url, 'text': text, 'sha256': hashlib.sha256(text.encode()).hexdigest(), 'validated_at': time.time(), **metadata}
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.cache_dir, delete=False) as temporary:
                json.dump(snapshot, temporary, ensure_ascii=False)
                temp_path = temporary.name
            os.replace(temp_path, path)
            return rules, {'fetch_status': 'validated'}
        except Exception as exc:
            if cached and 0 <= time.time() - cached['validated_at'] <= self.max_age:
                rules = parser(cached['text'])
                validator(rules)
                return rules, {'fetch_status': 'stale', 'snapshot_validated_at': cached['validated_at']}
            raise RuntimeError(f"source {source['name']} unavailable and no recent validated snapshot") from exc


def previous_counts(path: Path, sources: list[dict]) -> dict[str, int]:
    try:
        previous = json.loads(path.read_text()).get('sources', {})
    except (OSError, ValueError):
        return {}
    # A source URL change is an explicit source replacement, not a sudden growth.
    return {s['name']: p['parsed_rules'] for s in sources if isinstance(p := previous.get(s['name']), dict) and isinstance(p.get('parsed_rules'), int) and p.get('url') == s.get('url')}
