"""Check catalogue, source order, hashes and unchanged legacy trajectories offline."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--graphics',type=Path,required=True)
    ap.add_argument('--previous-jsonl',type=Path,required=True)
    ap.add_argument('--report-dir',type=Path,required=True)
    args=ap.parse_args();args.report_dir.mkdir(parents=True,exist_ok=True)
    directory=ROOT/'data/calligraphy'
    old={v['character']:v for v in map(json.loads,args.previous_jsonl.read_text(encoding='utf-8').splitlines())}
    new={v['character']:v for v in map(json.loads,(directory/'glyphs.jsonl').read_text(encoding='utf-8').splitlines())}
    source={}
    with args.graphics.open(encoding='utf-8') as f:
        for line in f:
            v=json.loads(line)
            if v['character'] in new:source[v['character']]=v
    changed=[ch for ch,v in old.items() if ch not in new or new[ch]['strokes']!=v['strokes']]
    if changed:raise ValueError('Legacy geometry changed: '+''.join(changed))
    for ch in new:
        if [s['source_median'] for s in new[ch]['strokes']]!=source[ch]['medians']:
            raise ValueError('Source stroke order changed: '+ch)
    m=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256((directory/'glyphs.jsonl').read_bytes()).hexdigest()!=m['content_sha256']:
        raise ValueError('JSONL content hash mismatch')
    with sqlite3.connect(directory/'glyphs.sqlite') as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database damaged')
        rows=list(c.execute('SELECT character,payload FROM glyphs'))
        if {ch for ch,_ in rows}!=set(m['characters']) or len(new)!=m['count']:raise ValueError('Catalogue mismatch')
        for ch,payload in rows:
            if json.loads(payload)!=new[ch]:raise ValueError('JSONL/database mismatch: '+ch)
    complexity=sorted(new,key=lambda c:(-len(new[c]['strokes']),c))
    added=[ch for ch in m['characters'] if ch not in old]
    sample=''.join(dict.fromkeys(complexity[:12]+added[::max(1,len(added)//24)]+list('机械臂智能科技程序控制墨韵翰蘸赢鹰麟')))
    sample=''.join(ch for ch in sample if ch in new)
    (args.report_dir/'native-sample.txt').write_text(sample,encoding='utf-8')
    report=dict(count=len(new),strokes=sum(len(g['strokes']) for g in new.values()),
                legacy_retained_unchanged=len(old),source_order_and_direction_matches=len(new),missing=0,
                database_bytes=(directory/'glyphs.sqlite').stat().st_size,database_integrity='ok',
                jsonl_and_db_equal=True,native_sample_count=len(sample),version=m['version'],physical_motion=False)
    (args.report_dir/'library-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
