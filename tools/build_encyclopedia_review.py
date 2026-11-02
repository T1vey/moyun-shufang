"""Build the 书法百科 review copy (HTML for Edge print-to-PDF) straight from encyclopedia.json.

usage: python tools/build_encyclopedia_review.py out.html  (then print it to PDF)
"""
import html, json, sys
from pathlib import Path

ROOT = Path(r'D:\zhiliao\TCB705_ZYNQ-10-15\ZYNQArm')
doc = json.loads((ROOT / 'data/encyclopedia/encyclopedia.json').read_text(encoding='utf-8'))
STYLE = {'kai': '楷书', 'xing': '行书', 'cao': '草书', 'li': '隶书', 'zhuan': '篆书'}
WORKS = {'mp_lanting': '《兰亭集序》', 'mp_jizhi': '《祭侄文稿》', 'mp_hanshi': '《黄州寒食帖》', 'mp_shusu': '《蜀素帖》',
         'mp_qianzi': '《楷书千字文》', 'mp_chibi': '《赤壁赋》', 'mp_zhanghan': '《张翰帖》（临本）'}


def figure(f):
    t = f['type']
    if t == 'styles':
        return '「%s」字五种书体对照' % f['char']
    if t == 'masterpiece':
        return '名帖笔迹：' + WORKS[f['style']]
    if t == 'glyph':
        return '%s「%s」' % (STYLE[f['style']], f['chars'])
    if t == 'grid':
        return '米字格中的楷书「%s」' % f['char']
    if t == 'order':
        return '楷书「%s」按笔顺分色' % f['char']
    if t == 'column':
        return '竖排右起「%s」并钤印' % f['chars']
    if t == 'couplet':
        return '春联挂法：%s / %s / 横批%s' % (f['upper'], f['lower'], f['banner'])
    if t == 'stroke':
        return '笔画提按：' + '、'.join({'heng': '横', 'pie': '长撇', 'dian': '点', 'shu_chuilu': '垂露竖', 'shu_xuanzhen': '悬针竖',
                                       'shu_gou': '竖钩', 'ti': '提', 'duan_pie': '短撇', 'na': '捺', 'heng_zhe': '横折'}[m] for m in f['modules'])
    if t == 'timeline':
        return '朝代轴，突出：' + '、'.join([f['era']] if isinstance(f['era'], str) else f['era'])
    if t == 'seals':
        return '印章示意：朱文与白文「%s」' % f['chars']
    return '示意图：' + {'brush': '毛笔', 'ink': '墨锭', 'paper': '宣纸', 'stone': '砚台', 'four': '文房四宝',
                        'seal': '印石与印蜕', 'inkpad': '印泥盒'}[f['item']]


e = html.escape
entries = sum(len(c['entries']) for c in doc['categories'])
screens = sum(len(x['screens']) for c in doc['categories'] for x in c['entries'])
chars = sum(len(s['text']) for c in doc['categories'] for x in c['entries'] for s in x['screens'])
parts = []
n = 0
for ci, c in enumerate(doc['categories'], 1):
    parts.append('<h2 class="cat"><span class="n">%d</span>%s<small>%d 篇</small></h2>' % (ci, e(c['title']), len(c['entries'])))
    for x in c['entries']:
        n += 1
        rows = ''.join('<tr><td class="no">%d</td><td class="tx">%s<div class="fg">配图：%s</div></td><td class="ct">%d 字</td><td class="mk"></td></tr>'
                       % (i, e(s['text']), e(figure(s['figure'])), len(s['text'])) for i, s in enumerate(x['screens'], 1))
        parts.append('''<article><header><b class="id">%02d</b><span class="sl">%s</span><h3>%s</h3><span class="key">%s / %s</span></header>
<table><tr><th class="no">屏</th><th>正文</th><th class="ct">字数</th><th class="mk">批注</th></tr>%s</table>
<div class="verdict"><span>□ 通过</span><span>□ 修改后通过</span><span>□ 删除</span><span class="line">意见：</span></div></article>'''
                     % (n, e(x['seal']), e(x['title']), c['id'], x['id'], rows))

page = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>书法百科审读稿</title><style>
@page{size:A4;margin:14mm 13mm 14mm 13mm}
*{box-sizing:border-box}body{margin:0;font:10.5pt/1.65 "Microsoft YaHei",sans-serif;color:#1f1a16}
h1,h2,h3{font-family:"STKaiti","KaiTi",serif;font-weight:400}
.cover{height:262mm;display:flex;flex-direction:column;justify-content:center;padding:0 10mm;page-break-after:always}
.cover .seal{width:24mm;height:24mm;background:#b3261e;color:#fbeee0;display:grid;grid-template-columns:1fr 1fr;align-items:center;justify-items:center;
 font:26pt/11mm "STKaiti","KaiTi",serif;border-radius:2mm;margin-bottom:10mm;transform:rotate(-3deg);padding:1mm}
.cover h1{font-size:32pt;margin:0 0 3mm;letter-spacing:.08em}.cover p{margin:1.5mm 0;font-size:11pt;color:#4a4038}
.cover table{border-collapse:collapse;margin-top:8mm;font-size:10.5pt}.cover td{padding:1.5mm 6mm 1.5mm 0;vertical-align:top}.cover td:first-child{color:#7c6f61;white-space:nowrap}
.cover ol{margin:1mm 0 0;padding-left:5mm}
h2.cat{font-size:19pt;margin:6mm 0 3mm;padding-bottom:1.5mm;border-bottom:1.2pt solid #b3261e;display:flex;align-items:center;break-after:avoid}
h2.cat .n{display:inline-grid;place-items:center;width:9mm;height:9mm;background:#b3261e;color:#fbeee0;border-radius:1.2mm;margin-right:3mm;font-size:13pt}
h2.cat small{margin-left:auto;font:10pt "Microsoft YaHei";color:#7c6f61}
h2.cat:not(:first-of-type){page-break-before:always}
article{border:1pt solid #cdbb98;border-radius:1.5mm;margin:0 0 4mm;break-inside:avoid;background:#fff}
article header{display:flex;align-items:baseline;padding:2mm 3mm;background:#f6efe0;border-bottom:.6pt solid #cdbb98}
article .id{font:600 9.5pt Consolas,monospace;color:#b3261e;margin-right:2.5mm}article h3{margin:0;font-size:14.5pt}
article .fig{margin-left:4mm;font-size:9pt;color:#4a4038}article .key{margin-left:auto;font:8.5pt Consolas,monospace;color:#9a8c78}
table{width:100%;border-collapse:collapse}th,td{border-bottom:.5pt solid #e6dac2;padding:1.6mm 2.5mm;vertical-align:top;text-align:left}
th{font-size:8.5pt;color:#7c6f61;font-weight:600;background:#fbf7ee}
td.tx{font-size:11pt;line-height:1.75}.no{width:8mm;text-align:center;color:#7c6f61}.ct{width:13mm;color:#9a8c78;font-size:8.5pt;white-space:nowrap}
.mk{width:52mm;border-left:.5pt dashed #cdbb98}
.fg{margin-top:1mm;font-size:8.8pt;color:#7a5a3a}
article .sl{display:inline-grid;place-items:center;width:7mm;height:7mm;border:1pt solid #1f1a16;border-radius:50%;font:12pt "STKaiti","KaiTi",serif;margin-right:2.5mm}
.verdict{display:flex;align-items:center;padding:1.6mm 3mm;font-size:9.5pt;color:#4a4038}.verdict span{margin-right:6mm}
.verdict .line{flex:1;border-bottom:.5pt solid #cdbb98;margin-right:0;padding-bottom:3mm}
</style></head><body>
<div class="cover"><div class="seal"><span>百</span><span>科</span><span>审</span><span>读</span></div>
<h1>书法百科 · 审读稿</h1><p>墨韵书坊 · 板子屏幕「书法百科」全部正文</p>
<table>
<tr><td>篇数</td><td>@CATS@ 个门类、@ENTRIES@ 篇、@SCREENS@ 屏，正文共 @CHARS@ 字；屏幕上每次显示一屏，每屏左侧配一幅图</td></tr>
<tr><td>来源</td><td>工程文件 data/encyclopedia/encyclopedia.json（版本 @VERSION@），本稿由该文件直接生成，与屏幕显示的文字完全一致</td></tr>
<tr><td>审读重点</td><td><ol><li>史实、人名、作品名、朝代是否准确</li><li>说法有分歧处是否已用“相传”“一般认为”</li><li>文字是否通顺、适合参观者阅读</li><li>配图是否与文章相符</li></ol></td></tr>
<tr><td>怎么批</td><td>直接在每屏右侧“批注”栏写修改意见，每篇末尾勾选结论；改好后把稿子给我，我按批注改到工程里。每屏不超过 150 字（屏幕一页能放下的字数）。</td></tr>
<tr><td>日期</td><td>2026-10-26</td></tr>
</table></div>
@BODY@
</body></html>'''
for k, v in (('@CATS@', len(doc['categories'])), ('@ENTRIES@', entries), ('@SCREENS@', screens), ('@CHARS@', chars), ('@VERSION@', e(doc['version'])), ('@BODY@', ''.join(parts))):
    page = page.replace(k, str(v))
Path(sys.argv[1]).write_text(page, encoding='utf-8')
print(entries, screens)
