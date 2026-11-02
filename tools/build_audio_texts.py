"""Build public-domain reading texts from the existing poems and archived source HTML.

Offline after the source pages have been saved. Never changes handwriting glyphs.
"""
import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from opencc import OpenCC

ROOT = Path(__file__).resolve().parents[1]
SIMPLIFY = OpenCC('t2s')
URLS = {
    'lanting': 'https://zh.wikisource.org/zh-hans/蘭亭集序',
    'qianzi': 'https://zh.wikisource.org/zh-hans/千字文',
    'chibi_common': 'https://zh.wikisource.org/zh-hans/前赤壁賦',
    'jizhi': 'https://digitalarchive.npm.gov.tw/Collection/Detail/3?dep=P',
    'hanshi': 'https://digitalarchive.npm.gov.tw/Collection/Detail/14714?dep=P',
    'shusu': 'https://digitalarchive.npm.gov.tw/Collection/Detail/912?dep=P',
    'zhanghan': 'https://www.dpm.org.cn/collection/handwriting/234567.html',
}


def clean(s):
    s = re.sub(r'<(?:style|script)\b[^>]*>.*?</(?:style|script)>', '', s, flags=re.S)
    s = re.sub(r'<span class="variant-tooltip"[^>]*>.*?</span>', '', s, flags=re.S)
    s = re.sub(r'<sup\b[^>]*>.*?</sup>', '', s, flags=re.S)
    s = re.sub(r'<[^>]+>', '', s)
    s = re.sub(r'\s+', '', html.unescape(s))
    s = re.sub(r'〈[^〉]*〉', '', s)  # editorial variants are not part of the spoken text
    return SIMPLIFY.convert(s)


def museum(raw):
    match = re.search(r'<td>釋文\s*</td>\s*<td>(.*?)</td>', raw, re.S)
    if not match:
        raise ValueError('Museum transcription not found')
    return match.group(1)


def sentences(text):
    return [s for s in re.findall(r'[^。！？；]+[。！？；]?[”’」』]*', text) if s.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sources', type=Path, default=ROOT/'build/tcb705/audio_20261027/sources')
    ap.add_argument('--output', type=Path, default=ROOT/'data/audio/texts')
    a = ap.parse_args(); a.output.mkdir(parents=True, exist_ok=True)
    poems = json.loads((ROOT/'data/calligraphy/poems/poems.json').read_text(encoding='utf-8'))['items']
    items = []
    for p in poems:
        items.append(dict(id='poem_'+p['id'], category='poem', title=p['title'], author=p['author'],
                          dynasty=p['dynasty'], sentences=[x+('，' if i%2==0 else '。') for i,x in enumerate(p['lines'])],
                          source_url='', source_note='沿用项目诗词库正文；普通话合成，古音与多音字待人工试听。',
                          verification_status='project-text', source_file='data/calligraphy/poems/poems.json'))
    raw = {k:(a.sources/(k+'.html')).read_text(encoding='utf-8') for k in URLS}
    texts = {}
    texts['lanting'] = '永和九年，岁在癸丑，暮春之初，会于会稽山阴之兰亭，修禊事也。群贤毕至，少长咸集。此地有崇山峻岭，茂林修竹；又有清流激湍，映带左右。引以为流觞曲水，列坐其次。虽无丝竹管弦之盛，一觞一咏，亦足以畅叙幽情。是日也，天朗气清，惠风和畅；仰观宇宙之大，俯察品类之盛；所以游目骋怀，足以极视听之娱，信可乐也。夫人之相与，俯仰一世，或取诸怀抱，悟言一室之内，或因寄所托，放浪形骸之外。虽趣舍万殊，静躁不同，当其欣于所遇，暂得于己，快然自足，不知老之将至。及其所之既倦，情随事迁，感慨系之矣。向之所欣，俯仰之间已为陈迹，犹不能不以之兴怀；况修短随化，终期于尽。古人云：死生亦大矣。岂不痛哉！每览昔人兴感之由，若合一契，未尝不临文嗟悼，不能喻之于怀。固知一死生为虚诞，齐彭殇为妄作。后之视今，亦犹今之视昔，悲夫！故列叙时人，录其所述，虽世殊事异，所以兴怀，其致一也。后之览者，亦将有感于斯文。'
    q = raw['qianzi'].split('<div class="poem">',1)[1].split('</div>',1)[0]
    q = clean(q)
    if len(q) != 1000:
        raise ValueError('千字文正文必须正好一千字，当前为 '+str(len(q)))
    # Common modern glyph forms in the reading text; source HTML is retained for comparison.
    q = q.translate(str.maketrans({'珎':'珍','奈':'柰','崐':'昆','竸':'竞','暎':'映','䟽':'疏','𡓜':'墙','䜩':'宴','嚬':'颦'}))
    texts['qianzi'] = ''.join(q[i:i+4]+('，' if (i//4)%2==0 else '。') for i in range(0,1000,4))
    # The source page is prose; select its paragraph(s), not navigation or modern commentary.
    pars = [clean(x) for x in re.findall(r'<p\b[^>]*>(.*?)</p>',raw['chibi_common'],re.S)]
    start = next(i for i,p in enumerate(pars) if p.startswith('壬戌之秋'))
    end = next(i for i,p in enumerate(pars[start:],start) if '不知东方之既白' in p)
    texts['chibi'] = ''.join(pars[start:end+1])
    j = museum(raw['jizhi']).replace('（脫大字）','大')
    texts['jizhi'] = clean(re.sub(r'（[^）]*）','',j))
    h = museum(raw['hanshi']).replace('子（點去）。','').replace('雨（點去）。','')
    texts['hanshi'] = clean(h).removesuffix('右黄州寒食二首。')
    sh = museum(raw['shusu']).replace('霜（旁改作金）','金').replace('清清（一清字點去）','清').replace('迩業（業字點去）','迩')
    texts['shusu'] = clean(sh.split('元祐戊辰',1)[0])
    zh = '張翰字季鷹，吳郡人。有清才，善屬文，而縱任不拘，時人號之爲江東步兵。後謂同郡顧榮曰：天下紛紜，禍難未已。夫有四海之名者，求退良難。吾本山林間人，無望于時。子善以明防前，以智慮後。榮執其手愴然，翰因見秋風起，乃思吳中菰菜鱸魚，遂命駕而歸。'
    if '張翰字季鷹' not in raw['zhanghan']:
        raise ValueError('张翰帖来源没有预期释文')
    texts['zhanghan'] = clean(zh)
    labels = [('lanting','兰亭序','王羲之','东晋'),('jizhi','祭侄文稿','颜真卿','唐'),
              ('hanshi','寒食帖二首','苏轼','宋'),('shusu','蜀素帖八首','米芾','宋'),
              ('qianzi','千字文','周兴嗣','南梁'),('chibi','前赤壁赋','苏轼','宋'),('zhanghan','张翰帖','欧阳询','唐')]
    for key,title,author,dynasty in labels:
        source = 'chibi_common' if key=='chibi' else key
        npm = key in ('jizhi','hanshi','shusu')
        note = ('国立故宫博物院，台北，CC BY 4.0；馆藏释文转简体，略涂改说明、落款及后人题跋。' if npm else
                '故宫博物院释文；「手」字据《晋书》补入。' if key=='zhanghan' else
                '维基文库古籍正文（公有领域），采用常用字形；异文待核对。')
        note += '普通话合成，多音字待人工试听。'
        items.append(dict(id='masterpiece_'+key,category='masterpiece',title=title,author=author,dynasty=dynasty,
                          sentences=sentences(texts[key]),source_url=URLS[source],source_note=note,
                          verification_status='source-transcription-normalized',
                          source_sha256=hashlib.sha256(raw[source].encode()).hexdigest()))
    for item in items:
        if not item['sentences'] or any(not s for s in item['sentences']):
            raise ValueError('Empty reading '+item['id'])
        (a.output/(item['id']+'.json')).write_text(json.dumps(item,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('TEXTS_READY',len(items),'sentences',sum(len(x['sentences']) for x in items))


if __name__ == '__main__':
    main()
