"""Turn the PL statistics of one character into the four sub-scores and a total.

The PL supplies every pixel count; this module only does the per-character
arithmetic (a few dozen operations).  The score measures geometric agreement
with the standard regular-script glyph, not artistic quality.
"""
import math
import numpy as np
from . import model as m

WEIGHTS = dict(shape=0.40, stroke=0.30, structure=0.15, ink=0.15)
GRADES = ((90, '优秀'), (80, '良好'), (70, '中等'), (60, '及格'), (0, '需多练习'))


def _clamp01(v):
    return max(0.0, min(1.0, v))


def _bbox_ratio(img):
    ys, xs = np.nonzero(img)
    if xs.size == 0:
        return 1.0
    return (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1)


def score(result, feats, bitmaps, calibration, box=None, width_cv=None):
    """result: contract.parse_result dict (non-empty)."""
    target = result['target']
    d = int(np.abs(feats[target].astype(np.int32) - result['features'].astype(np.int32)).sum())
    d0 = calibration.get('d_own_p90', 1150)
    d1 = calibration.get('d_other_p50', 1320) * 1.6
    s_shape = 100 * _clamp01((d1 - d) / max(1, d1 - d0))

    p = result['hit_w'] / max(1, result['n_w'])
    r = result['hit_t'] / max(1, result['n_t'])
    s_stroke = 100 * (2 * p * r / (p + r) if p + r else 0.0)

    t_img = np.unpackbits(bitmaps[target], bitorder='little').reshape(m.N, m.N).astype(bool)
    cxw, cyw = result['sx_w'] / max(1, result['n_w']), result['sy_w'] / max(1, result['n_w'])
    cxt, cyt = result['sx_t'] / max(1, result['n_t']), result['sy_t'] / max(1, result['n_t'])
    e_c = math.hypot(cxw - cxt, cyw - cyt) / m.N
    bx0, by0, bx1, by1 = result['bbox']
    ar_w = (bx1 - bx0) / max(1, by1 - by0)
    ar_t = _bbox_ratio(t_img)
    e_a = abs(math.log(max(1e-3, ar_w) / max(1e-3, ar_t)))
    e_g = 0.0
    if box is not None:
        x0, y0, x1, y1 = box
        cw, ch = max(1, x1 - x0), max(1, y1 - y0)
        e_g = math.hypot(((bx0 + bx1) / 2 - (x0 + x1) / 2) / cw, ((by0 + by1) / 2 - (y0 + y1) / 2) / ch)
    s_struct = 100 * _clamp01(1 - 4.0 * e_c - 0.8 * e_a - 0.5 * e_g)

    if width_cv is not None:
        cv = width_cv           # measured on the original strokes, before width normalisation
    else:
        ink = result['zone_ink'].astype(float)
        con = result['zone_contour'].astype(float)
        sel = con >= 4
        widths = 2 * ink[sel] / con[sel]
        cv = float(widths.std() / widths.mean()) if widths.size >= 3 and widths.mean() > 0 else 0.0
    # Rendered standard glyphs have a width CV of ~0.43-0.74 (median 0.57): brush strokes vary.
    s_ink = 100 * _clamp01(1 - max(0.0, cv - 0.6) / 0.6)

    subs = dict(shape=round(s_shape), stroke=round(s_stroke), structure=round(s_struct), ink=round(s_ink))
    total = round(sum(WEIGHTS[k] * v for k, v in dict(shape=s_shape, stroke=s_stroke, structure=s_struct, ink=s_ink).items()))
    comments = []
    if p < 0.8:
        comments.append('有多余的墨迹或笔画偏粗')
    if r < 0.8:
        comments.append('笔画不完整或偏短')
    if cxw - cxt > 3:
        comments.append('重心偏右')
    elif cxt - cxw > 3:
        comments.append('重心偏左')
    if cyw - cyt > 3:
        comments.append('重心偏下')
    elif cyt - cyw > 3:
        comments.append('重心偏上')
    if e_a > 0.25:
        comments.append('字形偏扁' if ar_w > ar_t else '字形偏瘦')
    if cv > 0.9:
        comments.append('粗细变化偏大')
    if not comments:
        comments.append('结构端正，笔画完整')
    grade = next(g for t, g in GRADES if total >= t)
    return dict(total=total, grade=grade, subs=subs, comments=comments,
                detail=dict(distance=d, precision=round(p, 3), recall=round(r, 3),
                            centroid=[round(cxw - cxt, 1), round(cyw - cyt, 1)], aspect=[round(ar_w, 2), round(ar_t, 2)],
                            width_cv=round(cv, 3)))
