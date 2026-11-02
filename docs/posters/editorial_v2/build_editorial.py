"""Build an eight-page A3 editorial poster set from project photos and evidence.

python build_editorial.py --sans-regular FONT --sans-bold FONT --calligraphy FONT
Requires reportlab, pypdf, Pillow, Poppler. Fonts are local, never redistributed.
"""
import argparse
import json
import math
import re
import subprocess
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ASSETS = HERE / 'assets'
MEDIA = ROOT / 'docs/media'
W, H = 841.89, 1190.55
M, RIGHT = 54, 787.89
PAPER, INK, MUTED = '#F6F4EE', '#242422', '#73716A'
RED, GOLD, LINE, PALE = '#973E35', '#A08B64', '#D8D4CA', '#EAE7DE'
BOXES = []
PAGE = 0


def text(c, x, y, s, size=16, font='sans', color=INK, align='left'):
    runs=[]
    for ch in s:
        selected='bold' if font in ('number','latin') and '\u3400'<=ch<='\u9fff' else font
        if runs and runs[-1][0]==selected:
            runs[-1]=(selected,runs[-1][1]+ch)
        else:
            runs.append((selected,ch))
    c.setFillColor(HexColor(color))
    width = sum(pdfmetrics.stringWidth(value, face, size) for face,value in runs)
    left = x if align == 'left' else x - width if align == 'right' else x - width/2
    assert left >= -1 and left + width <= W + 1, (PAGE, s, left, width)
    BOXES.append({'page': PAGE, 'text': s, 'x': round(left, 2), 'y': y, 'width': round(width, 2), 'size': size})
    for face,value in runs:
        c.setFont(face,size);c.drawString(left,y,value)
        left+=pdfmetrics.stringWidth(value,face,size)
    return width


def rule(c, x1, y, x2, color=LINE, width=.65):
    c.setStrokeColor(HexColor(color)); c.setLineWidth(width); c.line(x1, y, x2, y)


def para(c, s, x, y, width, size=15, leading=26, color=MUTED, font='sans'):
    for original in s.split('\n'):
        line = ''
        for ch in original:
            if line and pdfmetrics.stringWidth(line+ch, font, size)>width:
                carry=''
                if ch in '，。；：？！、）》】' and len(line)>1:
                    carry=line[-1];line=line[:-1]
                text(c,x,y,line,size,font,color); y-=leading; line=carry
            line+=ch
        if line: text(c,x,y,line,size,font,color); y-=leading
    return y


def photo(c, path, x, y, width, height, mode='contain'):
    """Place and clip photos in PDF; leave the source bitmap unchanged."""
    path = Path(path)
    with Image.open(path) as im: iw, ih = im.size
    scale = min(width/iw,height/ih) if mode=='contain' else max(width/iw,height/ih)
    dw, dh = iw*scale, ih*scale
    dx, dy = x+(width-dw)/2, y+(height-dh)/2
    c.saveState()
    clip=c.beginPath();clip.rect(x,y,width,height);c.clipPath(clip,stroke=0)
    c.drawImage(str(path),dx,dy,dw,dh,mask='auto')
    c.restoreState()


def caption(c, s, x, y, width=730):
    return para(c,s,x,y,width,10,16,MUTED)


def base(c, n, category, title=None, lead=None):
    global PAGE
    PAGE=n
    c.setFillColor(HexColor(PAPER));c.rect(0,0,W,H,stroke=0,fill=1)
    rule(c,M,1135,RIGHT,INK,.9)
    text(c,M,1150,'墨韵书坊',18,'brush')
    text(c,RIGHT,1152,category,10,'sans',MUTED,'right')
    if title:
        text(c,M,1045,title,53,'brush')
    if lead:
        para(c,lead,M,999,730,16,27,MUTED)
    rule(c,M,70,RIGHT)
    text(c,M,44,'基于 Zynq 的书法及绘画平台',10,'sans',MUTED)
    text(c,RIGHT-50,44,'MOYUN STUDIO',9,'latin',MUTED,'right')
    text(c,RIGHT,40,f'{n:02d}',23,'latin',RED,'right')


def section(c, x, y, num, title, description, width=214):
    text(c,x,y,num,10,'latin',RED)
    text(c,x,y-34,title,22,'bold')
    para(c,description,x,y-65,width,13.5,23)


def pipeline(c, x, y, widths, labels, details, height=108):
    for i,(width,label,detail) in enumerate(zip(widths,labels,details)):
        c.setFillColor(HexColor(PALE));c.rect(x,y,width,height,fill=1,stroke=0)
        text(c,x+15,y+height-27,f'0{i+1}',11,'latin',GOLD)
        text(c,x+15,y+height-57,label,19,'bold')
        para(c,detail,x+15,y+22,width-28,10,15)
        if i<len(widths)-1:
            xx=x+width+7
            c.setStrokeColor(HexColor(GOLD));c.setLineWidth(1)
            c.line(xx,y+height/2,xx+17,y+height/2)
            c.line(xx+12,y+height/2+4,xx+17,y+height/2)
            c.line(xx+12,y+height/2-4,xx+17,y+height/2)
        x+=width+32


def page1(c):
    base(c,1,'作品总览 / OVERVIEW')
    text(c,49,1009,'墨韵书坊',132,'brush')
    text(c,M,946,'基于 Zynq 的书法及绘画平台',25,'bold')
    text(c,M,908,'从屏上的一笔，到纸上的一画。',18,'sans',MUTED)
    photo(c,ASSETS/'robot_cutout.png',275,340,494,540)
    # Existing ink palette is retained through ink-black typography and a red accent.
    text(c,55,828,'书',57,'brush',RED)
    text(c,58,791,'毛笔写字',16,'bold')
    text(c,55,723,'画',57,'brush',RED)
    text(c,58,687,'照片绘画',16,'bold')
    text(c,55,618,'习',57,'brush',RED)
    text(c,58,582,'手写学习',16,'bold')
    photo(c,MEDIA/'results_calligraphy.jpg',M,360,216,169)
    caption(c,'机械臂实写 / 项目作品片段',M,341,216)
    rule(c,M,319,RIGHT)
    text(c,M,288,'一块开发板',22,'bold')
    text(c,310,288,'一台七轴机械臂',22,'bold')
    text(c,RIGHT,288,'书写 · 绘画 · 交互',17,'sans',MUTED,'right')
    for x,num,unit,label in [(54,'3,500','字','常用字轨迹库'),(310,'11.6万','点/s','100 MHz · RTL 逆解吞吐'),(568,'75.28%','LUT','布线后整板占用')]:
        w=text(c,x,206,num,37,'number')
        text(c,x+w+8,209,unit,12,'sans',RED)
        text(c,x,177,label,12,'sans',MUTED)
    para(c,'板端触屏与手机扫码承载输入；ARM 组织轨迹与任务，FPGA 执行批量七轴逆解。',M,129,730,13,22)
    caption(c,'封面由项目实拍机械臂照片去背景排版；后续页面保留原始作品与界面素材。',M,91)
    c.showPage()


def page2(c):
    base(c,2,'书 / CALLIGRAPHY','从一笔，到一首诗','按笔顺展开字形，以提按、行笔和收锋组织书写。')
    photo(c,MEDIA/'results_calligraphy.jpg',M,557,462,362,'contain')
    caption(c,'毛笔实写作品 / 原始照片',M,535,462)
    photo(c,ASSETS/'ui_calli.png',557,557,191,362)
    caption(c,'笔画工坊界面 / 截图含离线模拟标记',548,535,235)
    rule(c,M,501,RIGHT)
    text(c,M,453,'3,500',47,'number')
    text(c,248,460,'常用字',18,'bold')
    text(c,429,453,'88',47,'number')
    text(c,526,460,'项笔画模块',18,'bold')
    section(c,M,401,'01','字形有序','保留逐笔顺序与方向，按需读取字形轨迹，兼顾常用文字输入。')
    section(c,310,401,'02','笔画有势','以起笔、行笔和收笔模板组织提按；通过标定后的高度表达笔锋变化。')
    section(c,566,401,'03','文字成篇','支持文字排版，以及名帖、春联、诗词等入口，按纸面与字号生成任务。')
    rule(c,M,230,RIGHT)
    text(c,M,196,'从单字到篇章，复用同一套轨迹与执行流程。',23,'brush')
    caption(c,'字库来源：data/calligraphy/manifest.json；笔画模块：calligraphy/library.py、extended.py。',M,151)
    caption(c,'3500 字为轨迹生成与结构检查范围；图中展示项目已有实写样例。毛笔提按由高度模板表达。',M,129)
    c.showPage()


def page3(c):
    base(c,3,'画 / PORTRAIT DRAWING','让照片，成为线条','手机上传或选择本地线稿，沿中心线组织连续笔画。')
    photo(c,ASSETS/'ui_photo.png',M,643,734,296,'contain')
    caption(c,'照片上传界面 / 原始截图保留旧版“糖画坊”名称',M,622)
    pipeline(c,M,459,[162,162,162,152],['扫码上传','线稿生成','路径提取','机械臂绘制'],['手机或本地图像','照片模式可选云端','中心线与抬落笔','七轴规划与控制器'],98)
    photo(c,MEDIA/'results_portrait.jpg',M,161,404,262)
    text(c,500,375,'一张照片，',33,'brush')
    text(c,500,332,'一幅纸上肖像。',33,'brush')
    para(c,'板端显示线稿，规划器组织笔画顺序、抬笔移动与连续逆解，再由控制器完成实际绘制。',500,283,277,14,25)
    caption(c,'硬笔人像实绘 / 项目原始作品照片',M,139,420)
    caption(c,'照片的 AI 风格转换按配置调用云端；本地线稿流程可直接使用已有图像。',M,105)
    c.showPage()


def page4(c):
    base(c,4,'习 / HANDWRITING & LEARNING','手上写，纸上见','从触屏输入到逐笔跟随，把书写过程变成交互体验。')
    photo(c,ASSETS/'handwriting.png',M,594,734,371)
    caption(c,'手写交互界面 / 截图为明确标注的离线模拟状态',M,574)
    rule(c,M,536,RIGHT)
    text(c,M,476,'写一笔，提交一笔。',34,'brush')
    para(c,'触屏采集笔迹，识别笔画并映射到标定字框；规划与执行按队列衔接，保留任务停止和取消处理。',M,430,339,14,25)
    text(c,450,478,'3,755',44,'number')
    text(c,641,484,'类汉字',17,'bold')
    para(c,'离线汉字识别由 ARM 上的 OpenCV DNN 运行，识字与机械臂复写共享界面入口。',450,433,320,14,25)
    photo(c,ASSETS/'ui_audio.png',M,153,365,213)
    text(c,455,326,'书写之外，继续学习。',28,'brush')
    para(c,'界面还提供字迹识别、书法百科、趣味测验与诗文朗读，将展示、练习和学习放在同一块屏幕上。',455,282,321,14,25)
    caption(c,'音频功能界面 / 原始截图',M,130,365)
    caption(c,'识字类别数来自 user_gui/hwr.py；截图展示界面入口与状态，不替代实物动作验收。',M,105)
    c.showPage()


def block(c,x,y,w,h,label,detail,color=PALE):
    c.setFillColor(HexColor(color));c.rect(x,y,w,h,stroke=0,fill=1)
    text(c,x+20,y+h-35,label,21,'bold')
    para(c,detail,x+20,y+h-69,w-40,13,22)


def arrow(c,x1,y1,x2,y2):
    c.setStrokeColor(HexColor(GOLD));c.setLineWidth(1.1);c.line(x1,y1,x2,y2)
    ang=math.atan2(y2-y1,x2-x1)
    for d in [-.5,.5]:c.line(x2,y2,x2-7*math.cos(ang+d),y2-7*math.sin(ang+d))


def page5(c):
    base(c,5,'架构 / SYSTEM ARCHITECTURE','一块板，连起整套系统','PS 负责场景与任务，PL 承接计算和外设，控制器完成机械臂执行。')
    block(c,M,795,734,139,'输入与交互','板端触屏 / 手机扫码 / 本地字库 / 图像与手写笔迹')
    block(c,M,536,346,195,'ARM · PS','用户界面、字库与图像处理\n纸面标定、轨迹编排与重定时\n控制器通信、任务所有权与停止')
    block(c,442,536,346,195,'FPGA · PL','七轴 FP32 连续逆解\n显示、触摸、第二网口与音频\nAXI / DDR 批量数据接口')
    arrow(c,226,795,226,731)
    arrow(c,400,640,442,640);arrow(c,442,615,400,615)
    text(c,421,507,'目标位姿 → 关节解',12,'sans',MUTED,'center')
    block(c,M,353,734,100,'控制器与七轴机械臂','由 PS 下发任务，TCB705 控制器组织实际运动。')
    arrow(c,226,536,226,453)
    photo(c,MEDIA/'board.jpg',M,100,318,211)
    text(c,417,275,'XC7Z020CLG400-2',21,'latin')
    para(c,'Zynq-7020\nARM Cortex-A9 双核 + 可编程逻辑\nMD0700R 触屏与板级外设集成',417,236,355,14,26)
    caption(c,'板卡实物照片；架构依据当前 TCB705 主线和 platform.json。',417,121,355)
    c.showPage()


def page6(c):
    base(c,6,'计算 / FPGA IMPLEMENTATION','七轴逆解，三级流水','把连续轨迹拆成可重叠的计算阶段，以批量接口衔接 ARM 与 PL。')
    text(c,M,890,'目标位姿',16,'bold')
    rule(c,M,869,RIGHT,GOLD)
    pipeline(c,M,678,[222,222,222],['几何分解','CORDIC 与选解','检查与写出'],['位置与冗余几何','沿前一关节解选择连续分支','提交成功前缀与首个失败点'],144)
    text(c,M,628,'FP32 算术',14,'bold')
    text(c,310,628,'定点 CORDIC',14,'bold')
    text(c,566,628,'FIFO 顺序输出',14,'bold')
    rule(c,M,595,RIGHT)
    text(c,M,530,'11.6万',68,'number')
    text(c,310,539,'点 / 秒',25,'bold')
    text(c,M,494,'100 MHz · 每事务 64 个有效目标 · RTL 协同仿真',13,'sans',MUTED)
    section(c,M,427,'01','连续分支','相邻目标沿用上一组已接受关节解，避免每批重置冗余姿态。')
    section(c,310,427,'02','成功前缀','在失败点返回已完成部分，PS 接续处理未完成后缀。')
    section(c,566,427,'03','三级并发','HLS DATAFLOW 以 FIFO 连接阶段，重叠几何、角度与结果写回。')
    rule(c,M,251,RIGHT)
    para(c,'AXI HP1 读取控制与目标，HP3 写回关节解。DDR 接口保留原 FP64 打包布局，在计算边界转换为 FP32。',M,214,730,15,26)
    caption(c,'吞吐证据：hw/reports/parallel_fp32_20261024/hls/throughput_cycles.xml。',M,134)
    caption(c,'55,043–55,123 周期 / 64 点；该数值描述核级仿真，板端调用时间在下一页单列。',M,112)
    c.showPage()


def page7(c):
    base(c,7,'验证 / MEASUREMENTS','把性能放进完整链路','同时观察核级计算、布局布线与板端规划，找到真正影响体验的环节。')
    text(c,M,891,'21,679',56,'number')
    text(c,292,900,'个目标',19,'bold')
    text(c,479,891,'0',56,'number')
    text(c,533,900,'回退',19,'bold')
    para(c,'历史轨迹连续离线回放，339 批接续处理；最大位置计算误差约 0.39 µm。',M,852,730,14,24)
    rule(c,M,803,RIGHT)
    text(c,M,766,'完整平台 · 布线后资源',22,'bold')
    rpt=(ROOT/'hw/reports/audio_iobuf_20261027/utilization.rpt').read_text(encoding='utf8',errors='replace')
    resources=[('LUT','Slice LUTs',75.28),('FF','Slice Registers',52.95),('BRAM','Block RAM Tile',48.21)]
    for i,(label,source,percent) in enumerate(resources):
        yy=714-i*51
        text(c,M,yy,label,13,'latin')
        c.setFillColor(HexColor(PALE));c.rect(133,yy-1,489,12,stroke=0,fill=1)
        c.setFillColor(HexColor(GOLD));c.rect(133,yy-1,489*percent/100,12,stroke=0,fill=1)
        text(c,RIGHT,yy,f'{percent:.2f}%',16,'number',INK,'right')
        assert re.search(re.escape(source)+r'\s*\|[^\n]*'+str(percent),rpt)
    text(c,M,538,'WNS +0.136 ns',20,'number')
    text(c,420,538,'WHS +0.011 ns',20,'number')
    rule(c,M,508,RIGHT)
    text(c,M,466,'板端整图规划 · 同一新版代码',22,'bold')
    text(c,M,432,'8 笔人像，4,744 节点，热规划',13,'sans',MUTED)
    for yy,label,value,color in [(378,'ARM 原生 CPU',6.28,GOLD),(318,'FPGA FP32 路径',9.23,RED)]:
        text(c,M,yy+6,label,13,'sans')
        c.setFillColor(HexColor(color));c.rect(230,yy,value/10*422,22,stroke=0,fill=1)
        text(c,RIGHT,yy+3,f'{value:.2f} s',20,'number',INK,'right')
    para(c,'系统时延由计算、PS 调度、缓存维护和数据解析共同决定。当前板端批量调用仍是优化重点，核级吞吐不能直接换算成整图加速比。',M,253,730,14,25)
    caption(c,'离线误差为模型计算误差；资源为 2026-10-27 音频 IOBUF 平台。',M,149)
    caption(c,'板端对照：hw/reports/parallel_fp32_20261024/board_20261024/README.md。',M,127)
    caption(c,'完整来源与验证口径：docs/validation_summary.md。',M,105)
    c.showPage()


def page8(c):
    base(c,8,'作品与工程 / GALLERY & SOURCE','作品落纸，工程可复现','看见纸上的结果，也能沿着源码、脚本和验证记录理解实现。')
    photo(c,MEDIA/'results_calligraphy.jpg',M,652,354,278)
    photo(c,MEDIA/'results_portrait.jpg',435,652,353,278)
    caption(c,'毛笔书写 / 实拍',M,633,354)
    caption(c,'硬笔人像 / 实拍',435,633,353)
    photo(c,ASSETS/'writing.jpg',M,345,354,246)
    photo(c,ASSETS/'ui_home.png',435,345,353,246)
    caption(c,'纸面与书写夹具 / 实拍',M,325,354)
    caption(c,'墨韵书坊主界面 / 原始截图',435,325,353)
    rule(c,M,286,RIGHT)
    text(c,M,240,'从这里，继续了解工程。',32,'brush')
    text(c,M,198,'github.com/T1vey/moyun-shufang',22,'latin')
    para(c,'源码与构建脚本 / 技术报告 / 原始验证证据 / 运行指南 / 可复用发布检查技能',M,162,730,13,23)
    caption(c,'图片均来自项目已有素材；封面机械臂仅做 AI 去背景处理。字体为本机合法字体渲染，文件不随仓库分发。',M,107)
    c.showPage()


def repository_cover(args):
    path=ROOT/'build/posters/editorial_cover_layout.pdf';path.parent.mkdir(parents=True,exist_ok=True)
    c=canvas.Canvas(str(path),pagesize=(1200,650),pageCompression=1)
    global PAGE
    PAGE=0
    c.setFillColor(HexColor(PAPER));c.rect(0,0,1200,650,stroke=0,fill=1)
    # Use direct canvas calls here because the page-width assertion targets A3.
    c.setFont('brush',111);c.setFillColor(HexColor(INK));c.drawString(54,429,'墨韵书坊')
    c.setFont('bold',24);c.drawString(61,365,'基于 Zynq 的书法及绘画平台')
    c.setFont('sans',17);c.setFillColor(HexColor(MUTED));c.drawString(61,319,'书法写字  /  照片绘画  /  手写学习')
    photo(c,ASSETS/'robot_cutout.png',619,54,511,548)
    rule(c,62,275,535)
    for x,num,label in [(62,'3,500','常用字轨迹'),(240,'7','轴连续逆解'),(391,'100','MHz PL')]:
        c.setFillColor(HexColor(INK));c.setFont('number',37);c.drawString(x,205,num)
        c.setFillColor(HexColor(MUTED));c.setFont('sans',12);c.drawString(x,173,label)
    c.setFillColor(HexColor(RED));c.setFont('latin',11);c.drawString(62,92,'MOYUN STUDIO / ENGINEERING & CALLIGRAPHY')
    c.showPage();c.save()
    subprocess.run([args.poppler,'-singlefile','-scale-to','1800','-png',str(path),str(MEDIA/'cover_editorial_v2')],check=True)


def main():
    ap=argparse.ArgumentParser()
    for n in ['sans-regular','sans-bold','calligraphy']:ap.add_argument('--'+n,required=True)
    ap.add_argument('--latin-regular',default='C:/Windows/Fonts/arial.ttf')
    ap.add_argument('--latin-bold',default='C:/Windows/Fonts/arialbd.ttf')
    ap.add_argument('--poppler',default='pdftoppm');args=ap.parse_args()
    for name,path in [('sans',args.sans_regular),('bold',args.sans_bold),('brush',args.calligraphy),('latin',args.latin_regular),('number',args.latin_bold)]:
        pdfmetrics.registerFont(TTFont(name,path))
    output=HERE/'moyun_editorial_8p.pdf'
    c=canvas.Canvas(str(output),pagesize=(W,H),pageCompression=1)
    c.setTitle('墨韵书坊 · A 版实物编辑设计 · 八页作品海报')
    c.setAuthor('Moyun Studio')
    for fn in [page1,page2,page3,page4,page5,page6,page7,page8]:fn(c)
    c.save()
    source=PdfReader(output);writer=PdfWriter();writer.add_page(source.pages[0])
    writer.add_metadata({'/Title':'墨韵书坊 · 作品总览','/Author':'Moyun Studio'})
    with (HERE/'moyun_cover_a_v2.pdf').open('wb') as f:writer.write(f)
    subprocess.run([args.poppler,'-scale-to','1800','-png',str(output),str(HERE/'page')],check=True)
    preview=ROOT/'build/posters/editorial_preview.pdf'
    preview.parent.mkdir(parents=True,exist_ok=True)
    p=canvas.Canvas(str(preview),pagesize=(2000,1435),pageCompression=1)
    p.setFillColor(HexColor('#DDDAD1'));p.rect(0,0,2000,1435,stroke=0,fill=1)
    for i in range(8):
        x=18+(i%4)*497;y=18+(1-i//4)*710
        photo(p,HERE/f'page-{i+1}.png',x,y,475,674)
        p.setFillColor(HexColor(INK));p.setFont('latin',12);p.drawString(x,y+682,f'{i+1:02d}')
    p.showPage();p.save()
    subprocess.run([args.poppler,'-singlefile','-scale-to','2600','-png',str(preview),str(HERE/'overview_8p')],check=True)
    repository_cover(args)
    (HERE/'layout_text_audit.json').write_text(json.dumps(BOXES,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    for p in [output,HERE/'moyun_cover_a_v2.pdf']:
        assert p.stat().st_size<50_000_000
    print(json.dumps({'pdf':str(output),'pages':len(source.pages),'bytes':output.stat().st_size,'text_items':len(BOXES)},ensure_ascii=False))


if __name__=='__main__':main()
