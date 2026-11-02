"""Typeset generated artwork into A3 PDFs; raster previews via Poppler.

Usage: python docs/posters/build_posters.py --regular FONT --bold FONT --heavy FONT
Requires reportlab and pdftoppm. Font files are local dependencies, not distributed.
"""
import argparse
import subprocess
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader

HERE = Path(__file__).resolve().parent
MEDIA = HERE.parent / 'media'
IVORY, INK, GOLD, GREY = '#F5EEDF', '#1E1A17', '#B08A4A', '#5A4E44'
W, H = 841.89, 1190.55

def text(c, x, y, value, size=14, font='serif', color=INK):
    c.setFillColor(HexColor(color)); c.setFont(font, size); c.drawString(x, y, value)

def line(c, x1, y, x2, color=GOLD, width=.6):
    c.setStrokeColor(HexColor(color)); c.setLineWidth(width); c.line(x1, y, x2, y)

def poster(key, accent):
    out = HERE / ('poster_' + key + '.pdf')
    c = canvas.Canvas(str(out), pagesize=(W,H), pageCompression=1)
    c.setTitle('墨韵书坊 | 基于 Zynq 的书法及绘画平台')
    c.setAuthor('Moyun Studio')
    if key == 'c':
        c.setFillColor(HexColor(IVORY)); c.rect(0,0,W,H,stroke=0,fill=1)
        c.drawImage(str(HERE/'artwork'/('art_'+key+'.png')),W*.16,220,width=W*.68,height=H*.68)
    else:
        c.drawImage(str(HERE/'artwork'/('art_'+key+'.png')),0,0,width=W,height=H)
    # All typography remains vector text, separately editable in this source.
    text(c, 60, 1115, 'MOYUN STUDIO  /  ZYNQ-7020', 11, color=accent)
    text(c, 56, 1002, '墨韵书坊', 90, 'heavy')
    if (HERE/'seal.png').exists():
        c.drawImage(str(HERE/'seal.png'), 664, 1004, 95, 95, mask='auto')
    text(c, 61, 946, '基于 Zynq 的书法及绘画平台', 29, 'bold')
    text(c, 62, 909, '一块开发板 · 一台七轴机械臂 · 写字、画画，不接电脑', 15, color=GREY)
    # The artwork is a concept illustration, distinct from proof photographs.
    for i, (glyph, title, detail1, detail2) in enumerate([
        ('书','毛笔写字','3,500 常用字 · 88 项笔画模块','名帖 · 春联 · 诗词'),
        ('画','照片绘画','扫码上传 · 中心线提取 · 硬笔绘制','线稿提取 5.88 s → 1.14 s¹'),
        ('互','交互学习','屏上手写，机械臂复写','3,755 类离线识字 · 170 ms²'),
    ]):
        x=60+i*247
        text(c,x,282,glyph,34,'heavy',accent)
        text(c,x+47,285,title,19,'bold')
        text(c,x,254,detail1,11.2,color=GREY)
        text(c,x,233,detail2,11.2,color=GREY)
    cards=[('11.6万','点/s','七轴逆解核吞吐','100 MHz · RTL 协同仿真'),
           ('0','回退','21,679 个目标连续回放','离线回放 · 最大计算误差 0.39 µm'),
           ('75.28%','LUT','布线后整板占用','WNS +0.136 ns · Zynq-7020')]
    for i,(num,unit,a,b) in enumerate(cards):
        x=60+i*247
        c.setFillColor(HexColor('#EFE5D0'));c.roundRect(x,91,228,112,7,stroke=0,fill=1)
        line(c,x+12,201,x+216,width=1)
        text(c,x+14,153,num,34,'heavy')
        nx=x+14+pdfmetrics.stringWidth(num,'heavy',34)+8
        text(c,nx,157,unit,14,'bold',accent)
        text(c,x+14,126,a,11.5,'bold')
        text(c,x+14,107,b,9.3,color=GREY)
    line(c,60,75,782)
    text(c,60,56,'ARM：交互 · 排版 · 校验  ｜  FPGA：七轴逆解 · 显示 · 触摸 · 网口 · 音频',10,color=GREY)
    text(c,60,36,'¹ 14 张 1024×1024 图板端中位数   ² 板端单字中位数   ｜   模型计算误差不代表落纸精度',8.2,color=GREY)
    text(c,60,21,'主视觉为 AI 创作示意 · 核级 / 离线 / 实机指标分层报告 · github.com/T1vey/moyun-shufang',8.0,color=GREY)
    c.showPage();c.save()
    return out

def cover():
    pdf=MEDIA/'cover_layout.pdf'
    c=canvas.Canvas(str(pdf),pagesize=(1200,660),pageCompression=1)
    c.setTitle('Moyun Studio repository cover');c.setAuthor('Moyun Studio')
    c.setFillColor(HexColor(IVORY));c.rect(0,0,1200,660,stroke=0,fill=1)
    c.drawImage(str(HERE/'artwork/art_a.png'),560,-85,640,960)
    text(c,60,574,'ZYNQ × ROBOTICS × CHINESE INK',13,color=GOLD)
    text(c,55,440,'墨韵书坊',86,'heavy')
    text(c,61,381,'基于 Zynq 的书法及绘画平台',26,'bold')
    text(c,62,328,'书法写字  /  照片绘画  /  手写交互',18,color=GREY)
    line(c,62,284,515)
    for x,num,label in [(62,'3,500','常用字轨迹'),(225,'7','轴连续逆解'),(392,'100','MHz PL')]:
        text(c,x,217,num,35,'heavy');text(c,x,183,label,13,color=GREY)
    text(c,62,92,'ARM + FPGA 软硬件协同',15,'bold')
    text(c,62,65,'MOYUN STUDIO  ·  ENGINEERED TO WRITE & DRAW',10,color=GOLD)
    c.showPage();c.save();return pdf

def main():
    p=argparse.ArgumentParser()
    for n in ('regular','bold','heavy'):p.add_argument('--'+n,required=True)
    p.add_argument('--poppler',default='pdftoppm');a=p.parse_args()
    for name,path in [('serif',a.regular),('bold',a.bold),('heavy',a.heavy)]:
        pdfmetrics.registerFont(TTFont(name,path))
    MEDIA.mkdir(parents=True,exist_ok=True)
    for key,color in [('a','#B8322A'),('b','#214E45'),('c','#B8322A')]:
        pdf=poster(key,color)
        subprocess.run([a.poppler,'-singlefile','-scale-to','2400','-png',str(pdf),str(pdf.with_suffix(''))],check=True)
    pdf=cover()
    subprocess.run([a.poppler,'-singlefile','-scale-to','1800','-png',str(pdf),str(MEDIA/'cover')],check=True)
    temp=HERE.parents[1]/'build/posters';temp.mkdir(parents=True,exist_ok=True)
    comparison=temp/'comparison_layout.pdf'
    c=canvas.Canvas(str(comparison),pagesize=(1800,905),pageCompression=1)
    for i,(key,label) in enumerate([('a','A / INK & GOLD'),('b','B / JADE GREEN'),('c','C / CINNABAR')]):
        c.setFillColor(HexColor(IVORY));c.rect(i*600,0,600,905,stroke=0,fill=1)
        c.setFillColor(HexColor(INK));c.setFont('Helvetica',17);c.drawString(i*600+30,874,label)
        c.drawImage(str(HERE/('poster_'+key+'.png')),i*600+12,12,width=576,height=814)
    c.showPage();c.save()
    subprocess.run([a.poppler,'-singlefile','-scale-to','2600','-png',str(comparison),str(HERE/'comparison')],check=True)
    print('Created 3 A3 posters, previews and repository cover')

if __name__=='__main__':main()
