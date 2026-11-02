"""Cut single characters out of a masterpiece scan (build machine only; Pillow + OpenCV).

A column strip (x0, x1, y0, y1) holding n characters is split at the lightest
rows near even spacing. Ink is separated from paper and red seals by colour:
dark, low-saturation pixels are ink; for stone rubbings (light characters on a
dark ground) pass invert=True. Each character keeps only the ink components
that mostly belong to it, so a neighbour's touching stroke tip is dropped.
"""
import numpy as np
import cv2
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def load(path, box):
    with Image.open(path) as im:
        return np.asarray(im.convert('RGB').crop(box))


def ink_mask(rgb, invert=False, blur=1.0, close=0, factor=0.92, adaptive=0, offset=12, holes=0, sat_max=255, rules=False):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    v = hsv[..., 2].astype(np.float32)
    red = ((hsv[..., 0] < 12) | (hsv[..., 0] > 165)) & (hsv[..., 1] > 90) & (v > 90)   # seals (bright red; dark ink can read as red hue)
    gray = cv2.GaussianBlur(v, (0, 0), blur)
    if invert:
        gray = 255 - gray
    if adaptive:                                # uneven paper tone: compare with the local background
        local = cv2.GaussianBlur(gray, (0, 0), adaptive)
        ink = (gray < local - offset) & ~red
    else:
        t, _ = cv2.threshold(gray.astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        ink = (gray < t * factor) & ~red
    if sat_max < 255:                           # stains and foxing are coloured; ink is near-neutral
        ink &= cv2.GaussianBlur(hsv[..., 1].astype(np.float32), (0, 0), 1.5) <= sat_max
    ink = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)) > 0
    if rules:                                   # ruled (often dashed) column lines
        h, w = ink.shape
        col = cv2.dilate(ink.astype(np.uint8), np.ones((9, 1), np.uint8)).mean(0)   # bridge the dashes
        for x in range(w):
            lo, hi = max(0, x - 5), min(w, x + 6)
            side = np.r_[col[lo:max(lo, x - 2)], col[min(hi, x + 3):hi]]
            if col[x] > 0.35 and (not len(side) or side.mean() < col[x] * 0.4):
                for xx in range(max(0, x - 1), min(w, x + 2)):
                    # keep pixels where a stroke crosses (ink also 3 px left and right)
                    cross = ink[:, max(0, xx - 3)] & ink[:, min(w - 1, xx + 3)]
                    ink[:, xx] &= cross
    if close:                                   # mottled or faded ink: join the speckles of one stroke
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * close + 1, 2 * close + 1))
        ink = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_CLOSE, k) > 0
    if holes:                                   # small enclosed gaps inside a stroke (mottled ink)
        nb, lb, sb, _ = cv2.connectedComponentsWithStats((~ink).astype(np.uint8), connectivity=4)
        small = np.zeros(nb, bool); small[1:] = sb[1:, cv2.CC_STAT_AREA] <= holes
        ink = ink | small[lb]
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= max(12, ink.size * 2e-5)                # paper texture / dust
    return keep[lab]


def split_rows(ink, n, window=0.28):
    """n-1 cut rows, each at the lightest row within +-window of its even-spacing guess."""
    prof = cv2.GaussianBlur(ink.sum(1).astype(np.float32).reshape(-1, 1), (1, 0), 3).ravel()
    H = len(prof); step = H / n; cuts = [0]
    for k in range(1, n):
        lo, hi = int((k - window) * step), int((k + window) * step)
        lo = max(lo, cuts[-1] + int(step * 0.4))
        cuts.append(lo + int(np.argmin(prof[lo:hi])))
    return cuts + [H]


def isolate(ink, a, b, min_frac=0.006, partial=0.3, offset=False):
    """Ink of rows a..b: components lying mostly inside the band; a joined (连笔)
    stroke that clearly continues into the next character is cut at the band edge."""
    n, lab = cv2.connectedComponents(ink.astype(np.uint8), connectivity=8)
    out = np.zeros_like(ink)
    band = np.zeros_like(ink); band[a:b] = True
    for k in range(1, n):
        comp = lab == k
        inside = (comp & band).sum() / comp.sum()
        if inside >= 0.8:
            out |= comp
        elif inside >= partial:
            out |= comp & band
    # Specks of dirt or noise: components far smaller than the character's ink.
    n, lab, st, _ = cv2.connectedComponentsWithStats(out.astype(np.uint8), connectivity=8)
    if n > 1:
        total = st[1:, cv2.CC_STAT_AREA].sum()
        keep = np.zeros(n, bool); keep[1:] = st[1:, cv2.CC_STAT_AREA] >= total * min_frac
        out = keep[lab]
    ys, xs = np.nonzero(out)
    if not len(ys):
        return None
    pad = 4
    y0, x0 = max(0, ys.min() - pad), max(0, xs.min() - pad)
    g = out[y0:ys.max() + 1 + pad, x0:xs.max() + 1 + pad]
    return (g, (y0, x0)) if offset else g


def column(path, box, n, invert=False, cuts=None, min_frac=0.006, partial=0.3, scale=1, offset=False, **mask):
    """List of n binary character images (True = ink), top to bottom. cuts: optional
    n+1 absolute image rows separating the characters (for uneven cursive columns).
    scale > 1 upsamples first (thin strokes in small screenshots survive thresholding).
    offset=True returns (glyph, (row, col) of its top-left in the scaled strip) pairs."""
    rgb = load(path, box)
    if scale != 1:
        rgb = cv2.resize(rgb, (int(rgb.shape[1] * scale), int(rgb.shape[0] * scale)), interpolation=cv2.INTER_CUBIC)
    ink = ink_mask(rgb, invert, **mask)
    if cuts:
        assert len(cuts) == n + 1
        cuts = [int((c - box[1]) * scale) for c in cuts]
    else:
        cuts = split_rows(ink, n)
    return [isolate(ink, a, b, min_frac, partial, offset) for a, b in zip(cuts, cuts[1:])]


def sheet(glyphs, labels, out, cell=160):
    tiles = []
    for g, lab in zip(glyphs, labels):
        t = np.full((cell + 22, cell), 255, np.uint8)
        if g is not None:
            k = (cell - 10) / max(g.shape)
            r = cv2.resize((~g).astype(np.uint8) * 255, (max(1, int(g.shape[1] * k)), max(1, int(g.shape[0] * k))), interpolation=cv2.INTER_AREA)
            y, x = 22 + (cell - r.shape[0]) // 2, (cell - r.shape[1]) // 2
            t[y:y + r.shape[0], x:x + r.shape[1]] = r
        cv2.putText(t, lab, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, 0, 1)
        tiles.append(t)
    cv2.imencode('.png', np.hstack(tiles))[1].tofile(str(out))
