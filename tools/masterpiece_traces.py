"""Hand-traced masterpiece paths -> corrected brush paths with press depth -> simulated writing.

Input: the 名帖描红工作台 folder (tools/export_trace_studio.py), where the user traced
every character stroke by stroke on its 1024 x 1024 high-resolution image.

  1. clean: drop accidental clicks, resample, smooth the hand jitter (true corners kept);
  2. centre: measure the ink cross-section perpendicular to the path on the
     super-resolved ink; pull the path towards the ink centre (smoothly, never at
     crossings where the cross-section belongs to two strokes);
  3. press: ink width -> brush footprint width -> press depth with the brush model
     below; widths at crossings are bridged from both sides. A work whose strokes
     are wider than this brush can make is scaled down as a whole (its 90th
     percentile width -> WIDTH_CAP of the widest footprint), so its thick-thin
     contrast survives instead of every heavy stroke saturating;
  4. simulate: a bundle of hairs follows the path at the footprint width; hairs at
     the edge and late in a long stroke run dry (飞白), and the result is compared
     with the original ink.

The brush model is an estimate until it is checked against real test writes:
footprint width = TIP_MM at first touch, growing linearly to SPLAY x the brush's
maximum diameter at the press limit.

  python tools/masterpiece_traces.py STUDIO_DIR
"""
import argparse
import json
import math
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools'))
import build_masterpieces as B
import masterpiece_refine as MR
import export_trace_studio as E

SIZE_MM = 70.0                 # 名帖表演 character cell (user_gui/workflow.py MASTERPIECE_SIZE_MM)
PX = E.PX                      # 1024 px = 50 units = one SIZE_MM cell
MM = SIZE_MM / PX              # mm per image pixel
BRUSH = dict(hair_mm=12.0, diameter_mm=4.0, press_max_mm=6.0)
TIP_MM = 0.5                   # footprint width when the tip just touches
SPLAY = 1.3                    # pressed hair spreads beyond the dry diameter
STEP = 2.0                     # path sampling (px)
WIDTH_CAP = 0.92               # a work's 90th percentile width -> this share of the widest footprint


def width_of_press(d):
    return TIP_MM + (SPLAY * BRUSH['diameter_mm'] - TIP_MM) * np.clip(d, 0, None) / BRUSH['press_max_mm']


def press_of_width(w):
    return np.clip((w - TIP_MM) / (SPLAY * BRUSH['diameter_mm'] - TIP_MM) * BRUSH['press_max_mm'], 0, BRUSH['press_max_mm'])


# ---------------------------------------------------------------- ink at the studio geometry

def ink_masks(work):
    """Binary ink on the 1024 canvas, same placement as export_trace_studio.canvas."""
    out = []
    for ink, _ in E.hd_chars(work, 'edsr'):
        k = 0.94 * PX / max(ink.shape)
        r = cv2.resize(ink.astype(np.float32), (max(1, int(round(ink.shape[1] * k))), max(1, int(round(ink.shape[0] * k)))),
                       interpolation=cv2.INTER_AREA) > 0.5
        m = np.zeros((PX, PX), bool)
        y, x = (PX - r.shape[0]) // 2, (PX - r.shape[1]) // 2
        m[y:y + r.shape[0], x:x + r.shape[1]] = r
        out.append(m)
    return out


# ---------------------------------------------------------------- per stroke

def resample(p, step):
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(p, axis=0).T))]
    if d[-1] < step:
        return p[[0, -1]] if len(p) > 1 else p
    t = np.linspace(0, d[-1], max(2, int(d[-1] / step) + 1))
    return np.c_[np.interp(t, d, p[:, 0]), np.interp(t, d, p[:, 1])]


def smooth_path(q, lam, inside=None):
    """Whittaker fit split at true corners; ends held."""
    inside = np.zeros(len(q), bool) if inside is None else inside
    cut = [0] + MR.corners(q, inside, reach=8, angle=55.0) + [len(q) - 1]
    out = []
    for a, b in zip(cut, cut[1:]):
        w = np.ones(b - a + 1); w[0] = w[-1] = 50.0
        seg = MR.whittaker(q[a:b + 1], w, lam)
        out.append(seg if not out else seg[1:])
    return np.vstack(out), cut


def cross_section(mask, p, n, reach=160):
    """Ink run through p along the normal n: (left, right) distances in px, or None outside ink."""
    def walk(sign):
        for t in range(0, reach):
            x, y = int(round(p[0] + sign * n[0] * t)), int(round(p[1] + sign * n[1] * t))
            if not (0 <= x < PX and 0 <= y < PX) or not mask[y, x]:
                return t
        return None
    x, y = int(round(p[0])), int(round(p[1]))
    if not (0 <= x < PX and 0 <= y < PX) or not mask[y, x]:
        return None
    a, b = walk(-1), walk(1)
    return None if a is None or b is None else (a, b)


def process_stroke(raw, mask):
    pts = np.asarray([[v[0], v[1]] for v in raw], float)
    length = float(np.hypot(*np.diff(pts, axis=0).T).sum()) if len(pts) > 1 else 0.0
    if len(pts) < 3 or length < 8:
        return None                                   # a click, not a stroke
    q = resample(pts, STEP)
    q, _ = smooth_path(q, lam=40.0)                   # hand jitter (period below ~1 mm)
    # Cross-sections on the original ink.
    t = np.gradient(q, axis=0); t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
    nrm = np.c_[-t[:, 1], t[:, 0]]
    left = np.full(len(q), np.nan); right = np.full(len(q), np.nan)
    for i, (p, n) in enumerate(zip(q, nrm)):
        cs = cross_section(mask, p, n)
        if cs is not None:
            left[i], right[i] = cs
    width = left + right
    ok = np.isfinite(width)
    # Crossings: the section spans two strokes -> far wider than its neighbourhood.
    if ok.sum() >= 5:
        med = np.array([np.nanmedian(width[max(0, i - 12):i + 13]) for i in range(len(q))])
        ok &= width <= 1.6 * med
    inside = ~ok
    # Centre: half the measured offset, smoothed along the stroke, never more than 6 px.
    off = np.where(ok, (right - left) / 2.0, np.nan)
    idx = np.arange(len(q))
    if ok.sum() >= 2:
        off = np.interp(idx, idx[ok], off[ok])
        off = MR.whittaker(off[:, None], np.where(ok, 1.0, 0.05), 200.0)[:, 0]
        shift = np.clip(0.7 * off, -6, 6)
        shift[[0, -1]] = 0
        q = q + nrm * shift[:, None]
        width = np.where(ok, width, np.nan)
        width = np.interp(idx, idx[ok], width[ok])
    else:
        width = np.full(len(q), 4.0 / MM if not ok.any() else np.nanmedian(width))
    # Press changes over several mm in real writing; ripples shorter than ~5 mm are ink
    # texture (飞白), and each one would make the planner stop the brush on the paper.
    w_mm = MR.whittaker((width * MM)[:, None], np.ones(len(q)), 1000.0)[:, 0]
    w_mm = np.maximum(w_mm, 0.0)
    s = np.r_[0, np.cumsum(np.hypot(*np.diff(q, axis=0).T))] * MM
    return dict(points_px=q, width_mm=w_mm, crossing=inside, raw_px=pts, s_mm=s, length_mm=s[-1])


def work_scale(strokes):
    """One factor per work: its 90th percentile ink width -> WIDTH_CAP of the widest footprint."""
    w = np.concatenate([st['width_mm'][~st['crossing']] for st in strokes if (~st['crossing']).any()] or [np.ones(1)])
    return float(min(1.0, WIDTH_CAP * width_of_press(BRUSH['press_max_mm']) / max(np.percentile(w, 90), 1e-6)))


def set_press(st, scale):
    d = press_of_width(st['width_mm'] * scale)
    # Touch down and lift: press ramps over the first / last 1.2 mm of the path.
    s = st['s_mm']; ramp = np.clip(np.minimum(s, s[-1] - s) / 1.2, 0, 1)
    d = d * (0.25 + 0.75 * ramp)
    d[[0, -1]] = 0.0
    st['depth_mm'] = d


# ---------------------------------------------------------------- simulation

def noise(shape, seed, scale):
    rng = np.random.default_rng(seed)
    n = np.zeros(shape, np.float32)
    for octave, amp in ((scale, 1.0), (scale / 2, 0.5), (scale / 4, 0.25)):
        h, w = max(2, int(shape[0] / octave)), max(2, int(shape[1] / octave))
        n += amp * cv2.resize(rng.standard_normal((h, w)).astype(np.float32), (shape[1], shape[0]), interpolation=cv2.INTER_CUBIC)
    return n / 1.75


HAIRS = 36


def simulate(strokes, res=12.0, seed=0):
    """Hair-bundle brush along every stroke; returns ink coverage 0..1 on a SIZE_MM cell.

    The bundle spans the footprint width of the current press. Each hair carries ink
    along a smooth random profile and runs dry where that profile drops below a
    threshold that rises towards the bundle edge and with the length already written
    in the stroke (ink load): frayed edges and 飞白. A narrow core under the tip never
    runs dry."""
    rng = np.random.default_rng(seed)
    S = int(round(SIZE_MM * res))
    ink = np.zeros((S, S), np.float32)
    for st in strokes:
        p = st['points_px'] * MM * res; d = st['depth_mm']
        dense = resample(p, 0.25 * res)
        if len(dense) < 2:
            continue
        s0 = np.r_[0, np.cumsum(np.hypot(*np.diff(p, axis=0).T))]
        s1 = np.r_[0, np.cumsum(np.hypot(*np.diff(dense, axis=0).T))]
        dd = np.interp(s1 * s0[-1] / max(s1[-1], 1e-9), s0, d)
        s_mm = s1 / res
        tang = np.gradient(dense, axis=0); tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
        nrm = np.c_[-tang[:, 1], tang[:, 0]]
        half = width_of_press(dd) * res / 2
        load = 1.0 - np.clip((s_mm - 45.0) / 160.0, 0, 0.55)          # ink runs low late in a long stroke
        layer = np.zeros_like(ink)
        for a, b, h in zip(dense, dense[1:], half):
            cv2.line(layer, tuple(np.round(a * 8).astype(int)), tuple(np.round(b * 8).astype(int)), 1.0,
                     max(1, int(round(h * 0.9))), cv2.LINE_AA, 3)
        for j in range(HAIRS):
            u = -1 + 2 * (j + 0.5) / HAIRS + rng.normal(0, 0.25 / HAIRS)
            walk = cv2.GaussianBlur(rng.standard_normal((len(dense), 1)).astype(np.float32), (1, 0), 6.0,
                                    borderType=cv2.BORDER_REFLECT)[:, 0]
            walk /= max(float(walk.std()), 1e-6)
            wet = walk > (-2.2 + 2.6 * (1 - load) + 1.6 * abs(u) ** 3)
            pts = dense + nrm * (u * half * 0.98)[:, None]
            th = np.maximum(1, np.round(2.6 * half / HAIRS * 2)).astype(int)
            for i in range(len(pts) - 1):
                if wet[i] and wet[i + 1]:
                    cv2.line(layer, tuple(np.round(pts[i] * 8).astype(int)), tuple(np.round(pts[i + 1] * 8).astype(int)),
                             1.0, int(th[i]), cv2.LINE_AA, 3)
        ink = np.maximum(ink, layer)
    ink = cv2.GaussianBlur(ink, (0, 0), 0.5)
    rough = noise(ink.shape, seed + 1, 0.2 * res)
    return np.clip((ink - 0.45 + 0.08 * rough) * 5 + 0.5, 0, 1)


def to_image(cov, paper=(244, 236, 220), ink=(28, 24, 20)):
    p = np.array(paper, np.float32)[None, None]; k = np.array(ink, np.float32)[None, None]
    return (p * (1 - cov[..., None]) + k * cov[..., None]).astype(np.uint8)[..., ::-1]


# ---------------------------------------------------------------- outputs

def depth_colour(d):
    """0 mm light blue -> 6 mm deep red (BGR)."""
    u = float(np.clip(d / BRUSH['press_max_mm'], 0, 1))
    hsv = np.uint8([[[int(110 - 110 * u), 230, 230]]])
    return tuple(int(v) for v in cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0])


def label(img, text, org, size=0.9, colour=(60, 60, 60)):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, size, colour, 2, cv2.LINE_AA)


def cjk(img, text, org, px, colour=(40, 30, 20)):
    """Chinese caption with Pillow (OpenCV fonts have no CJK)."""
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', px)
    im = Image.fromarray(img[..., ::-1]); ImageDraw.Draw(im).text(org, text, font=font, fill=colour[::-1])
    img[:] = np.asarray(im)[..., ::-1]


def trace_sheet(base, strokes, raw_count):
    img = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)
    img = cv2.addWeighted(img, 0.45, np.full_like(img, 255), 0.55, 0)
    for i, st in enumerate(strokes):
        q = st['points_px']
        for a, b, d in zip(q, q[1:], st['depth_mm']):
            cv2.line(img, tuple(np.round(a).astype(int)), tuple(np.round(b).astype(int)), depth_colour(d), 5, cv2.LINE_AA)
        a, b = q[max(0, len(q) - 6)], q[-1]
        cv2.arrowedLine(img, tuple(np.round(a).astype(int)), tuple(np.round(b).astype(int)), (40, 40, 40), 3, cv2.LINE_AA, tipLength=1.2)
        c = tuple(np.round(q[0]).astype(int))
        cv2.circle(img, c, 17, (30, 30, 200), -1, cv2.LINE_AA)
        txt = str(i + 1); (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.putText(img, txt, (c[0] - tw // 2, c[1] + th // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    # depth legend
    for j in range(200):
        cv2.line(img, (800 + j, 990), (800 + j, 1010), depth_colour(j / 199 * BRUSH['press_max_mm']), 1)
    label(img, '0', (790, 980), 0.6); label(img, '6 mm', (975, 980), 0.6)
    return img


def compare(original_ink, cov):
    sim = cv2.resize(cov, (PX, PX), interpolation=cv2.INTER_AREA) > 0.5
    inter = (sim & original_ink).sum(); union = (sim | original_ink).sum()
    return float(inter / max(union, 1)), sim


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('studio', type=Path)
    ap.add_argument('--only', action='append')
    args = ap.parse_args()
    st_dir = args.studio
    manifest = json.loads((st_dir / 'manifest.json').read_text(encoding='utf-8'))
    stamp = time.strftime('%Y%m%d_%H%M')
    def tree(d):
        return {f.relative_to(d).as_posix(): f.read_bytes() for f in sorted(d.glob('*/*.json'))}
    latest = sorted(st_dir.glob('描红原始数据备份_*'))
    if not latest or tree(latest[-1]) != tree(st_dir / 'annotations'):     # back up only what changed
        shutil.copytree(st_dir / 'annotations', st_dir / ('描红原始数据备份_%s' % stamp))
    out_tr, out_sim, out_data = st_dir / '描红轨迹', st_dir / '模拟效果', st_dir / '轨迹数据'
    for d in (out_tr, out_sim, out_data):
        d.mkdir(exist_ok=True)
    report = []
    for w, mw in zip(B.WORKS, manifest['works']):
        assert w['id'] == mw['id']
        if args.only and w['id'] not in args.only:
            continue
        folder = '%s_%s' % (w['author'], w['title'])
        (out_tr / folder).mkdir(exist_ok=True); (out_sim / folder).mkdir(exist_ok=True)
        masks = ink_masks(w)
        sims, data, per_char = [], [], []
        for c, mask in zip(mw['chars'], masks):
            ann = json.loads((st_dir / 'annotations' / w['id'] / ('%02d.json' % c['index'])).read_text(encoding='utf-8'))
            raw = [s['points'] for s in ann['strokes']]
            per_char.append((raw, [s for s in (process_stroke(r, mask) for r in raw) if s is not None]))
        scale = work_scale([st for _, sts in per_char for st in sts])
        for st in (st for _, sts in per_char for st in sts):
            set_press(st, scale)
        print(folder, 'width scale', round(scale, 3), flush=True)
        for c, mask, (raw, strokes) in zip(mw['chars'], masks, per_char):
            dropped = len(raw) - len(strokes)
            base = cv2.imdecode(np.fromfile(str(st_dir / c['image']), np.uint8), cv2.IMREAD_GRAYSCALE)
            name = '%02d_%s' % (c['index'] + 1, c['char'])
            cv2.imencode('.png', trace_sheet(base, strokes, len(raw)))[1].tofile(str(out_tr / folder / (name + '_轨迹.png')))
            cov = simulate(strokes, seed=c['index'] + 17 * len(data))
            iou, sim = compare(mask, cov)
            sims.append(cov)
            # side by side: original | simulated | overlay
            sim_img = to_image(cov)
            orig = cv2.resize(cv2.cvtColor(base, cv2.COLOR_GRAY2BGR), sim_img.shape[1::-1], interpolation=cv2.INTER_AREA)
            over = np.full((PX, PX, 3), 255, np.uint8)
            over[mask] = (200, 200, 200); over[sim & mask] = (60, 60, 60); over[sim & ~mask] = (40, 40, 220)
            over = cv2.resize(over, sim_img.shape[1::-1], interpolation=cv2.INTER_AREA)
            gap = np.full((sim_img.shape[0], 16, 3), 255, np.uint8)
            sheet = np.hstack([orig, gap, sim_img, gap, over])
            head = np.full((70, sheet.shape[1], 3), 255, np.uint8)
            cjk(head, '原帖', (sim_img.shape[1] // 2 - 30, 14), 34)
            cjk(head, '模拟书写', (sim_img.shape[1] + 16 + sim_img.shape[1] // 2 - 60, 14), 34)
            cjk(head, '叠加对比（灰=原帖 深=重合 红=多出）', (2 * (sim_img.shape[1] + 16) + 40, 18), 28)
            foot = np.full((60, sheet.shape[1], 3), 255, np.uint8)
            cjk(foot, '「%s」  %d 笔  吻合度 %.0f%%  最深下压 %.1f mm%s' % (c['char'], len(strokes), iou * 100,
                max((float(s['depth_mm'].max()) for s in strokes), default=0),
                '' if scale > 0.999 else '  笔画宽度按原帖 %.0f%% 书写' % (scale * 100)), (20, 10), 30)
            cv2.imencode('.png', np.vstack([head, sheet, foot]))[1].tofile(str(out_sim / folder / (name + '_模拟.png')))
            cv2.imencode('.png', sim_img)[1].tofile(str(out_sim / folder / (name + '_模拟单字.png')))
            data.append(dict(index=c['index'], character=c['char'], strokes_traced=len(raw), strokes_used=len(strokes),
                             dropped_clicks=dropped, iou=round(iou, 4),
                             strokes=[dict(points_mm=[[round(float(x) * MM, 3), round(float(y) * MM, 3), round(float(z), 3)]
                                                      for (x, y), z in zip(s['points_px'], s['depth_mm'])],
                                           width_mm=[round(float(v), 3) for v in s['width_mm']],
                                           crossing=[bool(v) for v in s['crossing']]) for s in strokes]))
            report.append((folder, c['char'], len(raw), len(strokes), iou))
            print(folder, c['char'], len(raw), len(strokes), round(iou, 3), flush=True)
        (out_data / (w['id'] + '.json')).write_text(json.dumps(dict(
            schema='masterpiece-traces-v1', work=w['id'], title=w['title'], author=w['author'], size_mm=SIZE_MM,
            units='mm in the %g mm character cell, x right, y down; third value = press depth (mm)' % SIZE_MM,
            brush=dict(BRUSH, tip_mm=TIP_MM, splay=SPLAY), width_scale=round(scale, 4), chars=data), ensure_ascii=False), encoding='utf-8')
        # whole sentence as written in 名帖表演: columns of three, left to right
        n = len(sims); cols = math.ceil(n / 3); rows = min(3, n); cell = sims[0].shape[0]
        gx, gy, pad = int(cell * 0.15), int(cell * 0.1), int(cell * 0.12)
        page = np.zeros((rows * cell + (rows - 1) * gy + 2 * pad, cols * cell + (cols - 1) * gx + 2 * pad), np.float32)
        for i, cov in enumerate(sims):
            y, x = pad + (i % 3) * (cell + gy), pad + (i // 3) * (cell + gx)
            page[y:y + cell, x:x + cell] = np.maximum(page[y:y + cell, x:x + cell], cov)
        cv2.imencode('.png', to_image(page))[1].tofile(str(out_sim / ('%s_整幅模拟.png' % folder)))
    lines = ['字帖\t字\t描的笔数\t采用笔数\t吻合度']
    lines += ['%s\t%s\t%d\t%d\t%.0f%%' % (r[:4] + (r[4] * 100,)) for r in report]
    lines.append('平均吻合度\t%.0f%%' % (100 * np.mean([r[4] for r in report])))
    (out_sim / '吻合度统计.txt').write_text('\r\n'.join(lines) + '\r\n', encoding='utf-8-sig')
    print('mean iou', np.mean([r[4] for r in report]))


if __name__ == '__main__':
    main()
