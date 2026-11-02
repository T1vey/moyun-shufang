"""Build the 名帖表演 (masterpiece performance) libraries: one famous sentence per work.

Each character is cut from a scan of the original (tools/masterpiece_crop.py),
cleaned of seals, ruled lines, stains and specks, and traced like the style
libraries (tools/build_style_glyphs.py): one brush path per standard stroke in
standard order and direction, following the master's own centreline and stroke
width. Where the master's ink really runs on from the end of one stroke into the
start of the next (连笔), the two are written as one continuous brush movement;
a stroke is never split. Run from the repository root (build machine only).

  python tools/build_masterpieces.py [--only lanting] [--sr espcn] [--no-refine] [--out DIR]

2026-10-27: the ink edge comes from a x4 super-resolved strip (tools/masterpiece_sr.py)
and every traced path is smoothed, with crossings bridged and true corners kept
(tools/masterpiece_refine.py). --sr none --no-refine reproduces the first build.
--traces DIR takes the hand-traced brush paths with matched press depth
(tools/masterpiece_traces.py output, one <id>.json per work) instead of tracing
the scan; characters without a hand trace keep the automatic path.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools'))
import masterpiece_crop as C
import build_style_glyphs as G
import masterpiece_refine as MR

USER = Path(r'C:\Users\gongj\Desktop\shidamingtie')
DL = ROOT.parent / 'masterpieces_dl'
OUT = ROOT / 'data/calligraphy/masterpieces'
GRAPHICS = ROOT.parent / 'maobi/chinese_caligraphy_robot/graphics.txt'

# sentence: as displayed (simplified); forms: as written in the work (stroke order source).
# parts: (image, box x0,y0,x1,y1, n, cuts or None, crop options); characters in reading order.
WORKS = [
    dict(id='lanting', title='兰亭集序', author='王羲之', dynasty='东晋', script='行书',
         note='唐 冯承素摹 神龙本', sentence='永和九年岁在癸丑', forms='永和九年歲在癸丑',
         source=DL / 'lanting/神龍蘭亭序全.JPG',
         parts=[(None, (23668, 30, 23795, 805), 8, [30, 135, 238, 335, 452, 577, 675, 748, 805], {})]),
    dict(id='jizhi', title='祭侄文稿', author='颜真卿', dynasty='唐', script='行书',
         sentence='父陷子死巢倾卵覆', forms='父陷子死巢傾卵覆',
         source=DL / 'jizhi/祭侄文稿卷.唐.顏真卿.纸本行书.台北故宫博物院藏_(cropped).tif',
         parts=[(None, (6220, 2340, 6730, 2810), 1, None, {}),
                (None, (6220, 3510, 6730, 5540), 4, [3510, 4000, 4475, 4900, 5540], {}),
                (None, (5470, 360, 6030, 2190), 3, [360, 900, 1470, 2190], {})]),
    dict(id='hanshi', title='黄州寒食帖', author='苏轼', dynasty='北宋', script='行书',
         sentence='自我来黄州已过三寒', forms='自我來黃州已過三寒', note='取首句前九字',
         source=USER / '苏轼黄州寒食帖/F29557D76DA0648F383AEE8A2C008F77.jpg',
         parts=[(None, (630, 240, 840, 1670), 9, [240, 395, 565, 725, 910, 1075, 1185, 1365, 1475, 1670], {})]),
    dict(id='shusu', title='蜀素帖', author='米芾', dynasty='北宋', script='行书',
         sentence='青松劲挺姿凌霄耻屈', forms='青松勁挺姿凌霄恥屈', note='取首句前九字',
         source=USER / '米蒂蜀素帖/9A2D2DED56D87DEB58BEC3F38E8C0668.jpg',
         parts=[(None, (496, 435, 606, 1440), 8, [435, 560, 680, 790, 900, 1030, 1150, 1295, 1440], dict(rules=True)),
                (None, (355, 435, 479, 575), 1, [435, 575], dict(rules=True))]),
    dict(id='qianzi', title='楷书千字文', author='赵佶', dynasty='北宋', script='瘦金体',
         sentence='天地玄黄宇宙洪荒', forms='天地元黃宇宙洪荒', note='原迹避讳写作「元」',
         source=USER / '赵佶千字文/6D74C2D705BA3663AA5085DE9F86F2C7.jpg',
         parts=[(None, (608, 415, 724, 1268), 8, [415, 510, 618, 720, 828, 938, 1048, 1158, 1268],
                 dict(scale=3, blur=2.5, holes=700, close=3, factor=1.15, min_frac=0.012))]),
    dict(id='chibi', title='赤壁赋', author='赵孟頫', dynasty='元', script='行书',
         sentence='清风徐来水波不兴', forms='清風徐來水波不興',
         source=USER / '赵孟頫后赤壁赋/4496807F2A581829F363C750A5390E57.jpg',
         parts=[(None, (360, 1445, 478, 1560), 1, None, dict(scale=2, blur=1.5, factor=0.85, holes=300)),
                (None, (198, 330, 330, 1145), 7, [330, 453, 565, 690, 828, 947, 1045, 1145],
                 dict(scale=2, blur=1.5, factor=0.85, holes=300))]),
    dict(id='zhanghan', title='张翰帖', author='欧阳询', dynasty='唐', script='行书',
         sentence='张翰字季鹰吴郡人', forms='張翰字季鷹吳郡人', note='朱晓刚 临本',
         source=USER / '欧阳询/C35099FD1DB243961258DA3D29E90271.jpg',
         parts=[(None, (700, 280, 870, 1422), 8, [280, 428, 575, 728, 862, 1045, 1200, 1330, 1422],
                 dict(scale=2, blur=1.5, factor=0.8, holes=300))]),
]


def crops(work, sr=None):
    out = []
    for k, (image, box, n, cuts, opts) in enumerate(work['parts']):
        if not sr:
            out += C.column(str(image or work['source']), box, n, cuts=cuts, **opts)
            continue
        from masterpiece_sr import strip_path, FACTOR
        path = strip_path(work['id'], k, sr)
        if not path.exists():
            raise ValueError('%s: run tools/masterpiece_sr.py --method %s first' % (work['id'], sr))
        strip = cv2.cvtColor(cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        for item in C.column(str(image or work['source']), box, n, cuts=cuts, offset=True, **opts):
            out.append(None if item is None else
                       MR.sr_glyph(item[0], item[1], opts.get('scale', 1), strip, FACTOR, opts))
    if len(out) != len(work['sentence']) or any(g is None for g in out):
        raise ValueError('%s: crops do not match the sentence' % work['id'])
    return out


def to_cell(glyph):
    """Binary crop -> R x R cell (glyph centred, longest side 94 % of the cell)."""
    g = glyph.astype(np.float32)
    k = 0.94 * G.R / max(g.shape)
    r = cv2.resize(g, (max(1, int(round(g.shape[1] * k))), max(1, int(round(g.shape[0] * k)))), interpolation=cv2.INTER_AREA)
    cell = np.zeros((G.R, G.R), np.float32)
    y, x = (G.R - r.shape[0]) // 2, (G.R - r.shape[1]) // 2
    cell[y:y + r.shape[0], x:x + r.shape[1]] = r
    # Real ink has ragged edges; a smooth outline keeps the centreline free of
    # spurious branches that would otherwise become extra brush landings.
    # The smoothing scales with the stroke width, so thin strokes (瘦金体) are not eroded.
    from stroke_paths import _thin_cpu
    raw = cell > 0.5
    half = float(np.median(cv2.distanceTransform(raw.astype(np.uint8), cv2.DIST_L2, 5)[_thin_cpu(raw)]))
    sigma = float(np.clip(0.45 * half, 0.8, 2.2))
    k = int(np.clip(round(half), 1, 3)) * 2 + 1
    cell = cv2.morphologyEx(raw.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    return cv2.GaussianBlur(cell.astype(np.float32), (0, 0), sigma) > 0.5


def join_connected(paths, ink, dt):
    """连笔: when the master's ink continues from the end of stroke i straight into the
    start of stroke i+1, write them as one brush movement (no lift, no split)."""
    out = [paths[0]]
    for p in paths[1:]:
        a, b = out[-1][-1], p[0]
        gap = float(np.hypot(*(b - a)))
        w = max(float(dt[int(np.clip(a[1], 0, G.R - 1)), int(np.clip(a[0], 0, G.R - 1))]), 2.0)
        inked = all(ink[int(round(a[1] + (b[1] - a[1]) * t)), int(round(a[0] + (b[0] - a[0]) * t))]
                    for t in np.linspace(0, 1, max(3, int(gap))))
        if 1.0 < gap <= 3.0 * w and inked:
            out[-1] = np.vstack([out[-1], p])
        else:
            out.append(p)
    return out


def trace_char(cell, medians, width_ref):
    """Returns (paths, method, stats). Standard strokes first; master's own strokes if
    the standard decomposition cannot be traced one-to-one on this glyph."""
    G._CFG = dict(cursive=False, method='trace', width_ref=width_ref)
    smooth = cv2.GaussianBlur(cell.astype(np.float32), (0, 0), 1.2) > 0.5
    from stroke_paths import _thin_cpu
    skel = _thin_cpu(smooth)
    dt = cv2.distanceTransform(smooth.astype(np.uint8), cv2.DIST_L2, 5)
    ref = [np.array([[x / 1024 * G.R, (900 - y) / 1024 * G.R] for x, y in m], float) for m in medians]
    warped = G.register(ref, skel)
    nodes, edges = G.raw_graph(skel)
    edges = G.clean(nodes, edges, dt)
    method = 'standard'
    paths = []
    for w in warped:
        p = G.trace_stroke(w, skel, smooth)
        if p is None:
            p = G.ink_snap(w, skel)
        if len(p) < 2 or G.length(p) < 1.5:
            v = (w[-1] - w[0]) / max(np.hypot(*(w[-1] - w[0])), 1e-6)
            p = np.vstack([p[0], p[0] + v * 2.0])
        paths.append(p)
    def accepted(lo, hi):
        for p, w in zip(paths, warped):
            Q = np.clip(np.round(G.resample(p, 1.0)).astype(int), 0, G.R - 1)
            if smooth[Q[:, 1], Q[:, 0]].mean() < 0.93 or (G.length(w) > 15 and not lo <= G.length(p) / G.length(w) <= hi):
                return False
        return True
    # Strict match first; a looser length match still beats breaking strokes into pieces.
    ok = accepted(0.3, 3.0)
    if not ok and accepted(0.15, 4.0):
        ok, method = True, 'standard-loose'
    if ok:
        paths, keys = G.complete_strokes(paths, warped, skel, dt, min_len=G.R * 0.12)
        paths = [p for _, p in sorted(zip(keys, paths), key=lambda kp: kp[0])]
    else:
        # The master's own strokes: whole skeleton strokes (never split at crossings),
        # ordered and oriented by the standard stroke each one follows.
        method = 'master'
        pieces = G.label_strokes(G.natural_strokes(edges), warped)
        pieces = sorted(pieces + G.dots(smooth, pieces, warped), key=lambda e: (e['stroke'], (e['t0'] + e['t1']) / 2))
        merged = []
        for e in pieces:
            if G.length(e['pts']) < 2.5:
                continue
            if merged and merged[-1]['stroke'] == e['stroke']:
                last = merged[-1]['pts']
                for cand in (e['pts'], e['pts'][::-1]):
                    if np.hypot(*(cand[0] - last[-1])) <= 4.0:      # same stroke, continuing: one movement
                        merged[-1]['pts'] = np.vstack([last, cand[1:]]); break
                else:
                    merged.append(dict(e))
            else:
                merged.append(dict(e))
        paths = [e['pts'] for e in merged]
    paths = join_connected(paths, smooth, dt)
    reach = np.zeros((G.R, G.R), np.uint8)
    for p in paths:
        for x, y in G.resample(p, 1.5):
            xi, yi = int(np.clip(round(x), 0, G.R - 1)), int(np.clip(round(y), 0, G.R - 1))
            cv2.circle(reach, (xi, yi), int(math.ceil(dt[yi, xi] + 1.5)), 1, -1)
    coverage = float((reach.astype(bool) & smooth).sum() / max(smooth.sum(), 1))
    return paths, dt, dict(method=method, pen_downs=len(paths), standard_strokes=len(medians), coverage=round(coverage, 4))


def medians_for(forms, sentence):
    kai = sqlite3.connect(str(ROOT / 'data/calligraphy/glyphs.sqlite'))
    trad = {}
    with GRAPHICS.open(encoding='utf-8') as f:
        for line in f:
            item = json.loads(line)
            if item['character'] in forms:
                trad[item['character']] = item['medians']
    out = []
    for form, simp in zip(forms, sentence):
        if form in trad:
            out.append((form, trad[form]))
        else:
            row = kai.execute('SELECT payload FROM glyphs WHERE character=?', (simp,)).fetchone()
            if row is None:
                raise ValueError('no stroke order for %s/%s' % (form, simp))
            out.append((simp, [s['source_median'] for s in json.loads(row[0])['strokes']]))
    return out


def traced_strokes(char, size_mm, press_mm):
    """Hand-traced strokes ([x_mm, y_mm, depth_mm] in a size_mm cell) -> keyframes in the 50-unit cell."""
    out = []
    for st in char['strokes']:
        a = np.asarray(st['points_mm'], float)
        pts = np.c_[a[:, :2] * 50.0 / size_mm, np.clip(a[:, 2] / press_mm, 0, 1)]
        pts[0, 2] = pts[-1, 2] = 0.0
        n = len(pts)
        keep = [i for i in (1, 2, n - 3, n - 2) if 0 < i < n - 1]
        pts = G.rdp(pts, 0.04, keep)
        feed = np.clip(0.88 - 0.6 * pts[:, 2], 0.3, 0.9)
        rows = np.c_[np.clip(pts[:, :2], 0, 50), pts[:, 2], feed]
        out.append(dict(module='master', points=[[round(float(v), 6) for v in r] for r in rows]))
    return out


def build(work, sr=None, refine=True, out=None, traces=None):
    traced = {}
    if traces and (Path(traces) / (work['id'] + '.json')).exists():
        doc = json.loads((Path(traces) / (work['id'] + '.json')).read_text(encoding='utf-8'))
        traced = {c['index']: (c, doc['size_mm'], doc['brush']['press_max_mm']) for c in doc['chars'] if c['strokes']}
    glyphs = crops(work, sr)
    folder = (out or OUT) / work['id']
    (folder / 'crops').mkdir(parents=True, exist_ok=True)
    for i, g in enumerate(glyphs):
        cv2.imencode('.png', (~g).astype(np.uint8) * 255)[1].tofile(str(folder / 'crops' / ('%02d.png' % i)))
    cells = [to_cell(g) for g in glyphs]
    vals = []
    from stroke_paths import _thin_cpu
    for c in cells:
        sm = cv2.GaussianBlur(c.astype(np.float32), (0, 0), 1.2) > 0.5
        vals.append(cv2.distanceTransform(sm.astype(np.uint8), cv2.DIST_L2, 5)[_thin_cpu(sm)])
    width_ref = float(np.percentile(np.concatenate(vals), 90))
    records = {}
    for i, ((order_char, med), cell) in enumerate(zip(medians_for(work['forms'], work['sentence']), cells)):
        if i in traced:
            c, size_mm, press_mm = traced[i]
            strokes = traced_strokes(c, size_mm, press_mm)
            stats = dict(method='hand-traced', pen_downs=len(strokes), standard_strokes=len(med), coverage=c['iou'])
            records['#%02d' % i] = dict(character=work['sentence'][i], written=work['forms'][i], order_from=order_char,
                                        strokes=strokes, stats=stats)
            print(work['id'], i, work['sentence'][i], stats, flush=True)
            continue
        paths, dt, stats = trace_char(cell, med, width_ref)
        if refine:
            jm = MR.junctions(dt > 0, dt)
            strokes = [dict(module='master', points=MR.keyframes(*MR.refine(p, dt, jm), width_ref)) for p in paths]
        else:
            strokes = [dict(module='master', points=G.keyframes(p, dt, width_ref)) for p in paths]
        key = '#%02d' % i
        records[key] = dict(character=work['sentence'][i], written=work['forms'][i], order_from=order_char,
                            strokes=strokes, stats=stats)
        print(work['id'], i, work['sentence'][i], stats, flush=True)
    notice = ('%s《%s》（%s）。轨迹为对照高清原作逐笔人工描红，提按按原作墨迹宽度匹配。' if traced else
              '%s《%s》（%s）。轨迹取自原作图像的中线与笔画宽度；笔顺按标准笔顺，连笔按原作墨迹。') % (
        work['author'], work['title'], work.get('note') or work['dynasty'])
    raw = ''.join(json.dumps(records[k], ensure_ascii=False, separators=(',', ':')) + '\n' for k in sorted(records))
    digest = hashlib.sha256(raw.encode()).hexdigest()
    src = Path(work['source'])
    meta = dict(schema='brush-glyphs-v1', style='mp_' + work['id'], label='%s《%s》' % (work['author'], work['title']),
                kind='masterpiece', version='mp-%s-20261027-%s' % (work['id'], digest[:12]), count=len(work['sentence']),
                characters=work['sentence'], written=work['forms'], title=work['title'], author=work['author'],
                dynasty=work['dynasty'], script=work['script'], note=work.get('note', ''), source_notice=notice,
                source_image=src.name, source_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),
                content_sha256=digest, width_reference_px=round(width_ref, 4), raster_px=G.R,
                coordinates='50-unit XY-down', positional=True, order=[w['id'] for w in WORKS].index(work['id']),
                verification='structural offline; physical ink results pending')
    db = folder / 'glyphs.sqlite'; tmp = folder / 'glyphs.build.sqlite'
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', action='append')
    ap.add_argument('--sr', default='edsr', choices=['none', 'bicubic', 'fsrcnn', 'espcn', 'edsr'])
    ap.add_argument('--no-refine', action='store_true')
    ap.add_argument('--out', type=Path)
    ap.add_argument('--traces', type=Path)
    args = ap.parse_args()
    for w in WORKS:
        if not args.only or w['id'] in args.only:
            build(w, None if args.sr == 'none' else args.sr, not args.no_refine, args.out, args.traces)


if __name__ == '__main__':
    main()
