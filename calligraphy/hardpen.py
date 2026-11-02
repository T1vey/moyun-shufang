"""硬笔书法 (2026-10-27): hard-pen 正楷 from data/calligraphy/hardpen/glyphs.sqlite.

The hard pen is the third tool (画笔 / 毛笔 / 硬笔) with its own calibration in
config['hardpen']: the flange Z where the pen tip touches the paper (contact_z_mm) and a
small constant press (press_mm) taken up by the spring holder. A hard-pen task is written
on the calibrated paper at that height; its keyframe press (0..1) scales press_mm.

task() places one line of characters at the centre of the paper: the 硬笔试写 of the
settings page. The full layout (pages, lines, vertical text) comes with the phone mode.
"""
import json
import sqlite3
from contextlib import closing
from functools import lru_cache
from pathlib import Path

from .composer import digest
from .curves import BrushCurve
from .presets import binding, number

DB = Path(__file__).resolve().parents[1] / 'data/calligraphy/hardpen/glyphs.sqlite'
SCHEMA = 'hardpen-text-v1'
VERSION = 'hardpen-v1-20261027'
SIZES = (10, 15, 20)                  # 1 cm / 1.5 cm / 2 cm
SPEEDS = (70, 85, 100)
PRESS_MM = 0.5                        # default press below first touch (spring holder)
MAX_PRESS_MM = 2.0
PEN_MM = 0.5                          # line width of the 0.5 mm gel pen (preview only)
GAP = 0.2                             # character spacing, in character heights
# Execution floor below the lowest planned point. The spring holder gives about 3 mm, and a
# 70 % run dipped 0.503 mm at a press-in corner (2026-10-27), so the general 0.5 mm stopped it.
BELOW_PAPER_MM = 1.0
# Short pieces for the screen (2026-10-27): only those the current library can write are offered.
PRESETS = ('永', '书法', '春夏秋冬', '万水千山', '大好河山', '东西南北', '日月光明', '天地人和', '上下左右', '道德经')


def presets():
    return [p for p in PRESETS if not missing(p)]


def preview_svg(text, size_mm, config):
    """The line as the pen will write it (its own paths, never a browser font), on the paper."""
    t = task(text, size_mm, config); W, H = t['width_mm'], t['height_mm']
    lines = []
    for path, depths in zip(t['paths'], t['calligraphy']['depth_mm']):
        pts = [(x, y) for (x, y), d in zip(path, depths) if d > 0.02]
        if len(pts) > 1:
            lines.append('<polyline points="%s"/>' % ' '.join('%.2f,%.2f' % p for p in pts))
    # Framed on the line itself (half a character around it) so 1 cm characters stay legible.
    xs = [x for p in t['paths'] for x, _ in p]; ys = [y for p in t['paths'] for _, y in p]
    m = 0.5 * t['calligraphy']['font_size_mm']
    x0, y0, x1, y1 = min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%.2f %.2f %.2f %.2f"><rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#fffaf0"/>'
            '<g fill="none" stroke="#1f1a16" stroke-width="%.2f" stroke-linecap="round" stroke-linejoin="round">%s</g></svg>'
            % (x0, y0, x1 - x0, y1 - y0, x0, y0, x1 - x0, y1 - y0, PEN_MM, ''.join(lines))).encode()


def work_key(text, size_mm):
    """Store key of one piece: the same text at the same size reuses its saved commands."""
    import hashlib
    return 'hp_' + hashlib.sha1(('%s|%d' % (text, size_mm)).encode('utf-8')).hexdigest()[:20]


@lru_cache(maxsize=1)
def manifest():
    if not DB.exists():
        raise ValueError('未安装硬笔字库')
    with closing(sqlite3.connect(DB.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        return json.loads(con.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])


@lru_cache(maxsize=512)
def _glyph(ch):
    with closing(sqlite3.connect(DB.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        row = con.execute('SELECT payload FROM glyphs WHERE character=?', (ch,)).fetchone()
    if row is None:
        raise ValueError('硬笔字库缺少「%s」' % ch)
    return json.loads(row[0])


def missing(text):
    """Characters of text the library cannot write (spaces are allowed)."""
    out = []
    for ch in text:
        if ch.isspace() or ch in out:
            continue
        try:
            _glyph(ch)
        except ValueError:
            out.append(ch)
    return out


def profile(config, require_verified=False):
    """The hard-pen calibration as part of the plan identity (the press is geometry)."""
    p = config.get('hardpen', {})
    press = number(p.get('press_mm', PRESS_MM), 0, MAX_PRESS_MM, '硬笔下压量 (mm)')
    verified = p.get('verified') is True and p.get('calibration_binding') == binding(config)
    if require_verified and (not verified or p.get('contact_z_mm') is None):
        raise ValueError('请先在设置中标定硬笔落笔高度')
    out = dict(tool='hardpen', pen_mm=PEN_MM, max_press_mm=press, verified=verified)
    if p.get('contact_z_mm') is not None:
        out['contact_z_mm'] = number(p['contact_z_mm'], 0, 1000, '硬笔落笔 Z (mm)')
    return out


def revision(config):
    return digest(dict(calibration=binding(config), hardpen=profile(config), module_version=VERSION,
                       glyph_version=manifest()['version']))


def size_of(size_mm):
    if type(size_mm) not in (int, float) or size_mm not in SIZES:
        raise ValueError('硬笔字号只能选 1、1.5、2 cm')
    return int(size_mm)


def task(text, size_mm, config):
    """One line of hard-pen characters centred on the paper (the settings page test write)."""
    size = size_of(size_mm)
    text = ''.join(ch for ch in str(text or '') if not ch.isspace())
    if not 1 <= len(text) <= 20:
        raise ValueError('试写请输入 1～20 个字')
    bad = missing(text)
    if bad:
        raise ValueError('硬笔字库缺少：' + ''.join(bad))
    W, H = float(config['paper']['width_mm']), float(config['paper']['height_mm'])
    width = len(text) * size + (len(text) - 1) * GAP * size
    if width + 20 > W or size + 20 > H:
        raise ValueError('纸面放不下这一行，请减少字数或改小字号')
    x0, y0 = (W - width) / 2, (H - size) / 2
    p = profile(config); scale = size / 50.
    paths, depths, feeds, mapping = [], [], [], []
    for i, ch in enumerate(text):
        cx = x0 + i * size * (1 + GAP)
        for k, stroke in enumerate(_glyph(ch)['strokes']):
            dense = BrushCurve(stroke['points']).sample(scale)
            paths.append([[round(a[0] * scale + cx, 6), round(a[1] * scale + y0, 6)] for a in dense])
            depths.append([round(a[2] * p['max_press_mm'], 8) for a in dense])
            feeds.append([a[3] for a in dense])
            mapping.append(dict(character=ch, text_index=i, stroke_index=k, kind=stroke.get('kind')))
    meta = dict(schema=SCHEMA, module='hardpen', version=VERSION, brush=p, text=text, font_size_mm=size,
                glyph_version=manifest()['version'], revision=revision(config), stroke_map=mapping,
                depth_mm=depths, feed_ratio=feeds)
    meta['content_digest'] = digest({k: v for k, v in meta.items() if k not in ('depth_mm', 'feed_ratio')})
    return dict(units='mm', width_mm=W, height_mm=H, coordinate_system='full_canvas_xy_down',
                paths=paths, calligraphy=meta)


# ---- 手机硬笔 (2026-10-29): several lines, 横排 / 竖排, over pages -------------------------------
# The phone sends any text (newlines kept, punctuation left as a blank cell, since the library
# has none). A line is cut into plan units of consecutive characters that stay inside the
# planner's node budget (a full line of complex characters does not), each saved under the
# piece's work key with index = unit, so the same piece is written again from its saved commands.
DOC_SCHEMA = 'hardpen-doc-v1'
DOC_VERSION = 'hardpen-doc-20261029-v2'
LAYOUTS = {'h': '横排', 'v': '竖排'}  # h: rows left to right, top down; v: columns top down, right to left
LINE_GAP = 0.6                        # between lines, in character heights
MARGIN_MM = 10.
MAX_DOC_CHARS = 300
MAX_LINES = 99
MAX_UNITS = 99                        # plan_store index
# Estimated planner nodes per unit (max_nodes is 30 000, max_frames 800 000; a poem segment of
# ~13 000 nodes plans on the board). Offline with the board config (2026-10-29) the real nodes
# were 0.97-1.26 x the estimate, so a unit stays near 12 600 nodes and 420 000 frames.
UNIT_NODES = 10000
DRAW_STEP_MM, SAMPLE_STEP_MM, TRAVEL_STEP_MM, LIFT_NODES = 0.4, 0.35, 0.5, 32
PRESS_STEP, FEED_STEP = 0.035, 0.04
PUNCT = set('，。、；：？！“”‘’「」『』（）《》〈〉【】…—～·,.;:?!()[]<>"\'`-_~/\\|')


@lru_cache(maxsize=4096)
def char_cost(ch, size):
    """Planner nodes one character needs, estimated like planner.line(): drawn length at 0.4 mm
    plus one per sample point (every 0.35 mm, and every 0.035 of press or 0.04 of feed change,
    as BrushCurve.sample), a lift and a lower of 8 mm per stroke and a travel of about one
    character. Taken from the keyframes, so a long piece lays out at once on the board."""
    scale = size / 50.; nodes = 0.
    for stroke in _glyph(ch)['strokes']:
        p = stroke['points']
        length = sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** .5 for a, b in zip(p, p[1:])) * scale
        press = sum(abs(b[2] - a[2]) for a, b in zip(p, p[1:])); feed = sum(abs(b[3] - a[3]) for a, b in zip(p, p[1:]))
        nodes += (length * (1 / DRAW_STEP_MM + 1 / SAMPLE_STEP_MM) + press / PRESS_STEP + feed / FEED_STEP
                  + LIFT_NODES + size / TRAVEL_STEP_MM)
    return int(nodes + 1)


def normalize_doc(text):
    s = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
    s = ''.join('\n' if ch == '\n' else ' ' if ch.isspace() or ch in PUNCT else ch for ch in s)
    return '\n'.join(p.rstrip() for p in s.split('\n')).strip('\n')


def doc_key(text, size_mm, layout):
    import hashlib
    return 'hp_d' + hashlib.sha1(('%s|%d|%s|%s' % (text, size_mm, layout, DOC_VERSION)).encode('utf-8')).hexdigest()[:19]


def doc_layout(text, size_mm, layout, paper):
    """Lines and pages of a phone piece on the paper (x right, y down, like the other modes)."""
    size = size_of(size_mm)
    if layout not in LAYOUTS:
        raise ValueError('排版只能选横排或竖排')
    text = normalize_doc(text)
    count = sum(1 for ch in text if not ch.isspace())
    if not 1 <= count <= MAX_DOC_CHARS:
        raise ValueError('请输入 1～%d 个字' % MAX_DOC_CHARS)
    bad = missing(text)
    if bad:
        raise ValueError('硬笔字库缺少：' + ''.join(bad[:20]) + ('…' if len(bad) > 20 else ''))
    W, H = float(paper['width_mm']), float(paper['height_mm'])
    pitch, lpitch = size * (1 + GAP), size * (1 + LINE_GAP)
    along, across = (W, H) if layout == 'h' else (H, W)
    per_line = int((along - 2 * MARGIN_MM + GAP * size) // pitch + 1e-9)
    per_page = int((across - 2 * MARGIN_MM + LINE_GAP * size) // lpitch + 1e-9)
    if per_line < 1 or per_page < 1:
        raise ValueError('纸面太小，请改小字号')
    rows = []
    for para in text.split('\n'):
        if not para.strip():
            rows.append('')
            continue
        while para:
            rows.append(para[:per_line])
            para = para[per_line:].lstrip(' ')
    if len(rows) > MAX_LINES:
        raise ValueError('一次最多 %d 行，请减少文字或改小字号' % MAX_LINES)
    run = per_line * pitch - GAP * size          # length of a full line
    block = per_page * lpitch - LINE_GAP * size  # depth of a full page of lines
    lines, pages, k = [], [], 0
    for g, row in enumerate(rows):
        page, r = divmod(g, per_page)
        if r == 0:
            pages.append([])
        cells = []
        for i, ch in enumerate(row):
            if layout == 'h':
                x, y = (W - run) / 2 + i * pitch, (H - block) / 2 + r * lpitch
            else:
                x, y = (W + block) / 2 - size - r * lpitch, (H - run) / 2 + i * pitch
            if not ch.isspace():
                cells.append(dict(character=ch, text_index=k, x_mm=round(x, 6), y_mm=round(y, 6)))
                k += 1
        lines.append(dict(index=g, page=page, row=r, text=row, cells=cells))
        pages[-1].append(g)
    # Plan units: consecutive characters of one line within UNIT_NODES, in writing order.
    units, page_units = [], [[] for _ in pages]
    for line in lines:
        cost = 0
        for cell in line['cells']:
            c = char_cost(cell['character'], size)
            if not units or units[-1]['line'] != line['index'] or cost + c > UNIT_NODES:
                units.append(dict(index=len(units), page=line['page'], line=line['index'], cells=[]))
                page_units[line['page']].append(len(units) - 1); cost = 0
            units[-1]['cells'].append(cell); cost += c
    if len(units) > MAX_UNITS:
        raise ValueError('内容太多，请减少文字或改小字号')
    return dict(text=text, font_size_mm=size, layout=layout, layout_label=LAYOUTS[layout], characters=count,
                width_mm=W, height_mm=H, per_line=per_line, per_page=per_page, lines=lines, pages=pages,
                line_count=len(lines), page_count=len(pages), units=units, page_units=page_units, unit_count=len(units),
                layout_version=DOC_VERSION)


def doc_info(doc):
    """What the 硬笔作品库 keeps with each saved unit, to list and write the piece again."""
    return dict(text=doc['text'], font_size_mm=doc['font_size_mm'], layout=doc['layout'], line_count=doc['line_count'],
                page_count=doc['page_count'], unit_count=doc['unit_count'], layout_version=DOC_VERSION)


def _strokes(cell, size, sample=None):
    scale = size / 50.
    for k, stroke in enumerate(_glyph(cell['character'])['strokes']):
        dense = BrushCurve(stroke['points']).sample(scale, **(sample or {}))
        yield k, stroke, [[a[0] * scale + cell['x_mm'], a[1] * scale + cell['y_mm']] + list(a[2:]) for a in dense]


def unit_task(text, size_mm, layout, unit_index, config):
    """One plan unit (characters of one line) of a phone piece, on the paper at the hard pen's height."""
    doc = doc_layout(text, size_mm, layout, config['paper'])
    if type(unit_index) is not int or not 0 <= unit_index < doc['unit_count']:
        raise ValueError('序号无效')
    unit = doc['units'][unit_index]; size = doc['font_size_mm']
    p = profile(config); paths, depths, feeds, mapping = [], [], [], []
    for cell in unit['cells']:
        for k, stroke, dense in _strokes(cell, size):
            path = [[round(a[0], 6), round(a[1], 6)] for a in dense]
            if any(not 0 <= x <= doc['width_mm'] or not 0 <= y <= doc['height_mm'] for x, y in path):
                raise ValueError('字形越出已标定纸面')
            paths.append(path)
            depths.append([round(a[2] * p['max_press_mm'], 8) for a in dense])
            feeds.append([a[3] for a in dense])
            mapping.append(dict(character=cell['character'], text_index=cell['text_index'], stroke_index=k, kind=stroke.get('kind')))
    meta = dict(schema=DOC_SCHEMA, module='hardpen', version=VERSION, brush=p, text=doc['text'], font_size_mm=size,
                layout=doc['layout'], layout_version=DOC_VERSION, unit_index=unit_index, unit_count=doc['unit_count'],
                line_index=unit['line'], page_index=unit['page'], page_count=doc['page_count'], glyph_version=manifest()['version'],
                revision=revision(config), stroke_map=mapping, depth_mm=depths, feed_ratio=feeds)
    meta['content_digest'] = digest({k: v for k, v in meta.items() if k not in ('depth_mm', 'feed_ratio')})
    return dict(units='mm', width_mm=doc['width_mm'], height_mm=doc['height_mm'], coordinate_system='full_canvas_xy_down',
                paths=paths, calligraphy=meta)


def doc_preview(text, size_mm, layout, config, only=None):
    """Layout plus the pen lines of every page (or only page `only`; on paper only), for the
    phone and the screen."""
    doc = doc_layout(text, size_mm, layout, config['paper'])
    quick = dict(step_mm=2, tolerance_mm=.2, compression_step=.5, feed_step=.5)   # a picture, not the plan
    pages = []
    for index, page in enumerate(doc['pages']):
        out = []
        for g in page if only is None or only == index else ():
            for cell in doc['lines'][g]['cells']:
                for _, _, dense in _strokes(cell, doc['font_size_mm'], quick):
                    pts = [[round(a[0], 1), round(a[1], 1)] for a in dense if a[2] > 0.02]
                    if len(pts) > 1:
                        out.append(pts)
        pages.append(out)
    doc['preview_pages'] = pages
    doc['revision'] = revision(config)
    return doc


def doc_preview_svg(text, size_mm, layout, config, page=0):
    doc = doc_preview(text, size_mm, layout, config, only=page)
    if type(page) is not int or not 0 <= page < doc['page_count']:
        raise ValueError('页码无效')
    W, H = doc['width_mm'], doc['height_mm']
    lines = ''.join('<polyline points="%s"/>' % ' '.join('%.1f,%.1f' % (x, y) for x, y in s) for s in doc['preview_pages'][page])
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %g %g"><rect width="%g" height="%g" fill="#fffaf0"/>'
            '<g fill="none" stroke="#1f1a16" stroke-width="%.2f" stroke-linecap="round" stroke-linejoin="round">%s</g></svg>'
            % (W, H, W, H, max(PEN_MM, 0.004 * W), lines)).encode()
