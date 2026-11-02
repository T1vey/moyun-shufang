"""ARM-side conditioning around the PL stages (each a few milliseconds).

flatten      : divide the Y plane by a paper-background estimate so shadows and dark
               table areas become white before the PL thresholds the frame.
clean        : drop blobs that touch the page edge and are large (table, paper edge)
               and isolated specks, on the rectified page from the PL.
skeleton_glyph : scale one character to a fixed height, thin it to a 1-px skeleton
               (Zhang-Suen) and redraw it at one fixed stroke width.  Templates are built
               with the same function, so pen/brush thickness no longer affects matching.
normalize_width : older width-matching alternative (kept for comparison).
"""
import numpy as np
from . import model as m

TEMPLATE_WIDTH_RATIO = 0.0505     # default; the template file records its own median width/size
SKELETON_SIZE = 120               # glyph long side before thinning
SKELETON_WIDTH = 5                # redrawn stroke width (px at SKELETON_SIZE)
SKELETON_CELL = SKELETON_SIZE + 16
SPUR_LENGTH = 6                   # skeleton branches shorter than this (px) are thinning spurs


def flatten(gray, kernel=31):
    """kernel is at 1/4 scale (31 -> ~124 px): wider than the boldest brush stroke, so
    stroke interiors are not mistaken for background and hollowed out."""
    import cv2
    small = cv2.resize(gray, (m.W // 4, m.H // 4), interpolation=cv2.INTER_AREA)
    bg = cv2.dilate(small, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel)))
    bg = cv2.blur(bg, (kernel // 2 | 1, kernel // 2 | 1))
    bg = cv2.resize(bg, (m.W, m.H), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    out = gray.astype(np.float32) * (235.0 / np.maximum(bg, 24.0))
    return np.clip(out, 0, 255).astype(np.uint8)


def clean(rect, min_area=12, edge_contact=0.25):
    """Drop specks, and blobs that run along the page border (table, paper edge).

    A character that merely crosses the border touches it over about one stroke
    width, so it is kept; a background region hugs it for a quarter side or more.
    """
    import cv2
    size = rect.shape[0]
    n, lab, st, _ = cv2.connectedComponentsWithStats(rect.astype(np.uint8), connectivity=8)
    border = np.concatenate([lab[0], lab[-1], lab[1:-1, 0], lab[1:-1, -1]])
    contact = np.bincount(border, minlength=n)
    keep = np.zeros(n, bool)
    for k in range(1, n):
        keep[k] = st[k, 4] >= min_area and contact[k] < edge_contact * size
    return keep[lab]


def stroke_width(region):
    import cv2
    ink = int(region.sum())
    if ink == 0:
        return 0.0
    eroded = cv2.erode(region.astype(np.uint8), np.ones((3, 3), np.uint8))
    return 2.0 * ink / max(1, ink - int(eroded.sum()))


def width_cv(region):
    """Spread of local stroke width over 8x8 zones of the glyph (ink uniformity)."""
    ys, xs = np.nonzero(region)
    if xs.size == 0:
        return 0.0
    crop = region[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    hs, ws = crop.shape
    widths = []
    for zy in range(8):
        for zx in range(8):
            z = crop[zy * hs // 8:(zy + 1) * hs // 8, zx * ws // 8:(zx + 1) * ws // 8]
            if z.sum() >= 6:
                widths.append(stroke_width(z))
    widths = np.array(widths)
    return float(widths.std() / widths.mean()) if widths.size >= 3 and widths.mean() > 0 else 0.0


def normalize_width(rect, box, ratio=TEMPLATE_WIDTH_RATIO):
    """Returns (rect copy with the box region width-normalised, measured width, radius)."""
    import cv2
    x0, y0, x1, y1 = box
    region = rect[y0:y1, x0:x1]
    bb = m.tight_bbox(region, (0, 0, region.shape[1], region.shape[0]))
    out = rect.copy()
    if bb is None:
        return out, 0.0, 0
    s = max(bb[2] - bb[0], bb[3] - bb[1])
    w = stroke_width(region)
    r = int(round((ratio * s - w) / 2))
    r = max(-2, min(r, 12))
    if r:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * abs(r) + 1, 2 * abs(r) + 1))
        u = region.astype(np.uint8)
        pad = abs(r) + 1
        u = cv2.copyMakeBorder(u, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
        u = cv2.dilate(u, k) if r > 0 else cv2.erode(u, k)
        u = u[pad:-pad, pad:-pad]
        out[y0:y1, x0:x1] = u.astype(bool)
    return out, w, r


_NB = ((-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1))   # clockwise from N


def _neighbours(sk, y, x):
    return [(y + dy, x + dx) for dy, dx in _NB if sk[y + dy, x + dx]]


def _crossings(sk, y, x):
    """0->1 transitions around the 8-neighbourhood: 1 end, 2 line, >=3 junction (stairs count 2)."""
    ring = [sk[y + dy, x + dx] for dy, dx in _NB]
    return sum(1 for i in range(8) if not ring[i] and ring[(i + 1) % 8])


def prune_spurs(sk, max_len=SPUR_LENGTH):
    """Remove short side branches left by thinning, keep true stroke ends and lengths.

    From every end point walk along the skeleton; if a junction is met within
    max_len pixels the walked branch is a spur and is erased.  Isolated short
    pieces (no junction) are real strokes such as dots and are kept.
    """
    sk = np.pad(sk.astype(bool), 1)
    for _ in range(2):
        changed = False
        ys, xs = np.nonzero(sk)
        for y, x in zip(ys, xs):
            if not sk[y, x] or len(_neighbours(sk, y, x)) != 1:
                continue
            path, prev, cur = [(y, x)], None, (y, x)
            while len(path) <= max_len:
                nxt = [p for p in _neighbours(sk, *cur) if p != prev and p not in path]
                if len(nxt) != 1 or _crossings(sk, *nxt[0]) >= 3:
                    if nxt and _crossings(sk, *nxt[0]) >= 3:
                        for p in path:
                            sk[p] = False
                        changed = True
                    break
                prev, cur = cur, nxt[0]
                path.append(cur)
        if not changed:
            break
    return sk[1:-1, 1:-1]


MODEL_PEN_PX = 11               # 本地模型 redraw: pen width at a 256 px canvas (glyph 80 % of it)


def model_glyph(region, size=256):
    """Character region -> uint8 image (255 = paper) for the 手写识字 model (2026-10-28).

    The model was trained on pen handwriting: the brush glyph is thinned to its centre line
    and redrawn at a pen-like width. On 24 rendered brush characters this gave 22 top-1
    (11-13 px; 5-9 px 18-19, the raw binary crop 14)."""
    import cv2
    from stroke_paths import _thin_cpu
    bb = m.tight_bbox(region, (0, 0, region.shape[1], region.shape[0]))
    if bb is None:
        return None
    x0, y0, x1, y1 = bb
    k = size * 0.8 / max(x1 - x0, y1 - y0)
    w, h = max(1, int(round((x1 - x0) * k))), max(1, int(round((y1 - y0) * k)))
    crop = cv2.resize(region[y0:y1, x0:x1].astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR) >= 0.5
    canvas = np.zeros((size, size), bool)
    oy, ox = (size - h) // 2, (size - w) // 2
    canvas[oy:oy + h, ox:ox + w] = crop
    pen = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (MODEL_PEN_PX, MODEL_PEN_PX))
    ink = cv2.dilate(_thin_cpu(canvas).astype(np.uint8), pen)
    return np.where(ink > 0, 0, 255).astype(np.uint8)


def skeleton_glyph(region, close=False, prune=False):
    """Character region -> SKELETON_CELL square bool image (fixed size, fixed stroke width).

    The 1-px centre line keeps each stroke's direction and length, and redrawing it at
    one width makes the directional features independent of pen/brush thickness.
    close/prune were measured (300 classes, five stroke widths) and both lowered
    accuracy: closing merges bold strokes, pruning sometimes removes dots and hooks,
    while the PL features already smooth over short spurs.  Templates use the defaults.
    """
    import cv2
    from stroke_paths import _thin_cpu
    bb = m.tight_bbox(region, (0, 0, region.shape[1], region.shape[0]))
    if bb is None:
        return None
    x0, y0, x1, y1 = bb
    crop = region[y0:y1, x0:x1].astype(np.uint8)
    k = SKELETON_SIZE / max(x1 - x0, y1 - y0)
    w, h = max(1, int(round((x1 - x0) * k))), max(1, int(round((y1 - y0) * k)))
    # Smooth resampling: nearest-neighbour upscaling of a small glyph leaves staircase
    # edges that thinning turns into false branches.
    interp = cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR
    crop = (cv2.resize(crop.astype(np.float32), (w, h), interpolation=interp) >= 0.5).astype(np.uint8)
    canvas = np.zeros((SKELETON_CELL, SKELETON_CELL), np.uint8)
    canvas[8:8 + h, 8:8 + w] = crop
    if close:
        canvas = cv2.morphologyEx(canvas, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    skeleton = _thin_cpu(canvas > 0)
    if prune:
        skeleton = prune_spurs(skeleton)
    skeleton = skeleton.astype(np.uint8)
    pen = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (SKELETON_WIDTH, SKELETON_WIDTH))
    return cv2.dilate(skeleton, pen).astype(bool)
