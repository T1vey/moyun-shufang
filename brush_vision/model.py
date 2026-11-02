"""Bit-exact software model of the PL vision chain.

Front end mirrors hw/vision/rtl (brush_cam.v, brush_otsu.v, brush_morph.v); the
recogniser mirrors hls_source/vision/tcb_brush_recog.cpp.  Every integer step,
rounding and float32 operation order matches the hardware so results can be
compared word for word, and the same code builds the 3500-character templates.
"""
import math
import numpy as np

W, H = 640, 480
WPR = W // 32
BORDER = 4
PREVIEW_W, PREVIEW_H = W // 4, H // 4
N = 64                 # normalised glyph size
BOX = 56               # glyph long side inside the 64x64 cell
ZONES = 8
FEATURES = ZONES * ZONES * 4
FEATURE_SUM = 8192
DILATE = 2
MAX_RECT = 320
MAX_BOXES = 16
RESULT_WORDS = 128
OP_PASS, OP_ERODE, OP_DILATE = 0, 1, 2
DEFAULT_OPS = (OP_ERODE, OP_DILATE, OP_DILATE, OP_ERODE)   # open, then close


# ----------------------------------------------------------------- front end
def rgb565_to_gray(pix):
    pix = np.asarray(pix, dtype=np.uint32)
    r5, g6, b5 = pix >> 11 & 31, pix >> 5 & 63, pix & 31
    r8, g8, b8 = (r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2)
    return ((77 * r8 + 150 * g8 + 29 * b8) >> 8).astype(np.uint8)


def bgr_to_rgb565(img):
    img = np.asarray(img, dtype=np.uint16)
    return (img[..., 2] >> 3 << 11) | (img[..., 1] >> 2 << 5) | (img[..., 0] >> 3)


def histogram(gray, roi=(0, W - 1, 0, H - 1)):
    """Hardware histogram: every 4th pixel of every 4th row, inclusive ROI."""
    x0, x1, y0, y1 = roi
    sub = np.zeros_like(gray, dtype=bool)
    sub[::4, ::4] = True
    ys, xs = np.mgrid[0:gray.shape[0], 0:gray.shape[1]]
    sel = sub & (xs >= x0) & (xs <= x1) & (ys >= y0) & (ys <= y1)
    values = gray[sel].astype(np.intp)    # bincount needs the native int on 32-bit ARM
    return np.bincount(values, minlength=256), int(values.size), int(values.sum())


def otsu_threshold(hist, n, s):
    """brush_otsu.v: argmax ((|S*n0-N*s0|>>7)^2 // (n0*n1)), midpoint of the first
    contiguous maximal plateau; None if no split exists."""
    n0 = s0 = best = 0
    first = last = None
    on_best = False
    for t in range(256):
        h = int(hist[t])
        n0 += h
        s0 += t * h
        n1 = n - n0
        if n0 == 0 or n1 == 0:
            on_best = False
            continue
        d = abs(s * n0 - n * s0) >> 7
        q = (d * d) // (n0 * n1)
        if q > best:
            best, first, last, on_best = q, t, t, True
        elif q == best and on_best:
            last = t
        else:
            on_best = False
    return None if first is None else (first + last) >> 1


def biased_threshold(otsu, bias):
    return int(min(255, max(0, otsu + bias)))


def yuyv_gray(frame):
    """YUYV 4:2:2 bytes (640x480x2) -> Y plane; Y is used directly as gray."""
    return np.asarray(frame, dtype=np.uint8).reshape(-1)[0::2].reshape(H, W)


def gray_to_yuyv(gray):
    out = np.full(H * W * 2, 128, dtype=np.uint8)
    out[0::2] = np.asarray(gray, dtype=np.uint8).reshape(-1)
    return out


def preprocess(gray, roi=(0, W - 1, 0, H - 1), otsu=True, manual=100, bias=0, ops=DEFAULT_OPS):
    """Mode 3 of tcb_brush_recog: histogram -> Otsu -> threshold -> 4 morphology stages."""
    hist, n, s = histogram(gray, roi)
    t = otsu_threshold(hist, n, s)
    thr = biased_threshold(t, bias) if otsu and t is not None else manual
    return frontend_binary(gray, thr, ops), dict(otsu=t, threshold=thr, hist_n=n, hist_s=s)


def morph3(img, op):
    if op == OP_PASS:
        return img.copy()
    p = np.pad(img, 1)
    stack = [p[dy:dy + img.shape[0], dx:dx + img.shape[1]] for dy in range(3) for dx in range(3)]
    return np.logical_and.reduce(stack) if op == OP_ERODE else np.logical_or.reduce(stack)


def frontend_binary(gray, threshold, ops=DEFAULT_OPS):
    """Binary frame as written to BRAM (rows >= H-BORDER are never written)."""
    b = gray < threshold
    for op in ops:
        b = morph3(b, op)
    out = np.zeros_like(b)
    out[BORDER:H - BORDER, BORDER:W - BORDER] = b[BORDER:H - BORDER, BORDER:W - BORDER]
    return out


def pack_frame(binary):
    """u32 words, 20 per row, LSB = leftmost pixel (BRAM / DDR layout)."""
    return np.packbits(np.asarray(binary, bool).reshape(H, W), axis=1, bitorder='little').view('<u4').reshape(-1)


def unpack_frame(words, width=W, height=H):
    words = np.asarray(words, dtype='<u4')
    return np.unpackbits(words.view(np.uint8), bitorder='little').reshape(height, -1)[:, :width].astype(bool)


def unpack_preview(words):
    return np.asarray(words, dtype='<u4').view(np.uint8).reshape(PREVIEW_H, PREVIEW_W)


# ----------------------------------------------------------------- recogniser
def popcount64(values):
    v = np.asarray(values, dtype=np.uint64)
    return np.unpackbits(v.view(np.uint8)).reshape(v.shape + (64,)).sum(axis=-1)


H_FRAC = 24     # fixed-point fraction bits of the homography


def homography_fixed(hmat):
    """Float 3x3 (rect -> camera) to int64 coefficients with h8 scaled to 2^H_FRAC."""
    h = np.asarray(hmat, dtype=np.float64).reshape(9)
    if not h[8] > 0:
        raise ValueError('homography must have positive h22')
    q = np.rint(h / h[8] * (1 << H_FRAC)).astype(np.int64)
    if np.any(np.abs(q) >= 1 << 36):
        raise ValueError('homography coefficients out of fixed-point range')
    return [int(v) for v in q]


def _round_div(num, den, limit):
    """n = 2*num + den; valid iff 0 <= n < 2*den*limit; result n // (2*den)."""
    n = 2 * num + den
    if n < 0 or n >= 2 * den * limit:
        return None
    return n // (2 * den)


def rectify(binary, hq, size):
    """Mode 1: (u,v) -> camera pixel round(H*(u,v,1)), fixed point, nearest sample.

    hq from homography_fixed; X/Y/Z start each row at h1*v+h2 etc. and step by h0/h3/h6.
    """
    h = [int(v) for v in hq]
    out = np.zeros((size, size), dtype=bool)
    for v in range(size):
        X, Y, Z = h[1] * v + h[2], h[4] * v + h[5], h[7] * v + h[8]
        for u in range(size):
            if Z > 0:
                x = _round_div(X, Z, W)
                y = _round_div(Y, Z, H)
                if x is not None and y is not None:
                    out[v, u] = binary[y, x]
            X += h[0]; Y += h[3]; Z += h[6]
    return out


def projections(rect):
    return rect.sum(axis=0).astype(np.uint16), rect.sum(axis=1).astype(np.uint16)


def tight_bbox(rect, box):
    x0, y0, x1, y1 = box
    region = rect[y0:y1, x0:x1]
    ys, xs = np.nonzero(region)
    if xs.size == 0:
        return None
    return x0 + int(xs.min()), y0 + int(ys.min()), x0 + int(xs.max()) + 1, y0 + int(ys.max()) + 1


def normalize64(rect, bbox):
    """Aspect-preserving resample of the tight box into BOX x BOX centred in 64x64."""
    bx0, by0, bx1, by1 = bbox
    w, h = bx1 - bx0, by1 - by0
    s = max(w, h)
    k = (BOX << 16) // s
    ow, oh = max(1, (w * k) >> 16), max(1, (h * k) >> 16)
    ox, oy = (N - ow) // 2, (N - oh) // 2
    out = np.zeros((N, N), dtype=bool)
    if s >= BOX:
        cnt = np.zeros((N, N), dtype=np.int64)
        ys, xs = np.nonzero(rect[by0:by1, bx0:bx1])
        i = ((xs * k) >> 16) + ox
        j = ((ys * k) >> 16) + oy
        np.add.at(cnt, (j, i), 1)
        out = cnt * (4 * BOX * BOX) >= s * s       # >= 1/4 of the footprint
    else:
        inv = (s << 16) // BOX
        for j in range(oh):
            for i in range(ow):
                out[oy + j, ox + i] = rect[by0 + ((j * inv) >> 16), bx0 + ((i * inv) >> 16)]
    return out, (ow, oh)


def rows64(img):
    return np.packbits(np.asarray(img, bool), axis=1, bitorder='little').view('<u8').reshape(N)


def _shift_rows(r, d):
    """Bit x of result = bit x-d of r (d>0 moves content right/higher x)."""
    r = r.astype(np.uint64)
    return (r << np.uint64(d)) if d > 0 else (r >> np.uint64(-d))


def def_features(img):
    """Directional element features (256 x uint8) plus per-zone ink/contour counts."""
    b = rows64(img)
    up = np.r_[np.uint64(0), b[:-1]]
    dn = np.r_[b[1:], np.uint64(0)]
    interior = b & up & dn & _shift_rows(b, 1) & _shift_rows(b, -1)
    c = b & ~interior
    cu = np.r_[np.uint64(0), c[:-1]]
    cd = np.r_[c[1:], np.uint64(0)]
    planes = [c & (_shift_rows(c, 1) | _shift_rows(c, -1)),          # 0 deg  horizontal
              c & (cu | cd),                                          # 90 deg vertical
              c & (_shift_rows(cu, -1) | _shift_rows(cd, 1)),         # 45 deg (up-right / down-left)
              c & (_shift_rows(cu, 1) | _shift_rows(cd, -1))]         # 135 deg (up-left / down-right)

    def zone_counts(rows):
        bits = np.unpackbits(rows.astype('<u8').view(np.uint8), bitorder='little').reshape(N, N)
        return bits.reshape(ZONES, 8, ZONES, 8).sum(axis=(1, 3)).astype(np.int64)

    raw = np.stack([zone_counts(p) for p in planes])             # [4, zy, zx]
    pad = np.pad(raw, ((0, 0), (1, 1), (1, 1)))
    kern = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]])
    blur = sum(kern[dy, dx] * pad[:, dy:dy + ZONES, dx:dx + ZONES] for dy in range(3) for dx in range(3))
    f = np.array([min(255, math.isqrt(int(g) * 64)) for g in blur.reshape(-1)], dtype=np.int64)
    total = int(f.sum())
    if total == 0:
        q = np.zeros(FEATURES, dtype=np.uint8)
    else:
        recip = (FEATURE_SUM << 16) // total
        q = np.minimum(255, (f * recip) >> 16).astype(np.uint8)
    # Feature order: direction-major then zone row-major (d, zy, zx).
    return q, zone_counts(b).reshape(-1).astype(np.uint8), zone_counts(c).reshape(-1).astype(np.uint8)


def l1(q, templates):
    return np.abs(templates.astype(np.int32) - q.astype(np.int32)).sum(axis=1)


def top5(dist, order):
    """Hardware insertion: a new distance goes before the first strictly larger one,
    so ties keep the template visited first.  order lists template ids visited."""
    top = [(0, 0xffffffff)] * 5
    for i in order:
        d = int(dist[i])
        for p in range(5):
            if d < top[p][1]:
                top = top[:p] + [(int(i), d)] + top[p:4]
                break
    return top


def dilate_rows(r, radius=DILATE):
    out = np.zeros(N, dtype=np.uint64)
    horiz = np.zeros(N, dtype=np.uint64)
    for d in range(-radius, radius + 1):
        horiz |= _shift_rows(r, d)
    for y in range(N):
        for d in range(-radius, radius + 1):
            if 0 <= y + d < N:
                out[y] |= horiz[y + d]
    return out


def score_stats(img, target):
    b, t = rows64(img), rows64(target)
    db, dt = dilate_rows(b), dilate_rows(t)
    bits_b = np.unpackbits(b.astype('<u8').view(np.uint8), bitorder='little').reshape(N, N)
    bits_t = np.unpackbits(t.astype('<u8').view(np.uint8), bitorder='little').reshape(N, N)
    yy, xx = np.mgrid[0:N, 0:N]
    return dict(n_w=int(popcount64(b).sum()), n_t=int(popcount64(t).sum()),
                hit_w=int(popcount64(b & dt).sum()), hit_t=int(popcount64(t & db).sum()),
                sx_w=int((xx * bits_b).sum()), sy_w=int((yy * bits_b).sum()),
                sx_t=int((xx * bits_t).sum()), sy_t=int((yy * bits_t).sum()))


def recognise_box(rect, size, box, templates, bitmaps, expected=-1, candidates=None):
    """Mode 2 for one box; templates [n,256] uint8, bitmaps [n,512] uint8."""
    x0, y0, x1, y1 = box
    x1, y1 = min(x1, size), min(y1, size)
    bbox = tight_bbox(rect, (x0, y0, x1, y1)) if x0 < x1 and y0 < y1 else None
    if bbox is None:
        return dict(empty=True, box=tuple(box))
    img, (ow, oh) = normalize64(rect, bbox)
    q, ink, contour = def_features(img)
    n_tpl = len(templates)
    order = range(n_tpl) if not candidates else [c for c in candidates if c < n_tpl]
    dist = l1(q, templates)
    best = top5(dist, order)
    target = expected if 0 <= expected < n_tpl else best[0][0]
    target_img = np.unpackbits(np.asarray(bitmaps[target], dtype=np.uint8), bitorder='little').reshape(N, N).astype(bool)
    return dict(empty=False, box=tuple(box), bbox=bbox, size=(ow, oh), top5=best, target=int(target),
                features=q, zone_ink=ink, zone_contour=contour, image=img,
                **score_stats(img, target_img))
