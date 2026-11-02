"""Cleaner masterpiece ink and brush paths (build machine only, used by tools/build_masterpieces.py).

1. Edge from a super-resolved strip (tools/masterpiece_sr.py): the low-resolution
   crop still decides which ink belongs to the character (seals, ruled lines and
   neighbours are already removed there); its outline is then re-thresholded on the
   x4 strip, so a 100 px character no longer carries stair-step edges.
2. Path smoothing: the traced centreline follows the skeleton, which wobbles with
   ragged edges and bends towards every crossing. Each path is refitted with a
   weighted Whittaker smoother: points inside a crossing get almost no weight, so
   the brush passes it along its own direction; true corners (折, 钩) split the fit
   so they stay sharp. Stroke width (press) is bridged across crossings the same way.
"""
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_style_glyphs as G
import masterpiece_crop as C


# ---------------------------------------------------------------- super-resolved edge

def sr_glyph(glyph, offset, scale, strip, factor=4, opts=None):
    """glyph: binary crop from the (scale x) strip at offset (row, col); strip: RGB of the
    same column box upscaled `factor` x. Returns the glyph's binary ink at factor/scale x."""
    opts = dict(opts or {})
    k = factor / float(scale)
    h, w = glyph.shape
    y0, x0 = int(round(offset[0] * k)), int(round(offset[1] * k))
    H, W = int(round(h * k)), int(round(w * k))
    region = strip[y0:y0 + H, x0:x0 + W]
    if region.shape[0] < H or region.shape[1] < W:
        return None
    roi = cv2.resize(glyph.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)
    r = int(math.ceil(1.5 * k))
    roi = cv2.dilate(roi, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0
    mask = dict(blur=opts.get('blur', 1.0) * math.sqrt(k), factor=opts.get('factor', 0.92),
                close=int(round(opts.get('close', 0) * k)), holes=int(opts.get('holes', 0) * k * k))
    for key in ('invert', 'adaptive', 'offset', 'sat_max'):
        if key in opts:
            mask[key] = opts[key] * (k if key == 'adaptive' else 1)
    ink = C.ink_mask(region, **mask) & roi
    # Keep only ink touching the low-resolution character (no new specks).
    n, lab = cv2.connectedComponents(ink.astype(np.uint8), connectivity=8)
    core = cv2.resize(glyph.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST) > 0
    keep = np.zeros(n, bool); keep[np.unique(lab[core & ink])] = True; keep[0] = False
    ink = keep[lab]
    return ink if ink.any() else None


# ---------------------------------------------------------------- path smoothing

def whittaker(z, w, lam):
    """argmin sum w (x - z)^2 + lam sum (second difference of x)^2, per column of z."""
    n = len(z)
    if n < 4:
        return z.copy()
    D = np.diff(np.eye(n), 2, axis=0)
    A = np.diag(w) + lam * D.T @ D
    return np.linalg.solve(A, w[:, None] * z)


def junctions(smooth, dt):
    """Pixels where strokes cross or meet: discs around skeleton branch points."""
    from stroke_paths import _thin_cpu
    skel = _thin_cpu(smooth)
    nb = cv2.filter2D(skel.astype(np.uint8), cv2.CV_8U, G.KERNEL, borderType=cv2.BORDER_CONSTANT) * skel
    mask = np.zeros(smooth.shape, np.uint8)
    for y, x in np.argwhere(skel & (nb >= 3)):
        cv2.circle(mask, (int(x), int(y)), int(math.ceil(1.3 * dt[y, x] + 2)), 1, -1)
    return mask > 0


def corners(q, inside, reach=6, angle=50.0):
    """Indices of true corners: a sustained turn of more than `angle` degrees over
    `reach` px on each side, outside crossings, at least `reach` px from the ends."""
    n = len(q); out = []
    if n < 2 * reach + 3:
        return out
    turn = np.zeros(n)
    for i in range(reach, n - reach):
        a, b = q[i] - q[i - reach], q[i + reach] - q[i]
        c = np.dot(a, b) / max(np.linalg.norm(a) * np.linalg.norm(b), 1e-9)
        turn[i] = math.degrees(math.acos(np.clip(c, -1, 1)))
    i = reach
    while i < n - reach:
        if turn[i] > angle and not inside[i]:
            j = i
            while j + 1 < n - reach and turn[j + 1] > angle:
                j += 1
            k = i + int(np.argmax(turn[i:j + 1]))
            if not out or k - out[-1] >= reach:
                out.append(k)
            i = j + 1
        else:
            i += 1
    return out


def refine(path, dt, jmask, lam=None, end_weight=50.0):
    """Pixel centreline -> (smoothed centreline, half-width per point), both at 1 px steps."""
    q = G.resample(np.asarray(path, float), 1.0)
    P = np.clip(np.round(q).astype(int), 0, G.R - 1)
    inside = jmask[P[:, 1], P[:, 0]]
    hw = dt[P[:, 1], P[:, 0]].astype(float)
    if len(q) < 5:
        return q, np.maximum(hw, 0.5)
    if lam is None:
        # Smoothing scale grows with the stroke width (a wide stroke's centre wobbles more).
        # /0.6: chosen 2026-10-27 (wobble p90 0.33 -> 0.14 units, 99 % of the path still on the ink)
        lam = float(np.clip(np.median(hw[~inside]) if (~inside).any() else np.median(hw), 3, 12) ** 4 / 0.6)
    w = np.where(inside, 0.02, 1.0)
    w[0] = w[-1] = end_weight
    cut = [0] + corners(q, inside) + [len(q) - 1]
    out = []
    for a, b in zip(cut, cut[1:]):
        ww = w[a:b + 1].copy(); ww[0] = ww[-1] = end_weight
        seg = whittaker(q[a:b + 1], ww, lam)
        out.append(seg if not out else seg[1:])
    s = np.vstack(out)
    # Width: crossings read the merged ink, so bridge them from both sides, then smooth.
    good = ~inside
    if good.sum() >= 2 and inside.any():
        idx = np.arange(len(hw)); hw = np.interp(idx, idx[good], hw[good])
    hw = whittaker(hw[:, None], np.ones(len(hw)), lam / 4)[:, 0]
    return s, np.maximum(hw, 0.5)


def keyframes(path, hw, width_ref):
    """Smoothed pixel centreline + half-width -> [x, y, compression, feed] (as G.keyframes)."""
    comp = np.clip(0.12 + 0.68 * hw / width_ref, 0.08, 0.85)
    pts = np.c_[np.asarray(path) * G.UNIT, comp]
    pts[0, 2] = pts[-1, 2] = 0.0
    n = len(pts)
    keep = [i for i in (1, 2, n - 3, n - 2) if 0 < i < n - 1]
    pts = G.rdp(pts, 0.04, keep)
    feed = np.clip(0.88 - 0.6 * pts[:, 2], 0.3, 0.9)
    out = np.c_[np.clip(pts[:, :2], 0, 50), pts[:, 2], feed]
    return [[round(float(v), 6) for v in row] for row in out]
