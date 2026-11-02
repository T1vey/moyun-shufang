"""书法百科: read-only articles and the keyframes their figures are drawn from.

Pure reading material; nothing here plans or moves the arm.
"""
import json
from functools import lru_cache
from pathlib import Path
from calligraphy import glyph_store

DATA = Path(__file__).resolve().parents[1] / 'data/encyclopedia/encyclopedia.json'
STYLES = ('kai', 'xing', 'cao', 'li', 'zhuan')
MAX_SCREEN_CHARS = 150
MAX_FIGURE_CHARS = 20
ERAS = ('商', '周', '秦', '汉', '魏晋', '南北朝', '隋唐', '宋', '元', '明', '清')
TOOLS = ('brush', 'ink', 'paper', 'stone', 'four', 'seal', 'inkpad')


@lru_cache(maxsize=1)
def content():
    doc = json.loads(DATA.read_text(encoding='utf-8'))
    if doc.get('schema') != 'encyclopedia-v2':
        raise ValueError('百科内容格式错误')
    return doc


def _keyframes(glyph):
    # 50-unit keyframes rounded for the picture; never used for motion.
    return [[[round(p[0], 1), round(p[1], 1), round(p[2], 2)] for p in s['points']] for s in glyph['strokes']]


def glyphs(style, chars=''):
    """Figure strokes: chars in one style library, or a masterpiece's whole sentence."""
    if glyph_store.is_masterpiece(style):
        if style not in glyph_store.masterpieces():
            raise ValueError('未找到该名帖')
        m = glyph_store.manifest(style)
        return dict(style=style, label=m['label'], chars=m['characters'], rows=3,
                    glyphs=[_keyframes(glyph_store.glyph_at(style, i)) for i in range(m['count'])])
    if style not in STYLES or style not in glyph_store.available():
        raise ValueError('不支持的书体')
    if not isinstance(chars, str) or not 1 <= len(chars) <= MAX_FIGURE_CHARS:
        raise ValueError('配图字数无效')
    known = set(glyph_store.manifest(style)['characters'])
    found = [c for c in chars if c in known]
    return dict(style=style, label=glyph_store.label(style), chars=''.join(found),
                glyphs=[_keyframes(glyph_store.glyph(c, style)) for c in found])


def styles_of(char):
    """Every installed style that has this character (for the five-style figures)."""
    if not isinstance(char, str) or len(char) != 1:
        return []
    return [s for s in STYLES if s in glyph_store.available() and char in glyph_store.manifest(s)['characters']]


def strokes(modules):
    """Basic brush strokes with their press ratios, for the 提按 / 笔法 pictures."""
    from calligraphy.library import STROKES
    from calligraphy.presets import preview_modules
    keys = [k for k in (modules or '').split(',') if k]
    if not 1 <= len(keys) <= 4 or any(k not in STROKES for k in keys):
        raise ValueError('未知笔画')
    return dict(strokes=[dict(id=k, name=STROKES[k][0], chains=[[list(p[:3]) for p in c] for c in preview_modules(k)])
                         for k in keys])
