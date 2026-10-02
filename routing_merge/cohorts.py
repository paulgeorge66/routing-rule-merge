"""Pin GitHub files to one revision and fall back to a complete validated cohort."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit, quote

from .source_io import download


def github_group(url: str) -> tuple[str, str, str] | None:
    parsed = urlsplit(url)
    parts = parsed.path.strip('/').split('/')
    if parsed.scheme == 'https' and parsed.netloc == 'raw.githubusercontent.com' and len(parts) >= 4:
        return tuple(parts[:3])
    return None


class CohortFetcher:
    def __init__(self, cache_dir: Path, max_age: int = 86400):
        self.cache_dir, self.max_age = Path(cache_dir), max_age

    def load(self, entries, parse, validate):
        group = github_group(entries[0][1]['url'])
        identity = '/'.join(group)
        path = self.cache_dir / (hashlib.sha256(identity.encode()).hexdigest()+'.json')
        cached = None
        try:
            candidate = json.loads(path.read_text())
            if candidate['identity'] != identity or not re.fullmatch(r'[a-f0-9]{40}', candidate['revision_sha']):
                raise ValueError('invalid cohort identity')
            if not isinstance(candidate['validated_at'], (int, float)):
                raise ValueError('invalid cohort timestamp')
            for _, source in entries:
                item = candidate['files'][source['url']]
                if hashlib.sha256(item['text'].encode()).hexdigest() != item['sha256']:
                    raise ValueError('invalid cohort integrity')
                if len(item['text'].encode()) > int(source.get('max_bytes', 20_000_000)):
                    raise ValueError('cohort exceeds source limit')
            cached = candidate
        except (OSError, ValueError, KeyError, TypeError):
            pass

        def parse_cohort(snapshot, status):
            results = []
            for index, source in entries:
                item = snapshot['files'][source['url']]
                rules = parse(source, index, item['text'])
                validate(source, rules)
                parts = source['url'].split('/')
                resolved = '/'.join(parts[:5]+[snapshot['revision_sha']]+parts[6:])
                results.append((rules, {'fetch_status':status, 'revision_sha':snapshot['revision_sha'], 'resolved_url':resolved, 'content_sha256':item['sha256'], 'snapshot_validated_at':snapshot['validated_at']}))
            return results

        try:
            owner, repo, ref = group
            metadata, _ = download(f'https://api.github.com/repos/{owner}/{repo}/commits/{quote(ref, safe="")}', limit=1_000_000)
            sha = json.loads(metadata)['sha']
            if not isinstance(sha, str) or not re.fullmatch(r'[a-f0-9]{40}', sha):
                raise ValueError('invalid upstream revision')
            if cached and sha == cached['revision_sha']:
                snapshot = {**cached, 'validated_at':time.time()}
                results = parse_cohort(snapshot, 'not_modified')
            else:
                def fetch(entry):
                    index, source = entry
                    parts = source['url'].split('/')
                    resolved = '/'.join(parts[:5]+[sha]+parts[6:])
                    old = cached['files'].get(source['url']) if cached else None
                    headers = {'If-None-Match':old['etag']} if old and old.get('etag') else {}
                    text, metadata = download(resolved, headers, int(source.get('max_bytes',20_000_000)))
                    if text is None:
                        if old is None:
                            raise ValueError('304 without a validated file')
                        text, metadata = old['text'], {'etag':old.get('etag')}
                    return source['url'], {'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest(),**metadata}
                # Complete the cohort in memory; no partial new revision replaces the old one.
                with ThreadPoolExecutor(max_workers=4) as pool:
                    files = dict(pool.map(fetch, entries))
                snapshot = {'identity':identity, 'revision_sha':sha, 'validated_at':time.time(), 'files':files}
                results = parse_cohort(snapshot, 'validated')
            self.cache_dir.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.cache_dir,delete=False) as tmp:
                json.dump(snapshot,tmp,ensure_ascii=False)
                temporary = tmp.name
            os.replace(temporary,path)
            return results
        except Exception as exc:
            if cached and 0 <= time.time()-cached['validated_at'] <= self.max_age:
                return parse_cohort(cached, 'stale')
            raise RuntimeError(f'upstream {identity} unavailable and no complete recent validated cohort') from exc
