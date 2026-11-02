"""Render glyph-library centrelines as brush strokes and build recogniser templates.

Each character is rendered as it would appear on the rectified page (about 2 px/mm,
60 mm glyph) at several brush widths and slight slants; the bit-exact model then
crops, normalises and extracts features exactly like the PL, and the averaged
features become the template.  The base rendering's 64x64 image is the scoring
reference.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
import cv2
from . import contract as c, model as m

VERSION = 'brushrecog-templates-v1'
CANVAS = 168
GLYPH_PX = 120          # 50 glyph units -> 120 px
OFFSET = (CANVAS - GLYPH_PX) / 2
VARIANTS = ((1.0, 0.0, 0.0), (0.7, 0.0, 0.0), (1.35, 0.0, 0.0), (1.0, 0.06, -2.0), (1.0, -0.06, 2.0))
BASE_WIDTH = 3.0         # px at zero pressure
PRESSURE_WIDTH = 16.0    # extra px at full pressure


def render(strokes, width=1.0, shear=0.0, rotate_deg=0.0):
    img = np.zeros((CANVAS, CANVAS), dtype=np.uint8)
    scale = GLYPH_PX / 50.0
    th = np.deg2rad(rotate_deg)
    rot = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    for stroke in strokes:
        pts = np.asarray([p[:3] for p in stroke['points']], dtype=np.float64)
        xy = pts[:, :2] - 25.0
        xy[:, 0] += shear * xy[:, 1]
        xy = xy @ rot.T * scale + CANVAS / 2
        wpx = np.maximum(1.0, (BASE_WIDTH + PRESSURE_WIDTH * pts[:, 2]) * width)
        for i in range(len(xy)):
            p = tuple(int(round(v * 4)) for v in xy[i])
            cv2.circle(img, p, int(round(wpx[i] * 2)), 1, -1, cv2.LINE_8, shift=2)
            if i:
                q = tuple(int(round(v * 4)) for v in xy[i - 1])
                cv2.line(img, q, p, 1, max(1, int(round((wpx[i] + wpx[i - 1]) / 2))), cv2.LINE_8, shift=2)
    return img.astype(bool)


OUTLINE_SOURCE = Path(__file__).resolve().parents[2] / 'maobi/chinese_caligraphy_robot/graphics.txt'
# (morph radius px: + thicker / - thinner, shear, rotation deg); first entry = scoring reference
OUTLINE_VARIANTS = ((0, 0.0, 0.0), (2, 0.0, 0.0), (-1, 0.0, 0.0), (4, 0.0, 0.0), (0, 0.06, -2.0), (0, -0.06, 2.0),
                    (2, 0.05, 1.5))


def load_outlines(characters, path=OUTLINE_SOURCE):
    want, out = set(characters), {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            rec = json.loads(line)
            if rec['character'] in want:
                out[rec['character']] = rec['strokes']
    missing = want - set(out)
    if missing:
        raise ValueError('outline source lacks %d characters' % len(missing))
    return out


def _path_polygon(d, steps=6):
    tok = d.replace(',', ' ').split()
    pts, polys, i, cur = [], [], 0, None
    while i < len(tok):
        t = tok[i]
        if t == 'M':
            if pts:
                polys.append(pts)
            cur = (float(tok[i + 1]), float(tok[i + 2])); pts = [cur]; i += 3
        elif t == 'L':
            cur = (float(tok[i + 1]), float(tok[i + 2])); pts.append(cur); i += 3
        elif t == 'Q':
            c1 = (float(tok[i + 1]), float(tok[i + 2])); e = (float(tok[i + 3]), float(tok[i + 4]))
            for k in range(1, steps + 1):
                u = k / steps
                pts.append(((1 - u) ** 2 * cur[0] + 2 * (1 - u) * u * c1[0] + u * u * e[0],
                            (1 - u) ** 2 * cur[1] + 2 * (1 - u) * u * c1[1] + u * u * e[1]))
            cur = e; i += 5
        elif t == 'C':
            c1 = (float(tok[i + 1]), float(tok[i + 2])); c2 = (float(tok[i + 3]), float(tok[i + 4]))
            e = (float(tok[i + 5]), float(tok[i + 6]))
            for k in range(1, steps + 1):
                u = k / steps; v = 1 - u
                pts.append((v ** 3 * cur[0] + 3 * v * v * u * c1[0] + 3 * v * u * u * c2[0] + u ** 3 * e[0],
                            v ** 3 * cur[1] + 3 * v * v * u * c1[1] + 3 * v * u * u * c2[1] + u ** 3 * e[1]))
            cur = e; i += 7
        elif t == 'Z':
            i += 1
        else:
            i += 1
    if pts:
        polys.append(pts)
    return polys


def render_outline(paths, morph=0, shear=0.0, rotate_deg=0.0):
    """Arphic KaiTi outlines (1024 units, y up, baseline 900) filled on the page canvas."""
    img = np.zeros((CANVAS, CANVAS), dtype=np.uint8)
    scale = GLYPH_PX / 1024.0
    th = np.deg2rad(rotate_deg)
    rot = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    for d in paths:
        for poly in _path_polygon(d):
            xy = np.asarray(poly, dtype=np.float64)
            xy = np.column_stack([xy[:, 0] - 512, 900 - xy[:, 1] - 512 + 124])
            xy[:, 0] += shear * xy[:, 1]
            xy = xy @ rot.T * scale + CANVAS / 2
            cv2.fillPoly(img, [np.round(xy * 4).astype(np.int32)], 1, cv2.LINE_8, shift=2)
    if morph:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * abs(morph) + 1, 2 * abs(morph) + 1))
        img = cv2.dilate(img, k) if morph > 0 else cv2.erode(img, k)
    return img.astype(bool)


def page_features(page):
    """Same steps as recognition: skeleton + fixed width on ARM, then the PL normalisation."""
    from .prepare import skeleton_glyph
    glyph = skeleton_glyph(page)
    if glyph is None:
        raise ValueError('empty glyph rendering')
    img, _ = m.normalize64(glyph, m.tight_bbox(glyph, (0, 0, glyph.shape[1], glyph.shape[0])))
    q, _, _ = m.def_features(img)
    return q, img


def build_outlines(characters, output, progress=None):
    """Templates from the KaiTi outlines (the source of the centreline library)."""
    outlines = load_outlines(characters)
    n = len(characters)
    feats = np.zeros((n, m.FEATURES), dtype=np.uint8)
    bitmaps = np.zeros((n, 512), dtype=np.uint8)
    variant_feats = np.zeros((n, len(OUTLINE_VARIANTS), m.FEATURES), dtype=np.uint8)
    ratios = []
    for i, ch in enumerate(characters):
        for j, v in enumerate(OUTLINE_VARIANTS):
            page = render_outline(outlines[ch], *v)
            q, img = page_features(page)
            variant_feats[i, j] = q
            if j == 0:
                bitmaps[i] = np.packbits(img.reshape(-1), bitorder='little')
                if i % 7 == 0:
                    from .prepare import stroke_width
                    bb = m.tight_bbox(page, (0, 0, CANVAS, CANVAS))
                    ratios.append(stroke_width(page) / max(bb[2] - bb[0], bb[3] - bb[1]))
        feats[i] = np.clip(np.rint(variant_feats[i].astype(np.float64).mean(axis=0)), 0, 255).astype(np.uint8)
        if progress and (i + 1) % 250 == 0:
            progress(i + 1, n)
    calibration = calibrate(feats, variant_feats)
    calibration['width_ratio'] = float(np.median(ratios))
    blob = c.pack_templates(feats, bitmaps)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(blob.astype('<u8').tobytes())
    meta = dict(schema='brushrecog-templates-v3-kaiti-skeleton', count=n, characters=characters,
                feature_bytes=m.FEATURES, bitmap_bytes=512, sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                variants=OUTLINE_VARIANTS, canvas=CANVAS, glyph_px=GLYPH_PX, calibration=calibration,
                source='Make Me a Hanzi graphics.txt (Arphic PL KaiTi outlines), Zhang-Suen skeleton redrawn at a fixed width')
    output.with_suffix('.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    return meta


def glyph_features(strokes, variant):
    page = render(strokes, *variant)
    bbox = m.tight_bbox(page, (0, 0, CANVAS, CANVAS))
    if bbox is None:
        raise ValueError('empty glyph rendering')
    img, _ = m.normalize64(page, bbox)
    q, _, _ = m.def_features(img)
    return q, img


def build(characters, glyph, output, progress=None):
    """characters: str in template order; glyph(ch) -> {'strokes': [...]}."""
    n = len(characters)
    feats = np.zeros((n, m.FEATURES), dtype=np.uint8)
    bitmaps = np.zeros((n, 512), dtype=np.uint8)
    variant_feats = np.zeros((n, len(VARIANTS), m.FEATURES), dtype=np.uint8)
    for i, ch in enumerate(characters):
        strokes = glyph(ch)['strokes']
        for j, variant in enumerate(VARIANTS):
            q, img = glyph_features(strokes, variant)
            variant_feats[i, j] = q
            if j == 0:
                bitmaps[i] = np.packbits(img.reshape(-1), bitorder='little')
        feats[i] = np.clip(np.rint(variant_feats[i].astype(np.float64).mean(axis=0)), 0, 255).astype(np.uint8)
        if progress and (i + 1) % 250 == 0:
            progress(i + 1, n)
    calibration = calibrate(feats, variant_feats)
    blob = c.pack_templates(feats, bitmaps)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(blob.astype('<u8').tobytes())
    meta = dict(schema=VERSION, count=n, characters=characters, feature_bytes=m.FEATURES, bitmap_bytes=512,
                sha256=hashlib.sha256(output.read_bytes()).hexdigest(), variants=VARIANTS,
                canvas=CANVAS, glyph_px=GLYPH_PX, calibration=calibration)
    output.with_suffix('.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    return meta


def calibrate(feats, variant_feats):
    """Distances of renderings to their own template and to the nearest other one."""
    n = len(feats)
    rng = np.random.default_rng(7)
    sample = rng.choice(n, size=min(n, 400), replace=False)
    own, other, correct = [], [], 0
    tf = feats.astype(np.int32)
    for i in sample:
        for v in variant_feats[i]:
            d = np.abs(tf - v.astype(np.int32)).sum(axis=1)
            own.append(int(d[i]))
            d2 = d.copy(); d2[i] = 1 << 30
            other.append(int(d2.min()))
            correct += int(np.argmin(d) == i)
    own, other = np.array(own), np.array(other)
    return dict(d_own_p50=int(np.percentile(own, 50)), d_own_p90=int(np.percentile(own, 90)),
                d_other_p10=int(np.percentile(other, 10)), d_other_p50=int(np.percentile(other, 50)),
                self_top1=correct / len(own), samples=int(len(own)))


def load(path):
    path = Path(path)
    meta = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != meta['sha256']:
        raise ValueError('template file hash mismatch')
    n = meta['count']
    data = np.frombuffer(raw, dtype=np.uint8)
    if data.size != n * (m.FEATURES + 512):
        raise ValueError('template file size mismatch')
    feats = data[:n * m.FEATURES].reshape(n, m.FEATURES)
    bitmaps = data[n * m.FEATURES:].reshape(n, 512)
    return meta, feats, bitmaps, np.frombuffer(raw, dtype='<u8')


# ----------------------------------------------------------------- font styles
STYLE_VARIANTS = ((0, 0.0, 0.0), (2, 0.0, 0.0), (-1, 0.0, 0.0), (0, 0.06, -2.0), (0, -0.06, 2.0))
MISSING_FEATURE = 255     # characters a font lacks get features that never match


def render_font(font, ch, morph=0, shear=0.0, rotate_deg=0.0):
    """One character from a TrueType font, fitted to GLYPH_PX inside the CANVAS page."""
    from PIL import Image, ImageDraw
    im = Image.new('L', (260, 260), 0)
    ImageDraw.Draw(im).text((30, 10), ch, font=font, fill=255)
    a = np.array(im) > 127
    bb = m.tight_bbox(a, (0, 0, a.shape[1], a.shape[0]))
    if bb is None:
        return None
    x0, y0, x1, y1 = bb
    k = GLYPH_PX / max(x1 - x0, y1 - y0)
    w, h = max(1, int(round((x1 - x0) * k))), max(1, int(round((y1 - y0) * k)))
    g = cv2.resize(a[y0:y1, x0:x1].astype(np.float32), (w, h), interpolation=cv2.INTER_AREA) >= 0.5
    page = np.zeros((CANVAS, CANVAS), np.uint8)
    oy, ox = (CANVAS - h) // 2, (CANVAS - w) // 2
    page[oy:oy + h, ox:ox + w] = g
    if shear or rotate_deg:
        c = CANVAS / 2
        mat = cv2.getRotationMatrix2D((c, c), rotate_deg, 1.0)
        mat[0, 1] += shear
        mat[0, 2] -= shear * c
        page = cv2.warpAffine(page, mat, (CANVAS, CANVAS), flags=cv2.INTER_NEAREST)
    if morph:
        kk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * abs(morph) + 1, 2 * abs(morph) + 1))
        page = cv2.dilate(page, kk) if morph > 0 else cv2.erode(page, kk)
    return page.astype(bool)


def build_font_style(characters, font_path, name, label, output):
    """Skeleton templates of one calligraphy font: features + scoring bitmaps."""
    from fontTools.ttLib import TTFont
    from PIL import ImageFont
    cmap = TTFont(str(font_path), fontNumber=0).getBestCmap()
    font = ImageFont.truetype(str(font_path), 200)
    n = len(characters)
    feats = np.full((n, m.FEATURES), MISSING_FEATURE, dtype=np.uint8)
    bitmaps = np.zeros((n, 512), dtype=np.uint8)
    variant_feats = np.zeros((n, len(STYLE_VARIANTS), m.FEATURES), dtype=np.uint8)
    present = np.zeros(n, bool)
    for i, ch in enumerate(characters):
        if ord(ch) not in cmap:
            continue
        pages = [render_font(font, ch, *v) for v in STYLE_VARIANTS]
        if pages[0] is None:
            continue
        for j, page in enumerate(pages):
            q, img = page_features(page)
            variant_feats[i, j] = q
            if j == 0:
                bitmaps[i] = np.packbits(img.reshape(-1), bitorder='little')
        feats[i] = np.clip(np.rint(variant_feats[i].astype(np.float64).mean(axis=0)), 0, 255).astype(np.uint8)
        present[i] = True
    idx = np.nonzero(present)[0]
    calibration = calibrate(feats[idx], variant_feats[idx])
    blob = c.pack_templates(feats, bitmaps)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(blob.astype('<u8').tobytes())
    meta = dict(schema='brushrecog-templates-v3-kaiti-skeleton', style=name, label=label, count=n,
                characters=characters, present=int(present.sum()), missing=''.join(ch for ch, p in zip(characters, present) if not p),
                feature_bytes=m.FEATURES, bitmap_bytes=512, sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                variants=STYLE_VARIANTS, canvas=CANVAS, glyph_px=GLYPH_PX, calibration=calibration,
                source=Path(font_path).name)
    output.with_suffix('.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    return meta
