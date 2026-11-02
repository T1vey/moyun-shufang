"""Build the 硬笔正楷 (hard-pen regular script) glyph library (build machine only).

Source: makemeahanzi graphics.txt (楷体 outlines + stroke medians in standard order and
direction). A hard pen draws a line of almost constant width, so regular script is carried
by the path itself (docs/TCB705_硬笔书法模式实施方案_20261027.pdf, chapter 2):

  * strokes are classified (点 横 竖 撇 捺 提 折 钩, 竖 as 垂露 or 悬针) from the median;
  * the whole character is sheared so 横 rise ~3.5 deg to the right while 竖 stay vertical
    and every crossing keeps its place;
  * 起笔: a short press-in tick from the upper left (a corner, so the planner pauses there);
  * 收笔: 横/竖(垂露)/点 end on a small press-and-stop; 撇/提/钩/捺/悬针 lift while moving
    (press ramps to zero, feed rises) to leave a sharp tail;
  * 捺 ends with a flat 捺脚 to the right.

Keyframes are [x, y, press 0..1, feed 0..1] in the 50-unit cell (Y down), the format of
the other libraries; press x the hard-pen press limit gives the pen depth.

  python tools/build_hardpen_glyphs.py --chars 永中国 --review out.png
  python tools/build_hardpen_glyphs.py --test100 --out data/calligraphy/hardpen --review review.png
"""
import argparse
import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
GRAPHICS = ROOT.parent / 'maobi/chinese_caligraphy_robot/graphics.txt'
OUT = ROOT / 'data/calligraphy/hardpen'
UNIT = 50.0 / 1024                     # source em (1024, y up, baseline 900) -> 50-unit cell, y down
SHEAR_DEG = 3.5                        # 横画左低右高
TICK = 1.4                             # 起笔 press-in tick length (units; 0.28 mm at 1 cm)
PRESS = 0.8                            # writing press (fraction of the hard-pen press limit)
FEED = 0.85                            # writing feed
VERSION = 'hardpen-kai-20261027-v1'

# 100 test characters: 永字八法 first, then every stroke family and common structures.
TEST100 = ('永一二三十大小中人入八水火木林日月明山川口田目心必我你他学生书法字文天地春夏秋冬'
           '风花雨江河海云白鸟飞来去上下左右东西南北前后家和年好爱光美长门问马鱼龙之也乎于'
           '为成乐九力刀万千子女手又王主方道德经典诗词')


# ---------------------------------------------------------------- source

def load(chars):
    want = set(chars); out = {}
    with GRAPHICS.open(encoding='utf-8') as f:
        for line in f:
            item = json.loads(line)
            if item['character'] in want:
                out[item['character']] = item
    missing = [c for c in chars if c not in out]
    if missing:
        raise ValueError('source has no data for: ' + ''.join(missing))
    return out


def to_cell(p):
    p = np.asarray(p, float)
    return np.c_[p[:, 0] * UNIT, (900 - p[:, 1]) * UNIT]


def outline(path, step=8):
    """SVG path (M/L/Q/Z, source units) -> list of polygons in cell units (for review only)."""
    polys, cur, start = [], [], None
    tokens = re.findall(r'[MLQZ]|-?\d+(?:\.\d+)?', path)
    i = 0; pos = None
    while i < len(tokens):
        t = tokens[i]; i += 1
        if t == 'M':
            if cur: polys.append(cur)
            pos = (float(tokens[i]), float(tokens[i + 1])); i += 2; cur = [pos]; start = pos
        elif t == 'L':
            pos = (float(tokens[i]), float(tokens[i + 1])); i += 2; cur.append(pos)
        elif t == 'Q':
            c = (float(tokens[i]), float(tokens[i + 1])); e = (float(tokens[i + 2]), float(tokens[i + 3])); i += 4
            for u in np.linspace(0, 1, step)[1:]:
                cur.append(((1 - u) ** 2 * pos[0] + 2 * (1 - u) * u * c[0] + u * u * e[0],
                            (1 - u) ** 2 * pos[1] + 2 * (1 - u) * u * c[1] + u * u * e[1]))
            pos = e
        elif t == 'Z':
            if cur: polys.append(cur)
            cur = []; pos = start
    if cur: polys.append(cur)
    return [to_cell(p) for p in polys]


# ---------------------------------------------------------------- geometry

def angle(v):
    return math.degrees(math.atan2(v[1], v[0]))          # y down: 0 right, 90 down


def turn(a, b):
    d = (angle(b) - angle(a) + 180) % 360 - 180
    return abs(d)


def simplify(p, tol=1.0):
    """Douglas-Peucker on a 2-D median: indices of the points that carry the shape."""
    keep = {0, len(p) - 1}; stack = [(0, len(p) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        seg = p[b] - p[a]; L = max(np.hypot(*seg), 1e-9)
        rel = p[a + 1:b] - p[a]
        d = np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / L
        i = int(d.argmax())
        if d[i] > tol:
            keep.add(a + 1 + i); stack += [(a, a + 1 + i), (a + 1 + i, b)]
    return sorted(keep)


def corners(p, limit=45.0, skip=2.5):
    """Indices (into p) of the median's sharp turns (折 / 钩), found on the simplified median so
    small wiggles of the source are ignored. Bends within `skip` units of the start are the
    source font's entry shape, not a 折."""
    idx = simplify(p)
    q = p[idx]
    s = np.r_[0, np.cumsum(np.hypot(*np.diff(q, axis=0).T))]
    out = []
    for j in range(1, len(q) - 1):
        a, b = q[j] - q[j - 1], q[j + 1] - q[j]
        if s[j] < skip or np.hypot(*a) < 1e-6 or np.hypot(*b) < 1e-6:
            continue
        if turn(a, b) > limit:
            out.append(idx[j])
    return out


def trim_entry(m, within=5.0, bend=30.0):
    """Drop the source font's entry serif (a short slanted lead-in before the stroke turns into
    its real direction); the hard-pen 起笔 tick replaces it."""
    idx = simplify(m)
    s = np.r_[0, np.cumsum(np.hypot(*np.diff(m, axis=0).T))]
    for j in range(1, len(idx) - 1):
        i = idx[j]
        if s[i] > within:
            break
        if turn(m[i] - m[idx[j - 1]], m[idx[j + 1]] - m[i]) > bend and s[-1] - s[i] > 2.0:
            return m[i:]
    return m


def catmull(p, step=0.5):
    """Smooth curve through the median points of one corner-free piece."""
    p = np.asarray(p, float)
    if len(p) < 3:
        n = max(2, int(np.hypot(*(p[-1] - p[0])) / step) + 1)
        return np.c_[np.linspace(p[0, 0], p[-1, 0], n), np.linspace(p[0, 1], p[-1, 1], n)]
    q = np.vstack([2 * p[0] - p[1], p, 2 * p[-1] - p[-2]])
    out = [p[0]]
    for i in range(1, len(q) - 2):
        p0, p1, p2, p3 = q[i - 1], q[i], q[i + 1], q[i + 2]
        n = max(2, int(np.hypot(*(p2 - p1)) / step) + 1)
        for t in np.linspace(0, 1, n)[1:]:
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    return np.asarray(out)


def length(p):
    return float(np.hypot(*np.diff(p, axis=0).T).sum()) if len(p) > 1 else 0.0


# ---------------------------------------------------------------- classification

def classify(m, bbox, others=None):
    """Stroke family and ending from the median (cell units, y down).
    Returns (kind, ending): ending 'stop' or 'taper'. others: the character's other medians
    (a 悬针 must hang below all of them)."""
    cs = corners(m)
    L = length(m)
    a = angle(m[-1] - m[0])
    if cs:
        last = m[-1] - m[cs[-1]]
        before = m[cs[-1]] - m[cs[-1] - 1]
        start = m[min(len(m) - 1, max(1, cs[0]))] - m[0]
        first = angle(start)
        head = '横' if -30 <= first <= 30 else '竖' if 55 <= first <= 125 else '撇' if first > 125 or first < -150 else '点'
        tail = angle(last)
        # 钩: a short last piece turning sharply, or any stroke that ends going upwards
        if (np.hypot(*last) < max(6.0, 0.3 * L) and turn(before, last) > 60) or -170 < tail < -80:
            return (head + '钩') if head != '点' else '钩', 'taper'
        if -80 <= tail <= -10:
            return head + '提', 'taper'
        if tail > 135 or tail < -150:
            return head + '撇', 'taper'
        return head + '折', 'stop'
    if L < 6.0:
        return ('提', 'taper') if -80 <= a <= -10 else ('点', 'stop')
    if -30 <= a <= 25:
        return '横', 'stop'
    if 55 <= a <= 105 and not (a < 70 and L > 14.0 and m[-1][0] - m[0][0] > 6.0):
        # 悬针: a long vertical that reaches the bottom of the character
        lowest = max((float(o[:, 1].max()) for o in (others or [])), default=-1e9)
        near = min((float(np.hypot(*(o - m[-1]).T).min()) for o in (others or [])), default=1e9)
        if a >= 70 and m[-1][1] >= lowest + 1.0 and near > 4.0 and L > 0.45 * (bbox[3] - bbox[1]):
            return '悬针竖', 'taper'
        return '竖', 'stop'
    if a > 105 or a < -150:
        return '撇', 'taper'
    if 25 < a < 70:
        return ('捺', 'taper') if L > 14.0 else ('点', 'stop')
    if -80 <= a < -30:
        return '提', 'taper'
    return '点', 'stop'


# ---------------------------------------------------------------- hard-pen stroke

def shear(p, cx=25.0):
    p = np.array(p, float)
    p[:, 1] -= math.tan(math.radians(SHEAR_DEG)) * (p[:, 0] - cx)
    return p


def stroke(m, kind, ending):
    """Median (cell units) -> dense [x, y, press, feed] for a hard pen."""
    cs = corners(m)
    pieces, last = [], 0
    for c in cs + [len(m) - 1]:
        pieces.append(m[last:c + 1]); last = c
    path = [catmull(pieces[0])]
    for piece in pieces[1:]:
        path.append(catmull(piece)[1:])
    xy = np.vstack(path)
    if ending == 'taper' and kind == '捺':                      # 捺脚: flatten out to the right
        xy = np.vstack([xy, xy[-1] + [1.6 * TICK, 0.15 * TICK]])
    n = len(xy)
    press = np.full(n, PRESS); feed = np.full(n, FEED)
    s = np.r_[0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
    if ending == 'taper':                                        # lift while moving: a sharp tail
        tail = 0.3 * s[-1] if kind in ('撇', '提', '捺') else min(3.0, 0.5 * s[-1])
        u = np.clip((s - (s[-1] - tail)) / max(tail, 1e-6), 0, 1)
        press = PRESS * (1 - u ** 1.5); feed = FEED + (1 - FEED) * u
    rows = [np.c_[xy, press, feed]]
    if kind not in ('点', '提', '捺'):                            # 起笔: press in from the upper left
        d = xy[min(3, n - 1)] - xy[0]; d = d / max(np.hypot(*d), 1e-6)
        entry = xy[0] + np.array([-0.7, -0.7]) * TICK if abs(d[0]) >= abs(d[1]) or d[1] > 0 else xy[0] + np.array([0.7, -0.7]) * TICK
        if kind.startswith('撇'):
            entry = xy[0] + np.array([0.6, -0.8]) * TICK
        rows.insert(0, np.array([[entry[0], entry[1], 0.0, 0.5]]))
    else:
        rows.insert(0, np.array([[xy[0, 0], xy[0, 1], 0.0, 0.5]]))
    if ending == 'stop':                                         # 收笔: press and stop
        d = xy[-1] - xy[max(0, n - 4)]; d = d / max(np.hypot(*d), 1e-6)
        if kind == '点':
            stop = xy[-1] - d * 0.35 * TICK                     # 点: turn back a little
        else:
            stop = xy[-1] + np.array([0.35, 0.45]) * TICK       # 横 / 竖 / 折: down-right press
        rows.append(np.array([[stop[0], stop[1], PRESS, 0.4], [stop[0], stop[1], 0.0, 0.4]]))
    else:
        rows[-1][-1, 2] = 0.0
    return np.vstack(rows)


def rdp(p, tol, keep=()):
    out = {0, len(p) - 1} | set(keep)
    stack = [(0, len(p) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        seg = p[b, :2] - p[a, :2]; L = max(np.hypot(*seg), 1e-9)
        rel = p[a + 1:b, :2] - p[a, :2]
        dist = np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / L
        u = np.linspace(0, 1, b - a + 1)[1:-1]
        dz = np.abs(p[a + 1:b, 2] - (p[a, 2] * (1 - u) + p[b, 2] * u))
        df = np.abs(p[a + 1:b, 3] - (p[a, 3] * (1 - u) + p[b, 3] * u))
        err = np.maximum(dist, np.maximum(dz, df) * 2.0)
        i = int(err.argmax())
        if err[i] > tol:
            m = a + 1 + i; out.add(m); stack += [(a, m), (m, b)]
    return p[sorted(out)]


def glyph(item):
    medians = [trim_entry(to_cell(m)) for m in item['medians']]
    allp = np.vstack(medians)
    bbox = (allp[:, 0].min(), allp[:, 1].min(), allp[:, 0].max(), allp[:, 1].max())
    strokes = []
    for i, m in enumerate(medians):
        kind, ending = classify(m, bbox, medians[:i] + medians[i + 1:])
        rows = stroke(m, kind, ending)
        rows[:, :2] = shear(rows[:, :2])
        rows = rdp(rows, 0.03, keep=(1,))
        rows[:, :2] = np.clip(rows[:, :2], 0, 50)
        strokes.append(dict(module='hardpen', kind=kind, ending=ending,
                            points=[[round(float(v), 4) for v in r] for r in rows]))
    return dict(character=item['character'], strokes=strokes, stats=dict(strokes=len(strokes), source='makemeahanzi'))


# ---------------------------------------------------------------- checks

def check(g):
    """Structural checks; returns a list of problems (empty = fine)."""
    out = []
    for i, s in enumerate(g['strokes']):
        p = np.asarray(s['points'])
        if len(p) < 2:
            out.append('stroke %d has one point' % (i + 1))
        if p[0, 2] != 0 or p[-1, 2] != 0:
            out.append('stroke %d does not start and end lifted' % (i + 1))
        if not ((p[:, 2] >= 0) & (p[:, 2] <= 1) & (p[:, 3] > 0) & (p[:, 3] <= 1)).all():
            out.append('stroke %d press/feed out of range' % (i + 1))
        if length(p[:, :2]) < 1.0:
            out.append('stroke %d shorter than 1 unit' % (i + 1))
    return out


# ---------------------------------------------------------------- output

def write(records, out):
    out.mkdir(parents=True, exist_ok=True)
    raw = ''.join(json.dumps(records[k], ensure_ascii=False, separators=(',', ':')) + '\n' for k in sorted(records))
    digest = hashlib.sha256(raw.encode()).hexdigest()
    meta = dict(schema='brush-glyphs-v1', style='hardpen', label='硬笔正楷', kind='hardpen',
                version='%s-%s' % (VERSION, digest[:12]), count=len(records), characters=''.join(sorted(records)),
                source='https://github.com/skishore/makemeahanzi', coordinates='50-unit XY-down',
                shear_deg=SHEAR_DEG, tick_units=TICK, press=PRESS, feed=FEED, content_sha256=digest,
                verification='structural offline; pen test writes pending')
    db, tmp = out / 'glyphs.sqlite', out / 'glyphs.build.sqlite'
    if tmp.exists():
        tmp.unlink()
    with sqlite3.connect(str(tmp)) as con:
        con.execute('CREATE TABLE glyphs (character TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        con.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        con.executemany('INSERT INTO glyphs VALUES (?,?)', [(k, json.dumps(v, ensure_ascii=False, separators=(',', ':'))) for k, v in records.items()])
        con.execute('INSERT INTO metadata VALUES (?,?)', ('manifest', json.dumps(meta, ensure_ascii=False)))
    con.close()
    tmp.replace(db)
    return meta


def review(items, glyphs, path, size_mm=15.0, pen_mm=0.5, per_row=5):
    """Per character: source 楷体 outline | hard pen at size_mm | numbered strokes coloured by kind."""
    import cv2
    from PIL import Image, ImageDraw, ImageFont
    px = 20.0                                   # pixels per mm
    T = int(size_mm * px); k = T / 50.0
    colours = {'点': (200, 120, 0), '横': (0, 90, 200), '竖': (0, 150, 60), '撇': (170, 0, 170), '捺': (200, 0, 0),
               '提': (0, 160, 160), '钩': (120, 80, 0)}
    tiles = []
    for ch in glyphs:
        g = glyphs[ch]
        a = np.full((T, T, 3), 255, np.uint8)
        for poly in outline_all(items[ch]):
            cv2.fillPoly(a, [np.round(shear(poly) * k).astype(np.int32)], (120, 120, 120), cv2.LINE_AA)
        b = np.full((T, T, 3), 255, np.uint8); c = np.full((T, T, 3), 255, np.uint8)
        for i, s in enumerate(g['strokes']):
            p = np.asarray(s['points'])
            dense = []
            for u, v in zip(p, p[1:]):
                n = max(2, int(np.hypot(*(v[:2] - u[:2])) * k / 2))
                for t in np.linspace(0, 1, n):
                    dense.append(u * (1 - t) + v * t)
            dense = np.asarray(dense)
            for u, v in zip(dense, dense[1:]):
                w = pen_mm * px * (0.35 + 0.65 * min(1.0, (u[2] + v[2]) / 2 / PRESS))
                if (u[2] + v[2]) / 2 > 0.02:
                    cv2.line(b, tuple(np.round(u[:2] * k).astype(int)), tuple(np.round(v[:2] * k).astype(int)), (30, 25, 20), max(1, int(round(w))), cv2.LINE_AA)
            col = next((v for key, v in colours.items() if key in s['kind'][-1:] or s['kind'].endswith(key)), (90, 90, 90))
            cv2.polylines(c, [np.round(p[:, :2] * k).astype(np.int32)], False, col, 2, cv2.LINE_AA)
            q = np.round(p[0, :2] * k).astype(int)
            cv2.circle(c, tuple(q), 9, col, -1, cv2.LINE_AA)
            cv2.putText(c, str(i + 1), (q[0] - 5, q[1] + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1, cv2.LINE_AA)
        row = np.hstack([a, np.full((T, 4, 3), 220, np.uint8), b, np.full((T, 4, 3), 220, np.uint8), c])
        head = Image.new('RGB', (row.shape[1], 30), (255, 255, 255)); d = ImageDraw.Draw(head)
        font = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 18)
        d.text((4, 4), '%s  %s' % (ch, ' '.join(s['kind'] for s in g['strokes'])), font=font, fill=(40, 30, 20))
        tile = np.vstack([np.asarray(head)[..., ::-1], row])
        tiles.append(np.pad(tile, ((6, 6), (6, 6), (0, 0)), constant_values=235))
    rows = []
    for i in range(0, len(tiles), per_row):
        part = tiles[i:i + per_row] + [np.full_like(tiles[0], 235)] * (per_row - len(tiles[i:i + per_row]))
        rows.append(np.hstack(part))
    cv2.imencode('.png', np.vstack(rows))[1].tofile(str(path))


def outline_all(item):
    out = []
    for path in item['strokes']:
        out += outline(path)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--chars')
    ap.add_argument('--test100', action='store_true')
    ap.add_argument('--common', action='store_true', help='all characters of the 楷书 library (常用 3500)')
    ap.add_argument('--out', type=Path)
    ap.add_argument('--review', type=Path)
    a = ap.parse_args()
    chars = a.chars or (TEST100 if a.test100 else '')
    if a.common:
        chars = (ROOT / 'data/calligraphy/常用3500字.txt').read_text(encoding='utf-8')
    chars = ''.join(dict.fromkeys(c for c in chars if not c.isspace()))
    items = load(chars)
    glyphs = {c: glyph(items[c]) for c in chars}
    problems = {c: check(g) for c, g in glyphs.items()}
    bad = {c: p for c, p in problems.items() if p}
    print('characters', len(glyphs), 'strokes', sum(len(g['strokes']) for g in glyphs.values()), 'problems', len(bad))
    for c, p in list(bad.items())[:20]:
        print(c, p)
    kinds = {}
    for g in glyphs.values():
        for s in g['strokes']:
            kinds[s['kind']] = kinds.get(s['kind'], 0) + 1
    print('kinds', dict(sorted(kinds.items(), key=lambda kv: -kv[1])))
    if a.out:
        print(write(glyphs, a.out)['version'])
    if a.review:
        review(items, glyphs, a.review)


if __name__ == '__main__':
    main()
