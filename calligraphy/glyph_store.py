"""Versioned read-only, bounded on-demand glyph access. No robot dependencies.

楷书 is the original Make Me a Hanzi library; 行书/草书/隶书/篆书 are optional
per-style libraries in data/calligraphy/styles (tools/build_style_glyphs.py).
名帖表演 libraries (style 'mp_<work>') hold one famous sentence each, looked up by
character position (tools/build_masterpieces.py).
"""
import copy
from contextlib import closing
from functools import lru_cache
import json
from pathlib import Path
import re
import sqlite3

DATABASE = Path(__file__).resolve().parents[1]/'data/calligraphy/glyphs.sqlite'
STYLE_DIR = DATABASE.parent/'styles'
MASTER_DIR = DATABASE.parent/'masterpieces'
STYLES = {'kai':'楷书','xing':'行书','cao':'草书','li':'隶书','zhuan':'篆书'}


def is_masterpiece(style):
    return isinstance(style,str) and re.fullmatch(r'mp_[a-z0-9]{1,24}',style) is not None


def database(style='kai'):
    if is_masterpiece(style):return MASTER_DIR/style[3:]/'glyphs.sqlite'
    if style not in STYLES:raise ValueError('不支持的书体')
    return DATABASE if style=='kai' else STYLE_DIR/(style+'.sqlite')


def label(style):
    return STYLES[style] if style in STYLES else manifest(style)['label']


def masterpieces():
    """Installed masterpiece styles, in the order of tools/build_masterpieces.py (manifest 'order')."""
    if not MASTER_DIR.is_dir():return []
    found=[]
    for db in MASTER_DIR.glob('*/glyphs.sqlite'):
        style='mp_'+db.parent.name
        if not is_masterpiece(style):continue
        try:found.append((manifest(style).get('order',99),style))
        except ValueError:continue                      # a damaged optional library is not offered
    return [s for _,s in sorted(found)]


def available():
    """Styles whose library is installed, in display order (楷书 always first)."""
    return [s for s in STYLES if s=='kai' or database(s).exists()]


def _read(query, values=(), style='kai'):
    path=database(style)
    if not path.exists():raise ValueError('未安装%s字库'%STYLES.get(style,'名帖'))
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as con:
        row=con.execute(query,values).fetchone()
    if row is None:raise ValueError('当前字库缺少记录：'+''.join(values))
    return json.loads(row[0])


@lru_cache(maxsize=32)
def _manifest(style='kai'):
    value=_read("SELECT value FROM metadata WHERE key='manifest'",style=style)
    count=value.get('count');chars=value.get('characters')
    if (value.get('schema')!='brush-glyphs-v1' or type(count) is not int or not 1<=count<=10000
            or not isinstance(chars,str) or len(chars)!=count or (len(set(chars))!=count and not value.get('positional'))
            or value.get('style','kai')!=style):
        raise ValueError('字库版本不兼容或收录清单损坏')
    with closing(sqlite3.connect(database(style).resolve().as_uri()+'?mode=ro',uri=True)) as con:
        actual={row[0] for row in con.execute('SELECT character FROM glyphs')}
    expected={'#%02d'%i for i in range(count)} if value.get('positional') else set(chars)
    if actual!=expected:raise ValueError('字库记录与收录清单不一致')
    return value


def manifest(style='kai'):return copy.deepcopy(_manifest(style))


@lru_cache(maxsize=128)
def _glyph(character, style='kai'):
    if character not in _manifest(style)['characters']:raise ValueError('%s字库未收录：'%STYLES[style]+character)
    return _read('SELECT payload FROM glyphs WHERE character=?',(character,),style)


def glyph(character, style='kai'):return copy.deepcopy(_glyph(character,style))


@lru_cache(maxsize=64)
def _glyph_at(style, index):
    m=_manifest(style)
    if not m.get('positional') or type(index) is not int or not 0<=index<m['count']:raise ValueError('名帖字序无效')
    return _read('SELECT payload FROM glyphs WHERE character=?',('#%02d'%index,),style)


def glyph_at(style, index):
    """Masterpiece glyph at a sentence position (repeated characters keep the master's own forms)."""
    return copy.deepcopy(_glyph_at(style,index))
