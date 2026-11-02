"""Verify immutable delivery files; logs and local calibration remain separate."""
import argparse
import hashlib
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def verify(root=ROOT):
    root = Path(root).resolve()
    manifest = json.loads((root / 'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    if manifest.get('schema') != 'so101-delivery-v1' or not manifest.get('files'):
        raise ValueError('Invalid package manifest')
    for rel, digest in manifest['files'].items():
        path = (root / rel).resolve()
        if root not in path.parents or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('PACKAGE_VERIFY_FAIL ' + rel)
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=ROOT)
    a = p.parse_args()
    doc = verify(a.root)
    print('PACKAGE_VERIFY_PASS files=' + str(len(doc['files'])))


if __name__ == '__main__':
    main()
