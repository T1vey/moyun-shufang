"""名帖 / 诗词指令库 (2026-10-27): frozen brush plans kept on the SD card.

One entry per piece of writing: a masterpiece column (key mp_<work>, index = column)
a poem segment (key poem_<id>_p<page>, index = segment) a hard-pen piece (key hp_<digest>),
a couplet sheet (key cp_<id>, index = page) or a photo drawing (key ph_<digest of its strokes>). It holds the frozen plan
document and its execution nodes, exactly what a real-mode plan job holds in memory
(artifact.freeze). Writing the same piece again reads these instead of planning.

An entry is used only while the machine configuration digest and the piece's
revision (calibration binding, brush profile, glyph, layout and library versions) both
still match, and it passes the same artifact.check_frozen test as a fresh plan.
Any calibration change makes it stale; it is then planned again and replaced.
"""
import gzip
import json
import re
import time
from pathlib import Path

from .artifact import atomic_write, check_frozen
from .config import digest

SCHEMA = 'tcb705-masterpiece-store-v1'
KEY = re.compile(r'^(mp|poem|hp|cp|ph)_[a-z0-9_]{1,40}$')


def entry(root, key, index):
    if not KEY.match(str(key)) or type(index) is not int or not 0 <= index < 100:
        raise ValueError('指令库条目无效')
    return Path(root) / key / ('part_%d' % index)


def _write(path, value):
    atomic_write(path, gzip.compress(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode(), 6))


def _read(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()).decode('utf-8'))


def save(root, key, index, doc, nodes, revision, info=None):
    folder = entry(root, key, index)
    folder.mkdir(parents=True, exist_ok=True)
    meta = dict(schema=SCHEMA, key=key, index=index, revision=revision, config_digest=doc['config_digest'],
                nodes=len(nodes['positions_m']), duration_s=doc['metrics'].get('duration_s'),
                saved=time.strftime('%Y-%m-%d %H:%M:%S'))
    if info:
        meta['info'] = info                            # what this is, for lists on the screen
    atomic_write(folder / 'meta.json', b'{}')          # an interrupted save leaves an entry that never matches
    _write(folder / 'plan.json.gz', doc)
    _write(folder / 'nodes.json.gz', nodes)
    atomic_write(folder / 'meta.json', json.dumps(meta, ensure_ascii=False, indent=1).encode())
    return meta


def meta(root, key, index):
    try:
        return json.loads((entry(root, key, index) / 'meta.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def fresh(root, key, index, machine, revision):
    m = meta(root, key, index)
    return m.get('schema') == SCHEMA and m.get('revision') == revision and m.get('config_digest') == digest(machine)


def load(root, key, index, machine, revision):
    """(doc, nodes) when the entry matches the current machine and revision, else None."""
    if not fresh(root, key, index, machine, revision):
        return None
    folder = entry(root, key, index)
    try:
        doc, nodes = _read(folder / 'plan.json.gz'), _read(folder / 'nodes.json.gz')
        check_frozen(doc, nodes, machine)
    except (OSError, EOFError, ValueError, KeyError, TypeError):
        return None
    return doc, nodes
