"""Build the 诗词库 supplement: characters the poems need beyond the 3500-character 楷书 library.

Same source (Make Me a Hanzi graphics) and the same median -> brush keyframe conversion as
tools/build_glyph_library.py, stored separately so the 3500 library and its version stay
unchanged. Only data/calligraphy/poems/poems.json characters missing from 楷书 are built.

    python tools/build_glyph_supplement.py --graphics ../maobi/chinese_caligraphy_robot/graphics.txt
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
from build_glyph_library import choreography  # noqa: E402
from calligraphy import glyph_store  # noqa: E402

OUT = ROOT / 'data/calligraphy/poems'


def needed():
    poems = json.loads((OUT / 'poems.json').read_text(encoding='utf-8'))['items']
    known = set(glyph_store.manifest('kai')['characters'])
    return ''.join(sorted({c for p in poems for c in ''.join(p['lines']) if c not in known}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--graphics', type=Path, required=True)
    args = ap.parse_args()
    chars = needed(); records = {}
    with args.graphics.open(encoding='utf-8') as source:
        for line in source:
            item = json.loads(line); ch = item['character']
            if ch in chars and ch not in records:
                if not item['medians'] or len(item['medians']) != len(item['strokes']):
                    raise ValueError(ch)
                records[ch] = dict(character=ch, strokes=[choreography(m) for m in item['medians']])
    missing = ''.join(c for c in chars if c not in records)
    if missing:
        raise SystemExit('字形源中没有：' + missing + '（请从诗词库中去掉用到这些字的诗）')
    notice = ('Derived from Make Me a Hanzi / Arphic (C) 1999 Arphic Technology. Modified 2026-10-26: '
              'poem supplement glyphs converted with the same medians-to-brush-keyframes method as the 3500 library; '
              'stroke order preserved. Glyph data under Arphic Public License; see ../APL-English.txt.')
    for value in records.values():
        value['source_notice'] = notice
    raw = ''.join(json.dumps(records[c], ensure_ascii=False, separators=(',', ':')) + '\n' for c in chars)
    meta = dict(schema='brush-glyphs-v1', version='poem-supplement-20261026-' + hashlib.sha256(raw.encode()).hexdigest()[:12],
                count=len(chars), characters=chars, content_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                source='https://github.com/skishore/makemeahanzi', source_notice=notice,
                source_sha256=hashlib.sha256(args.graphics.read_bytes()).hexdigest(),
                coordinates='50-unit XY-down', selection='诗词库所需、3500 字楷书库未收录的字')
    db = OUT / 'supplement.sqlite'; tmp = OUT / 'supplement.build.sqlite'
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(str(tmp))
    with con:
        con.execute('CREATE TABLE glyphs (character TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        con.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        con.executemany('INSERT INTO glyphs VALUES (?,?)',
                        [(c, json.dumps(records[c], ensure_ascii=False, separators=(',', ':'))) for c in chars])
        con.execute('INSERT INTO metadata VALUES (?,?)', ('manifest', json.dumps(meta, ensure_ascii=False)))
    con.close()
    tmp.replace(db)
    print(len(chars), chars, meta['version'])


if __name__ == '__main__':
    main()
