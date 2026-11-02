"""Inspect manifest artifact paths/hashes without importing PYNQ."""
import argparse
import hashlib
import json
from pathlib import Path

def audit(manifest):
    base = manifest.parent.resolve()
    obj = json.loads(manifest.read_text(encoding='utf-8-sig'))
    rows = []
    def walk(value, label=''):
        if isinstance(value, dict):
            if label.endswith('/files'):
                for name, expected in value.items():
                    if not isinstance(expected, str) or len(expected) != 64:
                        continue
                    candidate = base / name
                    state = 'MISSING'
                    if candidate.is_file():
                        state = 'PASS' if hashlib.sha256(candidate.read_bytes()).hexdigest() == expected else 'HASH_MISMATCH'
                    rows.append({'field': label + '/' + name, 'file': name, 'status': state})
            path_value = next((value[k] for k in ('path', 'file', 'filename', 'relative_path') if isinstance(value.get(k), str)), None)
            if path_value and not path_value.startswith(('/', 'http:', 'https:')):
                candidate = base / path_value
                if not candidate.exists() and (base / Path(path_value).name).exists():
                    candidate = base / Path(path_value).name
                expected = value.get('sha256')
                state = 'MISSING'
                if candidate.is_file():
                    state = 'PASS' if not expected or hashlib.sha256(candidate.read_bytes()).hexdigest() == expected else 'HASH_MISMATCH'
                rows.append({'field': label, 'file': path_value, 'status': state})
            for k, v in value.items():
                if isinstance(v, (dict, list)):
                    walk(v, label + '/' + k)
                elif isinstance(v, str) and k in ('bit', 'hwh', 'bitfile', 'bitstream', 'registers', 'dtbo'):
                    path = base / v
                    rows.append({'field': label + '/' + k, 'file': v, 'status': 'PRESENT' if path.is_file() else 'MISSING'})
        elif isinstance(value, list):
            for i, item in enumerate(value):
                walk(item, label + '/' + str(i))
    walk(obj)
    failed = any(r['status'] in {'MISSING', 'HASH_MISMATCH'} for r in rows)
    return {'manifest': str(manifest), 'status': 'INCOMPLETE' if failed else ('PASS' if rows else 'NO_ARTIFACT_ENTRIES'), 'artifacts': rows}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    report = audit(args.manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(report['status'] != 'PASS')
