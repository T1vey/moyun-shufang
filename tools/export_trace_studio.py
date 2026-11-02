"""Export the 名帖描红工作台 (tools/trace_studio) with one high-resolution image per character.

Each character is cut as in tools/build_masterpieces.py, its edge taken from the x4
super-resolved strip (tools/masterpiece_sr.py), and placed on a 1024 x 1024 canvas
with the same centring as build_masterpieces.to_cell (longest side 94 %), so a
traced pixel maps to the 50-unit glyph cell as x * 50 / 1024. The original ink
tone is kept inside the ink; paper, seals and neighbours become white. The
current automatic paths (a build output folder) are added as the blue hint.

  python tools/export_trace_studio.py OUT_DIR --sr edsr --auto BUILD_DIR
"""
import argparse
import json
import math
import shutil
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools'))
import build_masterpieces as B
import masterpiece_crop as C
import masterpiece_refine as MR
from masterpiece_sr import strip_path, FACTOR

PX = 1024


def hd_chars(work, sr):
    """[(binary ink, grey tone)] at the super-resolved scale, in sentence order."""
    out = []
    for k, (image, box, n, cuts, opts) in enumerate(work['parts']):
        strip = cv2.cvtColor(cv2.imdecode(np.fromfile(str(strip_path(work['id'], k, sr)), np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        scale = opts.get('scale', 1)
        for g, off in C.column(str(image or work['source']), box, n, cuts=cuts, offset=True, **opts):
            ink = MR.sr_glyph(g, off, scale, strip, FACTOR, opts)
            f = FACTOR / float(scale)
            y0, x0 = int(round(off[0] * f)), int(round(off[1] * f))
            region = strip[y0:y0 + ink.shape[0], x0:x0 + ink.shape[1]]
            out.append((ink, cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)))
    return out


def canvas(ink, grey):
    """Ink tone on white, anti-aliased edge, centred like to_cell on PX x PX."""
    v = grey[ink]
    lo, hi = np.percentile(v, 2), np.percentile(v, 98)
    tone = np.clip((grey.astype(np.float32) - lo) / max(hi - lo, 1.0), 0, 1) * 0.55 + 0.04   # ink 10..150 of 255
    alpha = cv2.GaussianBlur(ink.astype(np.float32), (0, 0), 1.0)
    img = 1.0 - alpha * (1.0 - tone)
    k = 0.94 * PX / max(ink.shape)
    r = cv2.resize(img, (max(1, int(round(ink.shape[1] * k))), max(1, int(round(ink.shape[0] * k)))), interpolation=cv2.INTER_AREA)
    out = np.ones((PX, PX), np.float32)
    y, x = (PX - r.shape[0]) // 2, (PX - r.shape[1]) // 2
    out[y:y + r.shape[0], x:x + r.shape[1]] = r
    return (out * 255).round().astype(np.uint8)


def auto_paths(build_dir, work_id):
    db = Path(build_dir) / work_id / 'glyphs.sqlite'
    with sqlite3.connect(str(db)) as con:
        rows = dict(con.execute('SELECT character, payload FROM glyphs').fetchall())
    out = []
    for key in sorted(rows):
        rec = json.loads(rows[key])
        out.append((rec['stats']['standard_strokes'],
                    [[[round(p[0] * PX / 50, 1), round(p[1] * PX / 50, 1)] for p in s['points']] for s in rec['strokes']]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out', type=Path)
    ap.add_argument('--sr', default='edsr')
    ap.add_argument('--auto', type=Path, required=True)
    args = ap.parse_args()
    out = args.out; (out / 'images').mkdir(parents=True, exist_ok=True); (out / 'annotations').mkdir(exist_ok=True)
    for name in ('server.py', 'index.html'):
        shutil.copy2(ROOT / 'tools/trace_studio' / name, out / name)
    works = []
    for w in B.WORKS:
        folder = '%s_%s' % (w['author'], w['title'])
        (out / 'images' / folder).mkdir(exist_ok=True)
        chars = []
        for i, ((ink, grey), (std, auto)) in enumerate(zip(hd_chars(w, args.sr), auto_paths(args.auto, w['id']))):
            name = 'images/%s/%02d_%s.png' % (folder, i + 1, w['sentence'][i])
            cv2.imencode('.png', canvas(ink, grey))[1].tofile(str(out / name))
            chars.append(dict(index=i, char=w['sentence'][i], written=w['forms'][i], image=name, standard=std, auto=auto,
                              source_px=int(max(ink.shape) / (FACTOR / float(w['parts'][0][4].get('scale', 1))))))
            print(w['id'], i, w['sentence'][i], ink.shape, flush=True)
        works.append(dict(id=w['id'], title=w['title'], author=w['author'], dynasty=w['dynasty'], script=w['script'], chars=chars))
    manifest = dict(schema='trace-studio-v1', canvas_px=PX, cell_units=50, sr=args.sr,
                    mapping='unit = px * 50 / 1024 in build_masterpieces.to_cell geometry', works=works)
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
