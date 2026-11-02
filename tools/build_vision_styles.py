"""Build per-style recognition templates from calligraphy fonts (one process per style).

Output: data/vision/styles/<style>.bin/.json and data/vision/styles.json (index).
The Arphic KaiTi outline set (data/vision/templates_v3.bin) is listed as kai_arphic.
Fonts are only rendered to features here; the font files themselves are not shipped.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WIN = Path('C:/Windows/Fonts')
OFL = ROOT.parent / 'fonts_ofl'
STYLES = [   # name, label, category, font file
    ('kai_simkai', '楷体', '楷书', WIN / 'simkai.ttf'),
    ('kai_stkaiti', '华文楷体', '楷书', WIN / 'STKAITI.TTF'),
    ('kai_mashanzheng', '马善政楷书', '楷书', OFL / 'MaShanZheng-Regular.ttf'),
    ('kai_lxgw', '霞鹜文楷', '楷书', OFL / 'LXGWWenKai-Regular.ttf'),
    ('xing_stxingka', '华文行楷', '行书', WIN / 'STXINGKA.TTF'),
    ('xing_fzstk', '方正舒体', '行书', WIN / 'FZSTK.TTF'),
    ('xing_zhimang', '志莽行书', '行书', OFL / 'ZhiMangXing-Regular.ttf'),
    ('xing_longcang', '龙藏体', '行书', OFL / 'LongCang-Regular.ttf'),
    ('cao_liujianmaocao', '刘建毛草', '草书', OFL / 'LiuJianMaoCao-Regular.ttf'),
    ('li_simli', '隶书', '隶书', WIN / 'SIMLI.TTF'),
    ('li_stliti', '华文隶书', '隶书', WIN / 'STLITI.TTF'),
    ('wei_stxinwei', '华文新魏', '魏碑', WIN / 'STXINWEI.TTF'),
]


def one(args):
    name, label, font, chars, out = args
    from brush_vision import templates
    started = time.perf_counter()
    meta = templates.build_font_style(chars, font, name, label, out)
    return name, meta['present'], meta['calibration']['self_top1'], round(time.perf_counter() - started)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=ROOT / 'data/vision')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--jobs', type=int, default=12)
    a = ap.parse_args()
    from calligraphy import glyph_store
    chars = glyph_store.manifest()['characters'][:a.limit or None]
    jobs = [(n, l, str(f), chars, str(a.out / 'styles' / (n + '.bin'))) for n, l, _, f in STYLES]
    with ProcessPoolExecutor(a.jobs) as pool:
        for name, present, top1, sec in pool.map(one, jobs):
            print(f'{name:18s} present {present} self_top1 {top1:.3f} {sec}s', flush=True)
    index = [dict(style='kai_arphic', label='Arphic 楷体', category='楷书', file='templates_v3.bin')]
    index += [dict(style=n, label=l, category=cat, file='styles/' + n + '.bin') for n, l, cat, _ in STYLES]
    (a.out / 'styles.json').write_text(json.dumps(dict(schema='brushrecog-styles-v1', styles=index),
                                                  ensure_ascii=False, indent=1), encoding='utf-8')
    print('STYLES', len(index))


if __name__ == '__main__':
    main()
