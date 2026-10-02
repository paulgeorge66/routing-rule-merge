"""Diagnostic only: retain REJECT priority and do not invent an allowlist."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from .builder import ROOT, SECTION_ACTION
from .source_io import download

BASE = 'https://raw.githubusercontent.com/paulgeorge66/adblock-rule-merge/main/dist/'

def overlaps(dist: Path, reject: str) -> list[dict]:
    suffixes = set()
    exact = set()
    keywords = []
    for line in reject.splitlines():
        parts = line.split(',')
        if len(parts) < 2: continue
        kind, value = parts[:2]
        if kind == 'DOMAIN-SUFFIX': suffixes.add(value)
        elif kind == 'DOMAIN': exact.add(value)
        elif kind == 'DOMAIN-KEYWORD': keywords.append(value)
    rows = []
    for section, action in SECTION_ACTION.items():
        path = dist / f'{section}.list'
        if path.exists():
            lines = path.read_text().splitlines()
        else:
            lines = [(f'DOMAIN-SUFFIX,{line[2:]}' if line.startswith('+.') else f'DOMAIN,{line}') for line in (dist / f'{section}-domains.list').read_text().splitlines()]
        for line in lines:
            parts = line.split(',')
            if parts[0] not in {'DOMAIN', 'DOMAIN-SUFFIX'}: continue
            value = parts[1]; labels = value.split('.')
            parent = next((s for i in range(len(labels)) if (s := '.'.join(labels[i:])) in suffixes), None)
            matched = f'DOMAIN-SUFFIX,{parent}' if parent else f'DOMAIN,{value}' if parts[0] == 'DOMAIN' and value in exact else next((f'DOMAIN-KEYWORD,{k}' for k in keywords if k in value), None)
            if matched:
                rows.append({'section': section, 'routing_rule': line, 'routing_action': action, 'reject_rule': matched, 'effective_action': 'REJECT'})
    return rows

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--adblock-dir',type=Path);args=parser.parse_args()
    dist=ROOT/'dist'
    try:
        manifest=json.loads((args.adblock_dir/'manifest.json').read_text() if args.adblock_dir else download(BASE+'manifest.json',limit=100_000)[0])
        text=(args.adblock_dir/'reject.list').read_text() if args.adblock_dir else download(BASE+'reject.list')[0]
        artifact=manifest['artifacts']['reject.list']
        if len(text.encode()) != artifact['bytes'] or hashlib.sha256(text.encode()).hexdigest() != artifact['sha256']:
            raise ValueError('adblock snapshot changed during inspection')
        rows=overlaps(dist,text)
        report={'status':'verified','adblock_sha256':artifact['sha256'],'overlaps':len(rows),'top_override_overlaps':sum(r['section'].startswith('top-') for r in rows),'policy':'REJECT remains first; diagnostic does not add exceptions'}
        with (dist/'adblock-overlap.csv').open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=['section','routing_rule','routing_action','reject_rule','effective_action']);writer.writeheader();writer.writerows(rows)
    except Exception:
        # An optional diagnostic outage must not hold validated routing updates hostage.
        report={'status':'unavailable','policy':'REJECT remains first; overlap not reverified'}
        (dist/'adblock-overlap.csv').unlink(missing_ok=True)
    (dist/'adblock-overlap.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))

if __name__=='__main__':main()
