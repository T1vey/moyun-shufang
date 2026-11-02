"""诗词库: built-in Tang and Song quatrains in 楷书 on the calibrated paper (no motion here).

Traditional vertical layout: columns from right to left, each column top to bottom, the whole
poem written continuously and the block centred on each sheet. Each sheet is planned as a few
segments of whole columns so every plan stays well inside the planner's node budget; the
segments of one sheet are written back to back without changing paper.
"""
import json
import math
import sqlite3
from functools import lru_cache
from pathlib import Path
from . import glyph_store
from .curves import BrushCurve
from .presets import profile, VERSION, binding
from .composer import digest

DATA = Path(__file__).resolve().parents[1] / 'data/calligraphy/poems'
SCHEMA = 'brush-poem-v1'
LAYOUT_VERSION = 'poem-ttb-rtl-20261026-v1'
SIZES = (40, 50, 60, 70)
# 2026-10-27: the screen writes poems at a fixed 70 mm and 100 % speed; each segment is
# planned once and kept on the board (tcb705/plan_store.py). SIZES stay for layout checks.
POEM_SIZE_MM = 70
DEFAULT_SIZE = POEM_SIZE_MM
SPEED_PCT = 100
MARGIN_MM = 10.
# Characters per plan segment, measured offline: about 1 300-2 230 nodes per character
# depending on size, kept near 20 000 nodes (the planner limit is 30 000).
SEGMENT_CHARS = {40: 12, 50: 10, 60: 8, 70: 6}


@lru_cache(maxsize=1)
def library():
    doc = json.loads((DATA / 'poems.json').read_text(encoding='utf-8'))
    if doc.get('schema') != 'poems-v1':
        raise ValueError('诗词库格式错误')
    seen = set()
    for p in doc['items']:
        n = len(p['lines'][0])
        if p['id'] in seen or len(p['lines']) != 4 or n not in (5, 7) or any(len(l) != n for l in p['lines']):
            raise ValueError('诗词库条目无效：' + p['id'])
        missing = ''.join(c for c in ''.join(p['lines']) if not has_glyph(c))
        if missing:
            raise ValueError('《%s》有字库未收录的字：%s' % (p['title'], missing))
        seen.add(p['id'])
    return doc


@lru_cache(maxsize=1)
def _supplement():
    path = DATA / 'supplement.sqlite'
    if not path.is_file():
        return {}, dict(version='none', characters='')
    con = sqlite3.connect('file:%s?mode=ro' % path.as_posix(), uri=True)
    try:
        rows = dict(con.execute('SELECT character, payload FROM glyphs'))
        meta = json.loads(con.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
    finally:
        con.close()
    return rows, meta


def has_glyph(ch):
    return ch in glyph_store.manifest('kai')['characters'] or ch in _supplement()[0]


@lru_cache(maxsize=256)
def _supplement_glyph(ch):
    return json.loads(_supplement()[0][ch])


def glyph(ch):
    if ch in glyph_store.manifest('kai')['characters']:
        return glyph_store.glyph(ch, 'kai')
    if ch in _supplement()[0]:
        return _supplement_glyph(ch)
    raise ValueError('字库未收录：' + ch)


def poem(poem_id):
    for p in library()['items']:
        if p['id'] == poem_id:
            return p
    raise ValueError('未找到这首诗')


def text(poem_id):
    return ''.join(poem(poem_id)['lines'])


def size_of(size_mm):
    if type(size_mm) not in (int, float) or size_mm not in SIZES:
        raise ValueError('字号只能选 40、50、60、70 mm')
    return int(size_mm)


def grid(size, paper):
    s = float(size); gy = max(4., s * .1); gx = max(6., s * .2)
    W, H = float(paper['width_mm']), float(paper['height_mm'])
    rows = math.floor((H - 2 * MARGIN_MM + gy) / (s + gy)); cols = math.floor((W - 2 * MARGIN_MM + gx) / (s + gx))
    if rows < 1 or cols < 1:
        raise ValueError('当前标定纸面放不下 %d mm 的字，请换小一档字号' % size)
    return rows, cols, gx, gy, W, H


def layout(poem_id, size_mm, paper):
    size = size_of(size_mm); body = text(poem_id)
    rows, cols, gx, gy, W, H = grid(size, paper)
    per = rows * cols; pages = []
    for start in range(0, len(body), per):
        chunk = body[start:start + per]
        used = math.ceil(len(chunk) / rows); r_used = min(rows, len(chunk))
        bw = used * size + (used - 1) * gx; bh = r_used * size + (r_used - 1) * gy
        x0 = (W - bw) / 2; y0 = (H - bh) / 2
        cells = [dict(character=ch, text_index=start + i, column=i // rows, row=i % rows,
                      x_mm=round(x0 + (used - 1 - i // rows) * (size + gx), 6), y_mm=round(y0 + (i % rows) * (size + gy), 6))
                 for i, ch in enumerate(chunk)]
        pages.append(cells)
    return dict(poem_id=poem_id, font_size_mm=size, width_mm=W, height_mm=H, rows=rows, columns=cols,
                pages=pages, page_count=len(pages), segments=[segments(p, size, rows) for p in pages],
                direction='ttb_columns_rtl', layout_version=LAYOUT_VERSION, library_version=library()['version'])


def segments(cells, size, rows):
    """Whole columns per segment, right to left, at most SEGMENT_CHARS[size] characters each."""
    per = max(1, SEGMENT_CHARS[size] // rows) * rows
    return [[c['text_index'] for c in cells[i:i + per]] for i in range(0, len(cells), per)]


def sheets(poem_id, paper):
    out = {}
    for s in SIZES:
        try:
            out[str(s)] = layout(poem_id, s, paper)['page_count']
        except ValueError:
            out[str(s)] = None
    return out


def catalog(paper):
    return [dict(id=p['id'], title=p['title'], author=p['author'], dynasty=p['dynasty'], form=p['form'],
                 lines=p['lines'], sheets=sheets(p['id'], paper)) for p in library()['items']]


def revision(config):
    return digest(dict(calibration=binding(config), brush=profile(config), module_version=VERSION,
                       glyph_version=glyph_store.manifest('kai')['version'], supplement_version=_supplement()[1]['version'],
                       layout_version=LAYOUT_VERSION, library_version=library()['version']))


def task(poem_id, size_mm, page_index, segment_index, config):
    doc = layout(poem_id, size_mm, config['paper'])
    if type(page_index) is not int or not 0 <= page_index < doc['page_count']:
        raise ValueError('页码无效')
    segs = doc['segments'][page_index]
    if type(segment_index) is not int or not 0 <= segment_index < len(segs):
        raise ValueError('分段无效')
    wanted = set(segs[segment_index])
    p = profile(config); paths = []; depths = []; feeds = []; mapping = []
    scale = doc['font_size_mm'] / 50.
    for cell in doc['pages'][page_index]:
        if cell['text_index'] not in wanted:
            continue
        for index, stroke in enumerate(glyph(cell['character'])['strokes']):
            dense = BrushCurve(stroke['points']).sample(scale)
            path = [[round(a[0] * scale + cell['x_mm'], 6), round(a[1] * scale + cell['y_mm'], 6)] for a in dense]
            if any(not 0 <= x <= doc['width_mm'] or not 0 <= y <= doc['height_mm'] for x, y in path):
                raise ValueError('字形越出标定纸面')
            paths.append(path); depths.append([round(a[2] * p['max_press_mm'], 8) for a in dense])
            feeds.append([a[3] for a in dense])
            mapping.append(dict(character=cell['character'], text_index=cell['text_index'], stroke_index=index))
    meta = dict(schema=SCHEMA, module='poem', version=VERSION, brush=p, poem_id=poem_id, font_size_mm=doc['font_size_mm'],
                page_index=page_index, page_count=doc['page_count'], segment_index=segment_index, segment_count=len(segs),
                style='kai', glyph_version=glyph_store.manifest('kai')['version'], supplement_version=_supplement()[1]['version'],
                layout_version=LAYOUT_VERSION, library_version=doc['library_version'], revision=revision(config),
                stroke_map=mapping, depth_mm=depths, feed_ratio=feeds)
    meta['content_digest'] = digest({k: v for k, v in meta.items() if k not in ('depth_mm', 'feed_ratio')})
    return dict(units='mm', width_mm=doc['width_mm'], height_mm=doc['height_mm'],
                coordinate_system='full_canvas_xy_down', paths=paths, calligraphy=meta)


def preview_svg(poem_id, size_mm, config, page_index=0):
    """Authored 楷书 strokes of one sheet (for the picker and confirmation; not an FK prediction)."""
    doc = layout(poem_id, size_mm, config['paper']); scale = doc['font_size_mm'] / 50.
    W, H = doc['width_mm'], doc['height_mm']; out = []
    for cell in doc['pages'][page_index]:
        for stroke in glyph(cell['character'])['strokes']:
            pts = BrushCurve(stroke['points']).sample(scale, step_mm=1, tolerance_mm=.05, compression_step=.1, feed_step=.2)
            for a, b in zip(pts, pts[1:]):
                out.append('<path d="M%.2f %.2fL%.2f %.2f" stroke-width="%.2f"/>'
                           % (a[0] * scale + cell['x_mm'], a[1] * scale + cell['y_mm'], b[0] * scale + cell['x_mm'],
                              b[1] * scale + cell['y_mm'], .9 + 4.2 * (a[2] + b[2]) / 2 * scale / 1.4))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %g %g"><rect width="%g" height="%g" fill="#fffaf0"/>'
            '<g fill="none" stroke="#14100d" stroke-linecap="round">%s</g></svg>' % (W, H, W, H, ''.join(out))).encode()
