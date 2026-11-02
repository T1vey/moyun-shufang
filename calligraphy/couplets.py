"""春联模式 (2026-10-29): built-in couplets in 70 mm 楷书 on the 名帖 paper calibration.

One line per row: the bottom row is the upper line (上联), the middle row the lower line
(下联), the top row the banner (横批). Every character is turned 90° counter-clockwise (its
top towards the left) and a line reads from left to right. At a fixed 70 mm like 名帖 a row
of the paper holds three characters, so each line continues on the same row of the next
sheet: sheet 1 holds characters 1-3 of every line, sheet 2 characters 4-6, sheet 3 the 7th.
Laid side by side, the sheets give one strip per line. A paper change between sheets, fixed
100 %. Each row of a sheet is planned as its own page (node budget, saved like a 名帖 column).
No separate couplet table and no new calibration: the saved 名帖 / 诗词 commands stay valid.
Coordinates are the paper's canvas (x right, y down, the same view as the other writing modes);
no motion here.
"""
import json
from functools import lru_cache
from pathlib import Path
from . import glyph_store
from .curves import BrushCurve
from .presets import profile, VERSION, binding
from .composer import digest

LIBRARY = Path(__file__).resolve().parents[1] / 'data/calligraphy/couplets/couplets.json'
SCHEMA = 'brush-couplet-v1'
LAYOUT_VERSION = 'couplet-line-rows-70-20261029-v3'
STYLE = 'kai'
SIZE_MM = 70.     # fixed, the 名帖 size
MARGIN_MM = 10.   # as 名帖
PER_ROW = 3       # characters of one line per sheet (a 名帖 column turned on its side)
ROWS = 3          # rows per sheet: 上联 (bottom), 下联, 横批 (top)
GAP_ALONG_MM = 10.5   # between characters in a row (名帖 column gap, 0.15 x 70)
GAP_ROWS_MM = 7.      # between rows (名帖 character gap, 0.1 x 70)
PARTS = {'upper': '上联', 'lower': '下联', 'banner': '横批'}


@lru_cache(maxsize=1)
def library():
    doc = json.loads(LIBRARY.read_text(encoding='utf-8'))
    if doc.get('schema') != 'couplets-v1':
        raise ValueError('春联库格式错误')
    known = set(glyph_store.manifest(STYLE)['characters']); seen = set()
    for c in doc['items']:
        if c['id'] in seen or len(c['upper']) != len(c['lower']) or len(c['banner']) != 4:
            raise ValueError('春联库条目无效：' + c['id'])
        missing = ''.join(ch for ch in c['upper'] + c['lower'] + c['banner'] if ch not in known)
        if missing:
            raise ValueError('春联 %s 有字库未收录的字：%s' % (c['id'], missing))
        seen.add(c['id'])
    return doc


def couplet(couplet_id):
    for c in library()['items']:
        if c['id'] == couplet_id:
            return c
    raise ValueError('未找到该春联')


def catalog():
    return [dict(c, chars=len(c['upper'])) for c in library()['items']]


def surface(config, meta=None):
    """The calibrated surface a brush task is written on: the paper (couplets too, since
    2026-10-29), at the brush's own contact height when it has been calibrated."""
    base = config['paper']
    z = config.get('calligraphy', {}).get('contact_z_mm')
    if isinstance(meta, dict) and str(meta.get('schema', '')).startswith('hardpen-'):
        # 硬笔 (2026-10-27): the paper at the hard pen's own contact height.
        z = config.get('hardpen', {}).get('contact_z_mm')
        if z is None:
            raise ValueError('请先在设置中标定硬笔落笔高度')
    elif not (isinstance(meta, dict) and str(meta.get('schema', '')).startswith('brush-')):
        z = None
    if z is not None:
        base = dict(base, origin_m=[base['origin_m'][0], base['origin_m'][1], float(z) / 1000.])
    return base


def needed_mm(couplet_id=None):
    """The paper one sheet needs (the same for every couplet)."""
    return (PER_ROW * SIZE_MM + (PER_ROW - 1) * GAP_ALONG_MM + 2 * MARGIN_MM,
            ROWS * SIZE_MM + (ROWS - 1) * GAP_ROWS_MM + 2 * MARGIN_MM)


def layout(couplet_id, paper):
    c = couplet(couplet_id)
    W, H = float(paper['width_mm']), float(paper['height_mm'])
    need_w, need_h = needed_mm()
    if need_w > W + 1e-8 or need_h > H + 1e-8:
        raise ValueError('春联需要至少 %.0f×%.0f mm 的已标定纸面（当前 %.0f×%.0f mm），与名帖表演相同'
                         % (need_w, need_h, W, H))
    x0 = (W - (need_w - 2 * MARGIN_MM)) / 2
    y0 = (H - (need_h - 2 * MARGIN_MM)) / 2
    first = {'upper': 0, 'lower': len(c['upper']), 'banner': 2 * len(c['upper'])}
    count = -(-max(len(c['upper']), len(c['banner'])) // PER_ROW)
    pages, sheets = [], []
    for sheet in range(count):
        sheets.append([])
        for pos, part in enumerate(('upper', 'lower', 'banner')):     # pos 0 = bottom row
            chunk = c[part][sheet * PER_ROW:(sheet + 1) * PER_ROW]
            if not chunk:
                continue
            y = y0 + (ROWS - 1 - pos) * (SIZE_MM + GAP_ROWS_MM)
            pages.append([dict(character=ch, text_index=first[part] + sheet * PER_ROW + k, part=part, rotate='ccw90',
                               sheet=sheet, row=pos, x_mm=round(x0 + k * (SIZE_MM + GAP_ALONG_MM), 6), y_mm=round(y, 6))
                          for k, ch in enumerate(chunk)])
            sheets[-1].append(len(pages) - 1)
    return dict(couplet_id=couplet_id, upper=c['upper'], lower=c['lower'], banner=c['banner'],
                font_size_mm=SIZE_MM, width_mm=W, height_mm=H, pages=pages, sheets=sheets,
                page_count=len(pages), sheet_count=len(sheets),
                layout_version=LAYOUT_VERSION, library_version=library()['version'])


def rotated(points, rotate):
    """Turn 50-unit keyframes (x right, y down) by 90°: 'ccw90' puts the character's top on
    the left, 'cw90' on the right; 'none' keeps it upright."""
    if rotate == 'none':
        return points
    if rotate == 'ccw90':
        return [[p[1], 50. - p[0]] + list(p[2:]) for p in points]
    return [[50. - p[1], p[0]] + list(p[2:]) for p in points]


def revision(config):
    table = config['paper']
    return digest(dict(calibration=binding(config), table=table, brush=profile(config), module_version=VERSION,
                       glyph_version=glyph_store.manifest(STYLE)['version'], layout_version=LAYOUT_VERSION,
                       library_version=library()['version']))


def task(couplet_id, page_index, config):
    """One row (up to three characters) of the couplet."""
    doc = layout(couplet_id, surface(config, dict(schema=SCHEMA)))
    if type(page_index) is not int or not 0 <= page_index < doc['page_count']:
        raise ValueError('页码无效')
    p = profile(config); paths = []; depths = []; feeds = []; mapping = []
    scale = SIZE_MM / 50.
    for cell in doc['pages'][page_index]:
        for index, stroke in enumerate(glyph_store.glyph(cell['character'], STYLE)['strokes']):
            dense = BrushCurve(rotated(stroke['points'], cell['rotate'])).sample(scale)
            path = [[round(a[0] * scale + cell['x_mm'], 6), round(a[1] * scale + cell['y_mm'], 6)] for a in dense]
            if any(not 0 <= x <= doc['width_mm'] or not 0 <= y <= doc['height_mm'] for x, y in path):
                raise ValueError('字形越出已标定纸面')
            paths.append(path); depths.append([round(a[2] * p['max_press_mm'], 8) for a in dense])
            feeds.append([a[3] for a in dense])
            mapping.append(dict(character=cell['character'], text_index=cell['text_index'], part=cell['part'],
                                stroke_index=index))
    meta = dict(schema=SCHEMA, module='couplet', version=VERSION, brush=p, couplet_id=couplet_id,
                page_index=page_index, page_count=doc['page_count'], font_size_mm=SIZE_MM, style=STYLE,
                glyph_version=glyph_store.manifest(STYLE)['version'], layout_version=LAYOUT_VERSION,
                library_version=doc['library_version'], revision=revision(config), stroke_map=mapping,
                depth_mm=depths, feed_ratio=feeds)
    meta['content_digest'] = digest({k: v for k, v in meta.items() if k not in ('depth_mm', 'feed_ratio')})
    return dict(units='mm', width_mm=doc['width_mm'], height_mm=doc['height_mm'],
                coordinate_system='full_canvas_xy_down', paths=paths, calligraphy=meta)


def preview_svg(couplet_id, config, sheet=0):
    """One sheet: authored brush strokes on red row bands (not an FK prediction)."""
    doc = layout(couplet_id, surface(config, dict(schema=SCHEMA))); scale = SIZE_MM / 50.
    W, H = doc['width_mm'], doc['height_mm']; out = []
    if not 0 <= sheet < doc['sheet_count']:
        raise ValueError('纸张序号无效')
    pad = GAP_ROWS_MM / 2
    for page in doc['sheets'][sheet]:
        cells = doc['pages'][page]
        length = len(cells) * SIZE_MM + (len(cells) - 1) * GAP_ALONG_MM
        out.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#c8372b"/>'
                   % (cells[0]['x_mm'] - pad, cells[0]['y_mm'] - pad, length + 2 * pad, SIZE_MM + 2 * pad))
        for cell in cells:
            for stroke in glyph_store.glyph(cell['character'], STYLE)['strokes']:
                pts = BrushCurve(rotated(stroke['points'], cell['rotate'])).sample(scale, step_mm=1, tolerance_mm=.05,
                                                                                    compression_step=.1, feed_step=.2)
                for a, b in zip(pts, pts[1:]):
                    out.append('<path d="M%.2f %.2fL%.2f %.2f" stroke-width="%.2f"/>'
                               % (a[0] * scale + cell['x_mm'], a[1] * scale + cell['y_mm'],
                                  b[0] * scale + cell['x_mm'], b[1] * scale + cell['y_mm'], 1.2 + 6 * (a[2] + b[2]) / 2))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %g %g"><rect width="%g" height="%g" fill="#fbf5e8"/>'
            '<g fill="none" stroke="#14100d" stroke-linecap="round">%s</g></svg>' % (W, H, W, H, ''.join(out))).encode()
