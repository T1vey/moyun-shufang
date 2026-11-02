"""Rebuild runtime SQLite from versioned JSONL without a network or robot."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

def main():
    root = Path(__file__).resolve().parents[1] / 'data/calligraphy'
    metadata = json.loads((root / 'manifest.json').read_text(encoding='utf-8-sig'))
    records = [json.loads(line) for line in (root / 'glyphs.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    keys = [r['character'] for r in records]
    if len(records) != metadata['count'] or len(set(keys)) != len(keys):
        raise ValueError('Glyph count or uniqueness mismatch')
    target = root / 'glyphs.sqlite'
    temporary = root / 'glyphs.sqlite.tmp'
    if temporary.exists():
        temporary.unlink()
    try:
        with closing(sqlite3.connect(temporary)) as db:
            with db:
                db.execute('CREATE TABLE glyphs(character TEXT PRIMARY KEY,payload TEXT NOT NULL)')
                db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
                db.executemany('INSERT INTO glyphs VALUES (?,?)', [(r['character'], json.dumps(r, ensure_ascii=False, separators=(',', ':'))) for r in records])
                db.execute('INSERT INTO metadata VALUES (?,?)', ('manifest', json.dumps(metadata, ensure_ascii=False)))
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(json.dumps({'status': 'PASS', 'glyphs': len(records), 'database': str(target)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
