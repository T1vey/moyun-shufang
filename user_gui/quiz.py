"""趣味测验: rounds of multiple-choice questions built from the encyclopedia, glyph libraries,
masterpieces, poems and couplets. Read-only screen content; it never plans or moves the arm.
"""
import json
import random
from functools import lru_cache
from pathlib import Path
from calligraphy import glyph_store

BANK = Path(__file__).resolve().parents[1] / 'data/encyclopedia/quiz.json'
STYLES = {'kai': '楷书', 'xing': '行书', 'cao': '草书', 'li': '隶书', 'zhuan': '篆书'}
ROUND = [('style', 3), ('masterpiece', 1), ('poem_next', 1), ('poem_author', 1), ('couplet', 1), ('knowledge', 3)]
WORKS = {'mp_lanting': ('兰亭集序', '王羲之'), 'mp_jizhi': ('祭侄文稿', '颜真卿'), 'mp_hanshi': ('黄州寒食帖', '苏轼'),
         'mp_shusu': ('蜀素帖', '米芾'), 'mp_qianzi': ('楷书千字文', '赵佶'), 'mp_chibi': ('赤壁赋', '赵孟頫'),
         'mp_zhanghan': ('张翰帖', '欧阳询')}
ENTRY_OF_WORK = {'mp_lanting': 'works/lanting-xu', 'mp_jizhi': 'works/jizhi-wengao', 'mp_hanshi': 'works/hanshi-tie',
                 'mp_shusu': 'works/shusu-tie', 'mp_qianzi': 'works/qianzi-wen', 'mp_chibi': 'works/chibi-fu',
                 'mp_zhanghan': 'works/zhanghan-tie'}
ENTRY_OF_STYLE = {'kai': 'scripts/regular', 'xing': 'scripts/running', 'cao': 'scripts/cursive', 'li': 'scripts/clerical',
                  'zhuan': 'scripts/seal'}


@lru_cache(maxsize=1)
def bank():
    doc = json.loads(BANK.read_text(encoding='utf-8'))
    if doc.get('schema') != 'quiz-v1':
        raise ValueError('测验题库格式错误')
    return doc


def _keyframes(glyph):
    return [[[round(p[0], 1), round(p[1], 1), round(p[2], 2)] for p in s['points']] for s in glyph['strokes']]


def _question(prompt, correct, wrong, explain, entry=None, figure=None, rng=random):
    options = [correct] + list(wrong)
    if len(options) != 4 or len(set(options)) != 4:
        raise ValueError('选项必须是四个不同的答案')
    rng.shuffle(options)
    return dict(prompt=prompt, options=options, answer=options.index(correct), explain=explain, entry=entry, figure=figure)


@lru_cache(maxsize=1)
def _style_chars():
    sets = {s: set(glyph_store.manifest(s)['characters']) for s in STYLES if s in glyph_store.available()}
    # Characters written in at least four styles, so every answer option is a real alternative.
    return sets, sorted(c for c in set.union(*sets.values()) if sum(c in v for v in sets.values()) >= 4)


def style_question(rng):
    sets, chars = _style_chars()
    ch = rng.choice(chars); style = rng.choice([s for s in sets if ch in sets[s]])
    wrong = rng.sample([STYLES[s] for s in STYLES if s != style], 3)
    return _question('这个字是什么书体？', STYLES[style], wrong, '这是「%s」字的%s写法。' % (ch, STYLES[style]),
                     ENTRY_OF_STYLE[style], dict(type='glyph', glyphs=[_keyframes(glyph_store.glyph(ch, style))]), rng)


def masterpiece_question(rng):
    works = [w for w in WORKS if w in glyph_store.masterpieces()]
    work = rng.choice(works); title, author = WORKS[work]
    m = glyph_store.manifest(work)
    figure = dict(type='masterpiece', glyphs=[_keyframes(glyph_store.glyph_at(work, i)) for i in range(m['count'])])
    others = [w for w in works if w != work]
    if rng.random() < .5:
        return _question('这幅名帖笔迹是哪位书法家写的？', author, rng.sample([WORKS[w][1] for w in others], 3),
                         '这是%s《%s》的名句笔迹。' % (author, title), ENTRY_OF_WORK[work], figure, rng)
    return _question('这句笔迹出自哪幅名帖？', '《%s》' % title, ['《%s》' % WORKS[w][0] for w in rng.sample(others, 3)],
                     '这是%s《%s》的名句「%s」。' % (author, title, m['characters']), ENTRY_OF_WORK[work], figure, rng)


def _poems():
    from calligraphy import poems
    return poems.library()['items']


def poem_next_question(rng):
    items = _poems(); p = rng.choice(items); i = rng.randrange(3)
    pool = [l for q in items if q['id'] != p['id'] and len(q['lines'][0]) == len(p['lines'][0]) for l in q['lines']]
    pool = [l for l in dict.fromkeys(pool) if l != p['lines'][i + 1]]
    return _question('「%s」的下一句是？' % p['lines'][i], p['lines'][i + 1], rng.sample(pool, 3),
                     '出自%s《%s》。' % (p['author'], p['title']), 'poetry/jueju', None, rng)


def poem_author_question(rng):
    items = _poems(); p = rng.choice(items); line = rng.choice(p['lines'])
    authors = sorted({q['author'] for q in items if q['author'] != p['author']})
    return _question('「%s」是哪位诗人的诗句？' % line, p['author'], rng.sample(authors, 3),
                     '出自%s%s的《%s》。' % (p['dynasty'], p['author'], p['title']), 'poetry/poets', None, rng)


def couplet_question(rng):
    from calligraphy import couplets
    items = couplets.catalog(); c = rng.choice(items)
    pool = [x['lower'] for x in items if x['id'] != c['id'] and len(x['lower']) == len(c['lower'])]
    return _question('上联「%s」，下联是哪一句？' % c['upper'], c['lower'], rng.sample(pool, 3),
                     '上联末字仄声、下联末字平声，横批「%s」。' % c['banner'], 'couplets/rules', None, rng)


def knowledge_questions(rng, n):
    out = []
    for k in rng.sample(bank()['items'], n):
        correct = k['options'][k['answer']]
        out.append(_question(k['question'], correct, [o for o in k['options'] if o != correct], k['explain'], k['entry'], None, rng))
    return out


def round_(seed=None):
    rng = random.Random(seed); out = []
    makers = dict(style=style_question, masterpiece=masterpiece_question, poem_next=poem_next_question,
                  poem_author=poem_author_question, couplet=couplet_question)
    for kind, n in ROUND:
        out += knowledge_questions(rng, n) if kind == 'knowledge' else [makers[kind](rng) for _ in range(n)]
    rng.shuffle(out)
    return dict(version=bank()['version'], questions=out)
