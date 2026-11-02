"""Build the offline library from the existing Make Me a Hanzi graphics.

Only stroke medians are imported; source order/direction are never optimized.
Run from the repository root. No SDK, network or robot operations.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from calligraphy.library import STROKES

# Curated everyday/elementary characters plus useful short calligraphy phrases.
# This is a first trial repertoire, not a claim to be a frequency-ranked top 300.
SELECTION = '''
祝福生日快乐万事如意学业有成国泰民安天天向上春暖花开岁岁平安龙马精神福寿安康
一二三四五六七八九十百千万零年月日天地人和中国你好世界平安喜乐幸福健康快乐
春夏秋冬山水风雨云雪花草树木竹石星光明心爱家学书文梦龙飞舞生如意吉祥永远
上的是不了在有我他这为之大来以个到说们子就时出要也对小可下而过天自能着去
多于得后看都里那用道行所然事发成方者经法无同现当没动面起还进好其因前些从
又主样理她本开把它只想实知长此两公等间很老情外高重相业作手十正向全见关点
业问力定回些新已通真给名知才些教气最东声关分将间却部入与每内于几等思做西
怎次别听但身总使走门再听想何更才美先十海口金华马走南北电白少红眼母父儿女
吃饭喝茶火土车日月山川田目耳足衣食住乐好朋友老师学生学校工作学习认真早晚
今昨午来去多少大小左右上下前后中东西南北远近有无长短高低新旧冷热轻重深浅
开合坐立读写画唱笑话语文字笔墨纸书诗画清青绿白黑红黄蓝春江花月夜日出东方
国民团结友爱自由希望信念勇敢努力奋斗成功进步感恩快乐祝福生日健康万事如意
见听说请谢谢对不起再见欢迎光临欢迎回家人间山河岁时静美好年顺利满园万里鹏
程喜庆财富贵宝寿久长松柳梅兰荷桃李燕鸟鱼虫牛羊兔狗猫鸡马龙虎云海天心星空
''' 


def repertoire(path=None):
    path=path or ROOT/'data/calligraphy/sources/通用规范汉字表2013一级3500字.txt'
    chars=''.join(path.read_text(encoding='utf-8-sig').split())
    if len(chars)!=3500 or len(set(chars))!=3500 or any(not '\u4e00'<=c<='\u9fff' for c in chars):
        raise ValueError('Expected exactly 3500 unique CJK characters in the Level 1 repertoire')
    return chars


def distances(points):
    result = [0.]
    for a, b in zip(points, points[1:]):
        result.append(result[-1] + max(math.hypot(b[0]-a[0], b[1]-a[1]), .001))
    return [x/result[-1] for x in result]


def interpolate(points, t, u):
    import bisect
    i = max(0, min(len(t)-2, bisect.bisect_right(t, u)-1))
    k = (u-t[i])/(t[i+1]-t[i])
    return [a+(b-a)*k for a, b in zip(points[i], points[i+1])]


def classify(points):
    """Select a pressure envelope; never replace the actual character geometry."""
    dx, dy = points[-1][0]-points[0][0], points[-1][1]-points[0][1]
    length = sum(math.dist(a,b) for a,b in zip(points,points[1:]))
    direct = math.hypot(dx,dy)
    # Strongly compound strokes retain their turns; a generic folded envelope
    # is preferable to pretending every folded stroke is a specific radical.
    if direct < length*.72:
        return 'heng_zhe' if abs(points[1][0]-points[0][0]) > abs(points[1][1]-points[0][1]) else 'shu_gou'
    if abs(dy) < abs(dx)*.3: return 'heng'
    if dy < -abs(dx)*.3: return 'ti'
    if abs(dx) < abs(dy)*.25: return 'shu_chuilu'
    if dx < 0: return 'pie'
    return 'dian' if length < 13 else 'na'


def choreography(median):
    # Source coordinates: top-left (0,900), bottom-right (1024,-124).
    points = [[round(x/1024*50,6),round((900-y)/1024*50,6)] for x,y in median]
    points = [p for i,p in enumerate(points) if not i or p!=points[i-1]]
    if len(points)<2: raise ValueError('Degenerate stroke')
    key = classify(points)
    module = STROKES[key][1]
    t, mt = distances(points), distances(module)
    # Preserve source corners as well as all pressure keyframes. Keep depth
    # separate from XY scaling and release at the actual final endpoint.
    knots = sorted(set(t+mt))
    out=[]
    for u in knots:
        xy = interpolate(points,t,u)
        dv = interpolate([p[2:] for p in module],mt,u)
        out.append([round(v,6) for v in xy+dv])
    out[0][2]=out[-1][2]=0.
    return dict(module=key,points=out,source_median=median)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--graphics',type=Path,required=True)
    ap.add_argument('--out',type=Path,default=ROOT/'data/calligraphy')
    ap.add_argument('--repertoire',type=Path,default=ROOT/'data/calligraphy/sources/通用规范汉字表2013一级3500字.txt')
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    chars=repertoire(args.repertoire)
    wanted=set(chars);records={}
    with args.graphics.open(encoding='utf-8') as source:
        for line in source:
            item=json.loads(line);ch=item['character']
            if ch not in wanted:continue
            if ch in records:raise ValueError('Duplicate glyph: '+ch)
            if not item['medians'] or len(item['medians'])!=len(item['strokes']):raise ValueError(ch)
            records[ch]=dict(character=ch,strokes=[choreography(p) for p in item['medians']])
    if wanted-set(records):raise ValueError('Missing: '+''.join(wanted-set(records)))
    raw=''.join(json.dumps(records[ch],ensure_ascii=False,separators=(',',':'))+'\n' for ch in chars)
    geometry_digest=hashlib.sha256(raw.encode()).hexdigest()
    notice=('Derived from Make Me a Hanzi / Arphic (C) 1999 Arphic Technology. '
            'Modified 2026-10-22: selected 3500 Level 1 glyphs, converted medians to XY-down brush keyframes; '
            'stroke order preserved, pressure envelopes added. Glyph data under Arphic Public License; '
            'see APL-English.txt. No warranty; physical brush results not yet verified.')
    for value in records.values():value['source_notice']=notice
    raw=''.join(json.dumps(records[ch],ensure_ascii=False,separators=(',',':'))+'\n' for ch in chars)
    digest=hashlib.sha256(raw.encode()).hexdigest()
    meta=dict(schema='brush-glyphs-v1',version='common3500-20261022-'+geometry_digest[:12],count=len(chars),
              characters=chars,content_sha256=digest,geometry_sha256=geometry_digest,source_notice=notice,
              source_sha256=hashlib.sha256(args.graphics.read_bytes()).hexdigest(),
              source='https://github.com/skishore/makemeahanzi',stroke_order='PRC; preserve source order and direction',
              coordinates='50-unit XY-down',selection='2013 通用规范汉字表 一级字表 3500字',
              repertoire_sha256=hashlib.sha256(chars.encode('utf-8')).hexdigest(),
              selection_reference='https://www.moe.gov.cn/jyb_xwfb/xw_fbh/moe_2069/s7135/s7562/s7564/201308/t20130827_156334.html',
              verification='structural offline; physical ink results pending')
    # Exact bytes keep content_sha256 valid on both Windows and Linux.
    (args.out/'glyphs.jsonl').write_bytes(raw.encode('utf-8'))
    (args.out/'manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.out/'常用3500字.txt').write_text('\n'.join(chars[i:i+50] for i in range(0,len(chars),50))+'\n',encoding='utf-8')
    db=args.out/'glyphs.sqlite';tmp=args.out/'glyphs.build.sqlite'
    if tmp.exists():tmp.unlink()
    with sqlite3.connect(str(tmp)) as con:
        con.execute('CREATE TABLE glyphs (character TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        con.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        con.executemany('INSERT INTO glyphs VALUES (?,?)',[(ch,json.dumps(records[ch],ensure_ascii=False,separators=(',',':'))) for ch in chars])
        con.execute('INSERT INTO metadata VALUES (?,?)',('manifest',json.dumps(meta,ensure_ascii=False)))
    con.close()
    tmp.replace(db)
    print(json.dumps(dict(count=len(chars),strokes=sum(len(r['strokes']) for r in records.values()),bytes=db.stat().st_size,version=meta['version']),ensure_ascii=False))


if __name__=='__main__':main()
