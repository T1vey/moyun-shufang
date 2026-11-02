"""Revise only the lower text of original poster A, with seven matching details.

Original PDF content through the upper tagline is retained as PDF operators.
No raster artwork is regenerated or edited. Existing detail layout is reused.
"""
import argparse
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
POSTERS=HERE.parent
TEMP=ROOT/'build/posters/ink_a_v3'
W,H=841.89,1190.55
INK,RED,GOLD,MUTED='#1E1A17','#B8322A','#B08A4A','#5A4E44'
LINE,PALE='#CEBFA3','#EFE5D0'

spec=importlib.util.spec_from_file_location('moyun_poster_layout',POSTERS/'editorial_v2/build_editorial.py')
layout=importlib.util.module_from_spec(spec);spec.loader.exec_module(layout)
original_text=layout.text
original_para=layout.para

COPY={
    '从一笔，到一首诗':'毛笔书法：字库与笔画',
    '让照片，成为线条':'照片绘画：从线稿到纸面',
    '手上写，纸上见':'手写交互与离线识字',
    '一块板，连起整套系统':'Zynq 软硬件协同架构',
    '七轴逆解，三级流水':'七轴逆解的三级流水',
    '把性能放进完整链路':'性能、资源与板端验证',
    '作品落纸，工程可复现':'实写作品与工程资料',
    '字形有序':'字形轨迹','笔画有势':'提按模板','文字成篇':'文字排版',
    '从单字到篇章，复用同一套轨迹与执行流程。':'字形、提按与排版，共同生成书写任务。',
    '一张照片，':'提取中心线，','一幅纸上肖像。':'按笔画绘制。',
    '书写之外，继续学习。':'识字、朗读与书法学习',
    '从这里，继续了解工程。':'工程代码与复现资料',
    '从触屏输入到逐笔跟随，把书写过程变成交互体验。':'触屏输入逐笔进入队列，识字与机械臂复写各自处理。',
    '同时观察核级计算、布局布线与板端规划，找到真正影响体验的环节。':'分别列出核级吞吐、离线回放、布线后资源与板端规划时间。',
    '看见纸上的结果，也能沿着源码、脚本和验证记录理解实现。':'实写样例、交互界面与公开工程资料。',
    '图片均来自项目已有素材；封面机械臂仅做 AI 去背景处理。字体为本机合法字体渲染，文件不随仓库分发。':'封面为水墨创作示意；作品照片与界面截图来自项目已有素材。',
}
COLOR_MAP={'#242422':INK,'#73716A':MUTED,'#973E35':RED,'#A08B64':GOLD,'#D8D4CA':LINE,'#EAE7DE':PALE}


def text(c,x,y,s,size=16,font='sans',color=INK,align='left'):
    return original_text(c,x,y,COPY.get(s,s),size,font,COLOR_MAP.get(color,color),align)


def para(c,s,x,y,width,size=15,leading=26,color=MUTED,font='sans'):
    return original_para(c,COPY.get(s,s),x,y,width,size,leading,COLOR_MAP.get(color,color),font)


def rule(c,x1,y,x2,color=LINE,width=.65):
    c.setStrokeColor(HexColor(COLOR_MAP.get(color,color)));c.setLineWidth(width);c.line(x1,y,x2,y)


def paper(c):
    # The first fifth of art A is blank rice paper. Place that existing area
    # through a page-sized PDF clip, leaving the bitmap unchanged.
    c.saveState()
    path=c.beginPath();path.rect(0,0,W,H);c.clipPath(path,stroke=0)
    c.drawImage(str(POSTERS/'artwork/art_a.png'),0,-4*H,W,5*H)
    c.restoreState()


def base(c,n,category,title=None,lead=None):
    layout.PAGE=n;paper(c)
    rule(c,54,1135,787.89,GOLD,.8)
    text(c,54,1150,'墨韵书坊',16,'heavy')
    text(c,787.89,1152,category,10,'sans',MUTED,'right')
    if title:text(c,54,1045,COPY.get(title,title),45,'heavy')
    if lead:para(c,lead,54,999,730,16,27)
    rule(c,54,70,787.89)
    text(c,54,44,'基于 Zynq 的书法及绘画平台',10,'sans',MUTED)
    text(c,737.89,44,'MOYUN STUDIO',9,'latin',MUTED,'right')
    text(c,787.89,40,f'{n:02d}',23,'latin',RED,'right')


def section(c,x,y,num,title,description,width=214):
    text(c,x,y,num,10,'latin',RED)
    text(c,x,y-34,title,21,'bold')
    para(c,description,x,y-65,width,13.5,23)


def block(c,x,y,w,h,label,detail,color=PALE):
    c.setFillColor(HexColor(COLOR_MAP.get(color,color)));c.rect(x,y,w,h,stroke=0,fill=1)
    text(c,x+20,y+h-35,label,21,'bold')
    para(c,detail,x+20,y+h-69,w-40,13,22)


def lower_cover():
    path=TEMP/'lower_text.pdf'
    c=canvas.Canvas(str(path),pagesize=(W,H),pageCompression=1)
    layout.PAGE=1
    groups=[('书','毛笔书写','3,500 常用字，按笔顺书写','文字排版 · 名帖 · 春联 · 诗词'),
            ('画','照片绘画','照片转线稿，提取连续笔画','扫码上传或选择本地线稿'),
            ('互','手写与学习','屏上手写，机械臂逐笔复写','离线识字 · 诗文朗读')]
    for i,(glyph,title,a,b) in enumerate(groups):
        x=60+i*247
        text(c,x,282,glyph,27,'bold',RED)
        text(c,x+41,287,title,16.5,'bold')
        text(c,x,257,a,11.5,'sans',MUTED)
        text(c,x,237,b,11,'sans',MUTED)
    for i,(num,unit,a,b) in enumerate([
        ('11.6万','点/s','七轴逆解核吞吐','100 MHz · RTL 协同仿真'),
        ('0','回退','21,679 个目标连续回放','离线回放 · 最大计算误差 0.39 µm'),
        ('75.28%','LUT','布线后整板资源占用','WNS +0.136 ns'),
    ]):
        x=60+i*247
        rule(c,x,210,x+228,GOLD,.8)
        w=text(c,x,162,num,32,'number')
        text(c,x+w+9,165,unit,13,'sans',RED)
        text(c,x,134,a,11.5,'bold')
        text(c,x,113,b,9.1,'sans',MUTED)
    rule(c,60,80,782,GOLD,.6)
    text(c,60,59,'ARM：交互、排版与轨迹组织  ｜  FPGA：七轴逆解、显示、触摸、网口与音频',10,'sans',MUTED)
    text(c,60,37,'吞吐为 RTL 仿真结果；回退与计算误差来自该条历史轨迹的离线回放。',8.7,'sans',MUTED)
    text(c,60,20,'水墨主视觉为创作示意  ·  github.com/T1vey/moyun-shufang',8.5,'sans',MUTED)
    c.showPage();c.save()
    return path


def preserve_original_cover(overlay):
    source=POSTERS/'poster_a.pdf'
    reader=PdfReader(source);writer=PdfWriter();page=writer.add_page(reader.pages[0])
    stream=ContentStream(page.get_contents(),writer)
    found=False;end=None
    for i,(operands,operator) in enumerate(stream.operations):
        if operator==b'Tm' and [float(v) for v in operands[-2:]]==[62.0,909.0]:
            found=True
        if found and operator==b'ET':end=i+1;break
    if end is None:raise ValueError('Original A upper tagline not found; refusing to alter composition')
    stream.operations=stream.operations[:end]
    page.replace_contents(stream)
    page.merge_page(PdfReader(overlay).pages[0])
    writer.add_metadata({'/Title':'墨韵书坊 · 原 A 版文字修订','/Author':'Moyun Studio'})
    output=HERE/'moyun_a_text_refined.pdf'
    with output.open('wb') as f:writer.write(f)
    return output,{'original_pdf_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'retained_original_operations':end,'original_upper_area_above_y_pt':330,'original_upper_elements':['artwork','rice paper','title','subtitle','tagline','seal','palette']}


def main():
    ap=argparse.ArgumentParser()
    for n in ['sans-regular','sans-bold','serif-bold','serif-heavy']:ap.add_argument('--'+n,required=True)
    ap.add_argument('--latin-regular',default='C:/Windows/Fonts/arial.ttf')
    ap.add_argument('--latin-bold',default='C:/Windows/Fonts/arialbd.ttf')
    ap.add_argument('--poppler',default='pdftoppm');args=ap.parse_args()
    for name,path in [('sans',args.sans_regular),('bold',args.sans_bold),('brush',args.serif_bold),('heavy',args.serif_heavy),('latin',args.latin_regular),('number',args.latin_bold)]:
        pdfmetrics.registerFont(TTFont(name,path))
    for name,value in [('text',text),('para',para),('rule',rule),('base',base),('section',section),('block',block),('INK',INK),('RED',RED),('GOLD',GOLD),('MUTED',MUTED),('LINE',LINE),('PALE',PALE)]:
        setattr(layout,name,value)
    TEMP.mkdir(parents=True,exist_ok=True)
    cover,proof=preserve_original_cover(lower_cover())
    details=TEMP/'details.pdf'
    c=canvas.Canvas(str(details),pagesize=(W,H),pageCompression=1)
    c.setTitle('墨韵书坊 · A 版详情');c.setAuthor('Moyun Studio')
    for fn in [layout.page2,layout.page3,layout.page4,layout.page5,layout.page6,layout.page7,layout.page8]:fn(c)
    c.save()
    book=PdfWriter()
    book.add_page(PdfReader(cover).pages[0])
    for page in PdfReader(details).pages:book.add_page(page)
    book.add_metadata({'/Title':'墨韵书坊 · 原 A 版封面与七页详情','/Author':'Moyun Studio'})
    output=HERE/'moyun_ink_a_8p.pdf'
    with output.open('wb') as f:book.write(f)
    subprocess.run([args.poppler,'-scale-to','1800','-png',str(output),str(HERE/'page')],check=True)
    subprocess.run([args.poppler,'-singlefile','-scale-to','2400','-png',str(cover),str(HERE/'cover_full')],check=True)
    # The image comparison is a document-render QA check, not a bitmap edit.
    from PIL import Image,ImageChops
    old=Image.open(POSTERS/'poster_a.png').convert('RGB')
    new=Image.open(HERE/'cover_full.png').convert('RGB')
    assert old.size==new.size
    boundary=int((H-330)/H*old.height)
    difference=ImageChops.difference(old.crop((0,0,old.width,boundary)),new.crop((0,0,new.width,boundary)))
    proof['upper_pixel_difference_bbox']=difference.getbbox()
    assert proof['upper_pixel_difference_bbox'] is None, 'Original upper area changed'
    proof['upper_rendered_rows_unchanged']=boundary
    preview=TEMP/'overview.pdf'
    c=canvas.Canvas(str(preview),pagesize=(2000,1435),pageCompression=1)
    c.setFillColor(HexColor('#D9CEB9'));c.rect(0,0,2000,1435,stroke=0,fill=1)
    for i in range(8):
        x=18+(i%4)*497;y=18+(1-i//4)*710
        layout.photo(c,HERE/f'page-{i+1}.png',x,y,475,674)
        c.setFillColor(HexColor(INK));c.setFont('latin',12);c.drawString(x,y+682,f'{i+1:02d}')
    c.showPage();c.save()
    subprocess.run([args.poppler,'-singlefile','-scale-to','2600','-png',str(preview),str(HERE/'overview_8p')],check=True)
    proof.update(pages=8,scope='original cover upper area preserved; lower wording/fonts/layout revised; details retain A visual direction',cover_bytes=cover.stat().st_size,book_bytes=output.stat().st_size)
    assert max(cover.stat().st_size,output.stat().st_size)<50_000_000
    (HERE/'validation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':main()
