from pathlib import Path
import math,sys,json
import numpy as np
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor,Color,white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT

ROOT=Path(r'D:\zhiliao\TCB705_ZYNQ-10-15\ZYNQArm')
sys.path.insert(0,str(ROOT))
from calligraphy.library import STROKES,RADICALS
OUT=Path(r'C:\Users\gongj\Desktop\ZYNQ天链机械臂_手写模式完整实施方案_FPGA规划版_20261023.pdf')
pdfmetrics.registerFont(TTFont('CN',r'C:\Windows\Fonts\msyh.ttc',subfontIndex=0))
pdfmetrics.registerFont(TTFont('CNB',r'C:\Windows\Fonts\msyhbd.ttc',subfontIndex=0))
pdfmetrics.registerFont(TTFont('KAI',r'C:\Windows\Fonts\simkai.ttf'))
W,H=595.276,841.89
INK='#29251F';MUTED='#6B706D';PAPER='#F7F4EC';GOLD='#C58B36';TEAL='#187E79';BLUE='#426B94';RED='#B9513E';LINE='#DEDCD3'
c=canvas.Canvas(str(OUT),pagesize=(W,H),pageCompression=1)
c.setTitle('ZYNQ天链机械臂：手写模式完整实施方案（FPGA规划版）')
c.setAuthor('ZYNQArm 项目技术方案');c.setSubject('面向电子信息专业学生的算法学习与工程实施规划')
page_no=0;checks=[]

def box(x,y,w,h,fill='#FFFFFF',stroke=None,r=9):
    c.setFillColor(HexColor(fill));c.setStrokeColor(HexColor(stroke or fill));c.setLineWidth(.8)
    c.roundRect(x,H-y-h,w,h,r,fill=1,stroke=bool(stroke))
def line(x1,y1,x2,y2,color=LINE,width=1):
    c.setStrokeColor(HexColor(color));c.setLineWidth(width);c.line(x1,H-y1,x2,H-y2)
def txt(x,y,t,size=11,color=INK,font='CN'):
    c.setFont(font,size);c.setFillColor(HexColor(color));c.drawString(x,H-y-size*.86,str(t))
def para(x,y,w,t,size=10.5,leading=17,color=INK,font='CN',maxh=None):
    style=ParagraphStyle('p',fontName=font,fontSize=size,leading=leading,textColor=HexColor(color),wordWrap='CJK',spaceAfter=0)
    p=Paragraph(t,style);_,h=p.wrap(w,1000)
    if maxh is not None and h>maxh+.1:raise ValueError(f'overflow page {page_no}: {t[:35]} height {h}>{maxh}')
    if y+h>785:raise ValueError(f'page bottom overflow {page_no}: {t[:30]}')
    p.drawOn(c,x,H-y-h);checks.append((page_no,x,y,w,h));return h
def arrow(x1,y1,x2,y2,color=TEAL,width=1.8):
    line(x1,y1,x2,y2,color,width);a=math.atan2(y2-y1,x2-x1)
    for d in (-.5,.5):line(x2,y2,x2-7*math.cos(a+d),y2-7*math.sin(a+d),color,width)
def dot(x,y,r=3,color=TEAL):
    c.setFillColor(HexColor(color));c.circle(x,H-y,r,fill=1,stroke=0)
def heading(y,t,n=None):
    if n is not None:box(42,y,23,23,TEAL,r=6);txt(48,y+4,n,12,'#FFFFFF','CNB');x=75
    else:x=42
    txt(x,y+2,t,14,INK,'CNB')
def note(y,title,body,color=TEAL,h=80):
    box(42,y,511,h,'#EAF3EF' if color==TEAL else '#F9EDE5',r=10)
    txt(56,y+12,title,11,color,'CNB');para(56,y+32,483,body,10,16,maxh=h-39)
def card(x,y,w,h,title,body,color=TEAL):
    box(x,y,w,h);txt(x+14,y+14,title,12,color,'CNB');para(x+14,y+39,w-28,body,10.2,17,maxh=h-48)
def page(title,sub,section='手写模式 / 完整实施'):
    global page_no
    if page_no:c.showPage()
    page_no+=1;c.setFillColor(HexColor(PAPER));c.rect(0,0,W,H,fill=1,stroke=0)
    txt(42,26,'ZYNQ × TCB705  |  手写毛笔实验室',8.5,TEAL,'CNB')
    txt(403,26,section,8.2,MUTED)
    line(42,46,553,46)
    txt(42,63,title,23,INK,'CNB');para(42,101,510,sub,10.4,16,color=MUTED,maxh=32)
    line(42,798,553,798);txt(42,812,'2026.10.23  /  实施规划，非已部署功能',8,MUTED)
    txt(493,811,f'{page_no:02d} / 26',9,MUTED,'CNB')
    c.bookmarkPage(f'p{page_no}');c.addOutlineEntry(title,f'p{page_no}',0)
def trace(points,x,y,w,h,color=TEAL,width=2.5,dots=False,fit=True):
    a=np.asarray(points,dtype=float)[:,:2]
    if fit:
        lo=a.min(0);span=np.maximum(a.max(0)-lo,1e-6);s=min(w/span[0],h/span[1]);a=(a-lo)*s
        a+=np.array([x+(w-span[0]*s)/2,y+(h-span[1]*s)/2])
    else:a=a*np.array([w,h])+[x,y]
    c.setStrokeColor(HexColor(color));c.setLineWidth(width);c.setLineCap(1);c.setLineJoin(1)
    p=c.beginPath();p.moveTo(a[0,0],H-a[0,1])
    for px,py in a[1:]:p.lineTo(px,H-py)
    c.drawPath(p)
    if dots:
        for px,py in a:dot(px,py,1.7,color)
    dot(*a[0],3.8,GOLD)
    if len(a)>1:
        end=a[-1]
        for prior in a[-2::-1]:
            delta=end-prior;length=float(np.linalg.norm(delta))
            if length>1e-6:
                begin=end-delta/length*min(10,length)
                arrow(*begin,*end,color,1.6)
                break
    return a
def grid(x,y,w,h,n=4):
    box(x,y,w,h,'#FFFFFF',LINE)
    for i in range(1,n):line(x+w*i/n,y,x+w*i/n,y+h);line(x,y+h*i/n,x+w,y+h*i/n)
def resample(a,n):
    a=np.asarray(a,float);d=np.r_[0,np.cumsum(np.linalg.norm(np.diff(a,axis=0),axis=1))]
    ts=np.linspace(0,d[-1],n);return np.column_stack([np.interp(ts,d,a[:,j]) for j in range(2)])
def code(x,y,w,h,lines,size=9.3):
    box(x,y,w,h,'#263631');c.setFillColor(white);c.setFont('Courier',size)
    for i,s in enumerate(lines):c.drawString(x+14,H-y-21-i*15,s)

def table(y, widths, rows, size=10, leading=16, minrow=35):
    x0=42
    for ri,row in enumerate(rows):
        ps=[]
        for j,cell in enumerate(row):
            st=ParagraphStyle('cell',fontName='CNB' if ri==0 else 'CN',fontSize=size,leading=leading,wordWrap='CJK',textColor=HexColor('#FFFFFF' if ri==0 else INK))
            p=Paragraph(str(cell),st);_,hh=p.wrap(widths[j]-20,1000);ps.append((p,hh))
        h=max(minrow,max(z[1] for z in ps)+18)
        if y+h>782:raise ValueError(f'table overflow p{page_no}: {y+h}')
        box(x0,y,sum(widths),h,TEAL if ri==0 else ('#FFFFFF' if ri%2 else '#EEEFE7'),r=0)
        x=x0
        for j,(p,hh) in enumerate(ps):p.drawOn(c,x+10,H-y-9-hh);x+=widths[j]
        y+=h
    return y

def small_label(x,y,t,col=TEAL):
    txt(x,y,t,9,col,'CNB')

def lane(y,label,col=TEAL):
    txt(42,y+12,label,10.5,col,'CNB');line(126,y+44,553,y+44)

def pill(x,y,w,t,col=TEAL):
    box(x,y,w,30,col,r=7);txt(x+9,y+8,t,9.5,'#FFFFFF','CNB')

def darkbtn(x,y,w,t,active=False):
    box(x,y,w,26,'#B8661A' if active else '#2E2116','#B8661A',r=5)
    txt(x+8,y+7,t,9,'#FFE2A6','CNB')

# 01
page('手写模式：完整实施方案','ZYNQ7020 主控 · TCB705 七轴机械臂 · PL 运动规划 · 40～100 mm 字号','图解版 / 方案总览')
box(42,150,511,249,'#1A120C',r=13)
txt(63,170,'你写一笔，机械臂跟写一笔',24,'#FFE2A6','CNB')
for x,t,b in [(63,'① 手指松开','识别最近笔画'),(232,'② FPGA 规划','保留尺寸和位置'),(401,'③ 顺序执行','写完抬笔悬停')]:
    box(x,229,131,111,'#2E2116','#B8661A',r=8)
    txt(x+10,246,t,12,'#FFE2A6','CNB');para(x+10,275,111,b,10.3,18,color='#F7EAD6')
arrow(200,284,224,284,GOLD);arrow(369,284,393,284,GOLD)
txt(65,365,'忙时先规划、再排队；下一个字才清屏与复位。',12,'#CBB497')
heading(427,'这份文档解决什么')
para(42,460,511,'把最新要求落实成界面、状态机、数据结构、识别算法、FPGA 计算、队列调度、控制器下发与测试验收。所有示意图均为本项目实施设计；“现有能力”“新增内容”“待实测目标”分别说明。',11,19)
table(552,[135,376],[['阅读路线','对应页码'],['先看怎么用','第 2～6 页：交互、界面、自动准备、触摸采集'],['再看怎么算','第 7～15 页：识别、坐标、笔法、PL、接口与编译'],['最后看怎么开发','第 16～26 页：排队、复位、API、代码、延迟、测试与交付']],10,16)
txt(42,755,'版本：2026-10-23 · 本次交付为规划文档，未改动运行代码或操纵机械臂。',8.7,MUTED)

# 02
page('01  把需求固定下来','下列规则作为实施基线，避免开发到一半时各模块对“马上写”“下一个字”理解不同。')
table(151,[121,390],[['用户需求','实施规则'],['入口与风格','主界面“书法模式”旁新增“手写模式”；复用深棕、金黄、红印章和现有触摸控件。'],['自动准备','点击后建立会话、检查连接/标定/PL、加载缓存、使能与安全归位；准备成功后开放画布。'],['一笔一写','有效松手后自动匹配最近模块；无识别确认弹窗。保留单笔在字框中的大小、位置和主要方向。'],['FPGA 规划','新增严格 PL 路径：几何采样、七轴连续 IK、轨迹平滑和时间参数化在 PL 完成；CPU 负责识别、调度、复核与传输。'],['字号与速度','字号 40～100 mm，步进 1 mm，默认 60 mm；速度使用现有 GUI 全局速度，不新增另一套百分比。'],['保存墨迹','当前字的所有已接收笔画保留；完成、等待、正在写只是状态变化，不删笔画。'],['忙时排队','识别/规划可与机器人执行重叠；按输入序号执行。上一笔未执行完，也能规划后一笔。'],['下一个字','冻结新输入，完成此前已接收的笔画，抬笔复位；确认成功后清屏，建立新字编号，回到准备完成态。'],['结束一笔','竖直抬笔后停在该笔末端上方；不逐笔归位，不逐笔重新连接或加载 FPGA。']],10,16)
note(698,'“马上”具体指什么','空闲时不再等识别确认或重复准备；忙时立即进入处理流水线。机器人仍要移动到落笔起点，排队等待不能被软件消除。',h=77)

# 03
page('02  现有工程能复用到哪里','以实际源码为依据。已有“FPGA 加速”并不等于目前已经实现完整 PL 手写规划。')
table(151,[116,197,198],[['模块','已经具备','本次新增/改造'],['GUI / Web 服务','糖画坊风格、书法页、速度设置、异步任务接口','手写页、触摸轨迹、状态推送、字级会话'],['笔画模板','35 种基本笔画、53 种偏旁；提按与平滑曲线','简化识别模板；任意位置放置；保持相对比例'],['现有 PL','IK_CHAIN：每批最多 64 点；FK_ROWS：最多 1024 点','手写几何、连续轨迹、时间参数化模式；严格 PL 验收'],['现有 CPU 规划','几何采样、细化、连续曲线、时间规划；必要时回退 CPU IK','拆出黄金参考模型；手写执行路径禁止静默 CPU 代算'],['控制器下发','常驻 SDK、moveJoints、全局速度、七轴反馈','持续悬停会话；轨迹时间执行契约的独立验证'],['原书法执行','预设/整字任务，带开始与结束归位','手写不能每一笔直接调用原整任务执行器']],9.8,16)
note(650,'现有标记还不足以证明“全 PL”','当前 ik_backend 显示 PL 时，仍可能有 CPU 细化或回退。新手写计划必须记录各阶段执行位置，以及 cpu_ik_calls=0、cpu_retime_calls=0 等证据。CPU 独立复核保留。',h=112)

# 04
page('03  用户界面长什么样','以 1024×600 屏幕为目标；下图为布局示意，颜色采用当前 base.css 的实际样式变量。')
box(42,151,511,292,'#120C08',r=9)
txt(54,164,'糖画坊',14,'#FFE2A6','CNB')
darkbtn(252,159,75,'书法模式');darkbtn(333,159,75,'手写模式',True);darkbtn(414,159,63,'速度 60%');darkbtn(484,159,57,'设置')
box(54,197,221,221,'#231910','#B8661A',r=5)
for i in (1,2,3):
    line(54+i*55.25,197,54+i*55.25,418,'#51402B',.5);line(54,197+i*55.25,275,197+i*55.25,'#51402B',.5)
line(89,276,235,276,'#F3AD45',4);line(164,228,164,383,'#FFE2A6',3)
txt(65,426,'字框 60 mm × 60 mm',8,'#CBB497')
box(288,197,253,221,'#1A120C','#5B4026',r=5)
txt(302,210,'手写跟随',13,'#FFE2A6','CNB');txt(302,236,'● 正在书写第 1 笔',10,'#8FD694')
txt(302,259,'已识别：竖  |  第 2 笔已规划',9.5,'#CBB497')
darkbtn(302,286,224,'字号   −      60 mm      ＋')
txt(304,321,'40～100 mm · 下个字生效',9,'#CBB497')
darkbtn(302,345,105,'下一个字',True);darkbtn(418,345,109,'停止')
darkbtn(302,381,225,'返回用户界面')
table(463,[126,385],[['控件','行为与实现细节'],['正方形画布','约 440×440 CSS 像素，米字格可淡显；使用独立绘制层，不整页重建 DOM。'],['字号控件','按钮与滑块同步；1 mm 步进。当前字有笔画时锁定其字号，新值明确标注“下个字生效”。'],['状态区','显示准备进度、识别名称、执行序号、已规划/待规划数量；不以弹窗打断写字。'],['触摸与颜色','按钮触摸区域至少 44×44 CSS 像素；金黄表示已接收、亮金表示当前、红色标记错误，不只靠颜色区分。']],10,16)
txt(42,757,'切页复用现有显示通道；不重载 Overlay，不重置 LCD，不再引入切换黑屏。',9,MUTED)

# 05
page('04  点进模式后，自动做哪些准备？','准备阶段只做一次。准备完成后保存机械臂起始状态，后续逐笔执行直接复用。')
steps=[('1','获取独占会话','防止图片绘画、书法、其他客户端同时控制机械臂。'),('2','核对机器与标定','确认控制器、七轴映射、TCP、纸面、下压上限和反馈有效；不改既有标定。'),('3','预热识别与 PL','载入识别模板；确认 bit/hwh/ABI/时钟；申请固定 DDR 缓冲并做非运动自检。'),('4','连接、使能、归位','按已验证 SDK 流程检查状态再使能；沿验证过的抬笔/归位路径运动。'),('5','冻结准备快照','停稳后读取七轴姿态与工具位姿，形成 q_ready；预热结束，开放画布。')]
for i,(n,t,b) in enumerate(steps):
    yy=153+i*100;heading(yy,t,n);para(75,yy+32,478,b,10.4,17,maxh=51)
note(671,'准备失败就停在明确的阶段','给出“控制器未连接 / 标定不一致 / FPGA 版本不符”等具体原因；不自动清报警或关闭保护。恢复时重新核对姿态，不能把旧准备快照当成当前状态。',h=103)

# 06
page('05  手写采集与墨迹保存','前端只做轻量采集与显示；识别、规划、网络请求都不能堵住触摸回调。')
for x,t,b,col in [(42,'按下','新建 stroke_id；锁定一个触点；记录画布坐标。',TEAL),(217,'移动','积累 x、y、时间；逐帧画线；保留真实点序。',BLUE),(392,'松开','冻结这一笔；异步提交一次；立即允许下一笔。',GOLD)]:card(x,151,161,130,t,b,col)
heading(315,'三层数据，不把屏幕截图当轨迹')
table(351,[121,390],[['数据层','存什么、什么时候清除'],['raw_strokes','归一化坐标 u、v、时间戳；每字最多 64 笔，每笔最多 2048 点；超过预算明确提示，不偷偷截断。'],['recognized','最近模块、匹配分数、放置参数、字符字号与版本。只识别当前这一笔，不扫描 3500 字库。'],['render/history','按 stroke_id 保存屏幕矢量墨迹和状态。已写完仍保留；刷新页面恢复本会话，不重新提交运动。']],10,16)
heading(568,'事件边界')
para(42,602,511,'Pointer Events 优先，板载浏览器不支持时用单一路径的 Touch Events 适配。pointercancel、页面隐藏、触点丢失或第二手指介入，取消未提交输入；不能当作松手执行。采样点必须有限、时间有序且位于字框内。',10.5,18)
note(697,'保留到“下一个字”','有效松手后保留金色墨迹；识别结果叠加层只用于提示，原笔迹不被替换。失败笔画留在屏幕并带编号和原因，不能显示成已完成。',h=78)

# 07
page('06  怎样匹配“最接近的笔画”？','采用本地、有方向的模板匹配。对有效但模糊的输入自动选最近类别，不弹确认框。')
for x,t,pts in [(42,'手写轨迹',[[0,.05],[.85,0],[.9,.82]]),(217,'识别主线',[[0,0],[1,0],[1,1]]),(392,'毛笔执行模块',STROKES['heng_zhe'][1])]:
    box(x,151,161,160);trace(pts,x+29,176,103,94,TEAL if x!=392 else GOLD,3,False);txt(x+25,285,t,11,INK,'CNB')
table(333,[111,400],[['步骤','确定的首版算法'],['预处理','去重、轻度去抖；按弧长重采样成 64 点。识别副本平移、等比归一化；原始位置单独保留。'],['粗排','35 类各准备约 3 个识别样例；比较点距、方向、转角和宽高比，取前 5 个样例；分差小时扩大候选。'],['精排','带窗口 ±8 的 DTW 对齐；各项归一后用 J=0.60 形状+0.15 方向+0.15 转角+0.10 比例。权重需采样调优。'],['选择','选 J 最小的模块；同分按固定优先级。普通竖线无法区分垂露/悬针时使用默认笔法，不编造识别置信度。'],['特殊输入','短按走“点”判定；反向书写保留方向惩罚，但执行采用模板标准笔顺。取消、越界等无效输入不进入运动。']],10,16)
note(689,'识别主线与笔法轨迹分开','识别模板忽略小回锋，执行模块仍有起笔、提按和收锋。首版识别只在 CPU 上进行；它不属于用户要求迁入 PL 的运动规划。',h=85)

# 08
page('07  字号与屏幕位置怎样对应纸面？','字号 S 是整个字框的边长，不是把每一笔都放大到 S mm。否则多笔无法拼成一个字。')
grid(42,155,210,210,4);grid(343,155,210,210,4)
for x,w in [(42,210),(343,210)]:
    line(x+.2*w,155+.35*w,x+.8*w,155+.35*w,GOLD,4)
    line(x+.5*w,155+.15*w,x+.5*w,155+.85*w,TEAL,3)
txt(80,379,'屏幕的固定正方形',11,INK,'CNB');txt(379,379,'纸上的 S×S mm',11,INK,'CNB')
arrow(264,259,329,259);txt(272,278,'映射',10,TEAL)
box(42,414,511,111,'#263631')
txt(57,431,'u=(x−左边界)/画布宽；v=(y−上边界)/画布高',12,'#FFFFFF','CNB')
txt(57,461,'P = O字框 + S·u·ex + S·v·ey − d·n',13,'#F5D6A0','CNB')
txt(57,491,'ex、ey：标定纸面两个方向；n：纸面法线；d：下压深度。',9.8,'#FFFFFF')
para(42,548,511,'例：S=60 mm，横笔从 (0.20,0.35) 写到 (0.80,0.35)，对应长度 36 mm、距字框上沿 21 mm。随后竖笔在 u=0.50 处落下，就保持“十”的相对位置。S=100 mm 时同一横为 60 mm。',10.7,18)
para(42,609,511,'本式以 mm 表示。送入 IK 前统一转 m；若接口接收法兰目标，必须先通过 TCP 工具变换换算。',10,15,maxh=30)
note(644,'字号不等于毛笔粗细，也不等于可达保证','按字号缩放 X/Y，不按比例放大下压深度；9 mm 毛长、2 mm 最粗直径与用户给出的 4 mm 下压上限沿用。当前约 149×150 mm 标定矩形能容纳 100 mm 字框，但仍要验证角落、姿态与机构可达。',h=128)

# 09
page('08  模板怎样贴合手写位置与比例？','识别决定笔画种类；放置参数决定它在当前字里“多长、多高、从哪里到哪里”。')
table(151,[126,385],[['输入类型','放置方法'],['横 / 竖 / 撇 / 捺','从手写主方向与两端定位；把模块主线长度和方向映射过去。笔法小回锋不参与放大字框。'],['横折等折线','提取主要转角地标；分别映射各主段的长短和转角位置，连接处保持同一点与连续切线。'],['弯 / 钩','保留主曲线弯曲程度；细小钩用模板形状，尺度设下限，避免手指抖动变成夸张折角。'],['点','用触摸中心定位；点的长度/倾斜按小轨迹和模板决定；零长度也不能出现除零或无限放大。']],10.3,17)
para(42,393,511,'现有落笔 Z 若记录的是法兰坐标，不能直接称为笔尖高度；应沿用对应工具/接触标定转换，本次不修改已保存的工作高度。',10,16,maxh=48)
heading(453,'坐标副本各司其职')
card(42,489,246,126,'识别副本','中心归一、等比缩放，仅用于比较形状。不能把此副本直接拿去执行，否则每笔都会跑到同一个中心。')
card(303,489,250,126,'放置参数','归一字框中的位置、主方向、转角地标、段长比例。CPU 输出这些参数；PL 据此变换毛笔节点并生成曲线。',GOLD)
note(644,'首版边界处理','对字框内的整条执行包络（含回锋）做检查；不要先越界再硬裁轨迹。触摸有效但变形过大时仍选最近模块，缩减局部笔法装饰需明确规则与测试；不能悄悄移动整个字。',h=127)

# 10
page('09  机械臂实际执行的一笔','一笔是连续的“空移 → 落笔 → 书写 → 抬笔 → 悬停”，提按和竖直姿态都要进入规划。')
box(42,151,511,207)
line(64,310,530,310,'#A89175',2)
txt(71,325,'纸面',10,MUTED)
arrow(78,198,172,198,TEAL,2);arrow(172,198,172,292,BLUE,2)
trace([[0,0],[.3,-.08],[.6,.06],[1,0]],172,294,238,13,GOLD,3,False,False)
arrow(410,292,410,198,TEAL,2);dot(410,198,5,GOLD)
txt(70,174,'空移',11,TEAL,'CNB');txt(184,237,'落笔',10,BLUE);txt(256,275,'提按书写',11,GOLD,'CNB');txt(423,237,'抬笔',10,TEAL);txt(424,174,'等待下一笔',10,INK)
table(384,[110,401],[['阶段','规划与执行约束'],['接入起点','从上一笔悬停端点出发，先保持足够间隙，再到新起点上方；不沿纸面横移。'],['落笔与提按','沿纸面法线落笔，深度 d(s) 来自模块；全程保持既定工具姿态，不能用单个舵机先动替代。'],['笔内运动','七轴协调，曲线和速度连续；保留模板的顿笔位置，但不在每个离散节点自动停一下。'],['抬笔悬停','按纸面法线抬起，末端速度为 0；已验证的抬笔高度从机器配置读取。不要误把归位高度当逐笔抬笔高度。']],10,16)
note(682,'为什么不只协调 ID3 和 ID4？','天链是七轴机构。保持笔轴竖直需要完整七轴 IK 约束和工具/纸面标定；ID3、ID4 会参与，但不能照搬旧 SO101 的固定两舵机联动规则。',h=92)

# 11
page('10  明确 CPU、FPGA、控制器的分工','最终目标是 PL 产出可执行的完整单笔计划；CPU 不在 PL 出错后偷偷重新算一份轨迹。')
for y,title,col,body in [(151,'CPU / PS',TEAL,'触摸采集 · 最近笔画匹配 · 放置参数 · 会话与队列 · 独立复核 · SDK 发送'),(282,'FPGA / PL',GOLD,'模板变换与曲线采样 → 连续七轴 IK → 关节曲线 → 时间参数化 → 约束检查'),(413,'机械臂控制器',BLUE,'接收目标 · 关节伺服 · 编码器反馈 · 保护与停止；执行时间语义必须与 PL 输出一致')]:
    box(42,y,511,96,'#FFFFFF');txt(58,y+15,title,14,col,'CNB');para(58,y+44,479,body,10.7,18,maxh=43)
    if y<413:arrow(297,y+102,297,y+123,col)
heading(543,'新增 PL 任务模式的建议')
para(42,576,511,'保留现有 IK_CHAIN / FK_ROWS ABI；新增独立版本的 HANDWRITING_PLAN。输入模块控制节点、放置参数、纸面/TCP、起始 q、限制和速度版本；输出七轴轨迹、阶段标志、时间信息、末端悬停 q、误差统计和状态码。',10.5,18)
note(678,'严格执行位置证明','每份计划注明 geometry=PL、ik=PL、retime=PL；CPU FK/限位复核可保留。PL 超时、输出不完整、复核不通过时该笔不得执行，也不得伪装成已成功规划。',h=96)

# 12
page('11  七轴逆解连续性怎样保证？','把上一点的关节姿态作为下一点的起始猜测；整笔还要受限位、误差、变化率共同约束。')
for i in range(5):
    x=52+i*103;box(x,158,90,69,'#FFFFFF');txt(x+12,172,f'目标 P{i}',11,TEAL,'CNB');txt(x+12,197,f'关节 q{i}',10,INK)
    if i<4:arrow(x+91,192,x+101,192,TEAL)
txt(54,246,'q0 从准备姿态/前笔悬停姿态开始；q1、q2……沿同一分支延续。',10.3,MUTED)
table(284,[126,385],[['机制','具体实现'],['种子与预测','首点用 q_seed；后续以 q[i−1] 为基准，可用 2q[i−1]−q[i−2] 预测。预测只用于初值，不是已合格结果。'],['七轴冗余','优先靠近上一组解并远离关节边界；限制累计偏移；不把“达到相同 TCP”误当成“同一关节分支”。'],['失败处理','PL 内有界增加迭代、细分步长再算；整笔达不到容差就报错。禁止 CPU IK 补算后仍标注全 PL。'],['连续复核','逐段检查限位、关节增量、FK 轨迹误差、笔轴方向、速度/加速度与碰撞；只验节点不能保证中间轨迹。'],['批次衔接','即使内部仍分 64 点批次，也传递末两组 q、阶段和版本；不能每一批重新从 home 开始。']],10,16)
note(674,'笔尖竖直不是一个“写前开关”','每个落笔、书写、抬笔采样点都要满足工具方向约束；离散点之间的控制器插补也需验证。只有端点方向正确，不能证明整段抬笔方向正确。',h=101)

# 13
page('12  PL 速度规划与 GUI 速度一致','用户只看到一套速度。速度百分比也不是固定的笔尖毫米/秒，弯角与加速度限制仍然生效。')
table(151,[127,384],[['项目','首版确定做法'],['几何与时间分离','先求连续关节曲线 q(s)，再求进度 s(t)。沿用现有 CPU 曲线算法作黄金参考，再逐阶段迁入 HLS。'],['速度约束','vq=q_s·v_s；aq=q_ss·v_s²+q_s·a_s。q_s、q_ss 为路径的一阶/二阶导数；同时检查 jerk。笔内节点不能全部设成零速度。'],['时间参数化','先实现有界的分段多项式与全局时间放大：求各关节导数极值，按速度/加速度/jerk 比例放慢，反复检查直到通过；后续再做更激进的局部优化。'],['提按与顿笔','d(s) 和笔法阶段随轨迹走；执行模板既有顿笔系数沿用，不重新恢复早前偏长的顿笔时长。'],['统一速度源','采用现有 GUI 的 draw_speed_pct；归位、空移、书写共用该来源。笔法内部相对速度由同一基准派生。'],['变速生效点','当前正在执行的笔保持已冻结的速度版本；新 GUI 值在下一笔或复位任务生效。未执行队列按新速度在 PL 重做时间规划，几何缓存可复用。']],10,16)
note(672,'必须避免二次乘速度','若 PL 已按 60% 输出时间轴，控制器不能再把整段按 60% 二次缩放。定时接口由 PL 时间轴主导；现有 moveJoints 的全局比例则由适配层单独处理，不能混用两套语义。',h=101)

# 14
page('13  PL 算完后，怎样真正驱动机械臂？','轨迹计算和轨迹执行是两个环节。不能把 SDK 接口返回“成功”当作机械臂已经按计划运动。')
table(151,[119,392],[['路径','用途与限制'],['当前 moveJoints','可复用常驻连接、全局速度、七轴关节目标和反馈。当前默认队列深度 1，控制器自行插补，调用中没有显式逐点时间戳。'],['阶段联调路径','先用既有接口检验 PL 关节目标、笔尖位置、抬笔姿态和顺序。但若每段停顿或偏离 PL 时间律，只能算阶段结果。'],['最终执行契约','优先验证厂商支持的定时/缓冲关节轨迹接口：单位、七轴顺序、周期、排队容量、开始/完成、断流、停止必须有可重复测试。'],['已有透传原型','仓库有 sdk_target_sink.cpp，调用 PluseToServo；存在源码不代表当前 GUI 已接通或本机验收。文档中的 2～4 ms 是示例，不能直接当实测周期。'],['保护与实时性','若某透传方式要求关闭保护，不作为自动准备的隐藏步骤。先确认适合本机的控制契约；ARM Linux 网络线程必须测抖动与停止行为。']],10,16)
heading(605,'本方案采用的验收口径')
para(42,637,511,'最终交付要求：PL 生成轨迹，控制器按已验证的时间/轨迹契约执行。若当前固件只有自由插补的 moveJoints 可用，则保留阶段演示，但不宣称已满足完整 PL 时间规划执行。无需先把 SDK 或网卡协议搬入 FPGA。',10.5,18)
txt(42,755,'机械臂仍通过板载 GE_PL 网口通信；CPU 发送 PL 结果不会改变“规划在 PL”的职责。',9,MUTED)

# 15
page('14  Vivado 工程要怎样改和编译？','已有 PL 资源并不宽裕。优先复用一个运算核心，用状态机调度各阶段，不另造多个完整 IK 引擎。')
table(151,[127,128,256],[['本地基线指标','已用 / 可用','意味着什么'],['LUT','39,238 / 53,200','73.76%；仍要看布局和布线，不只看剩余逻辑数。'],['Slice','12,988 / 13,300','97.65%；来自 2026-10-20 布局报告，说明现有打包/控制集压力较大。'],['BRAM / DSP','37 / 140；68 / 220','可评估把部分分布式存储转 BRAM、算术映射 DSP；不能据此直接保证新设计放得下。']],9.8,16)
heading(414,'构建流程与产物')
para(42,447,511,'① 从最新线稿版 Block Design 建立独立 handwriting Vivado 工程，保留 LCD、触摸、GE_PL、线稿 IP 与原规划兼容模式。<br/>② HLS 分阶段实现，先做 C 仿真，再综合与 C/RTL 联合仿真；对照 CPU 黄金输出。<br/>③ 合并 IP，检查时钟/复位/AXI；运行综合、布局布线、DRC、时序和 CDC 检查。<br/>④ 导出 .bit、.hwh、.xsa、ABI 文档、构建哈希、资源/时序报告和自检向量。<br/>⑤ 候选包板端自检、显示/触摸/网络回归通过后，再替换开机版本并保留回退包。',10.5,19)
note(672,'不要复制旧 manifest 或盲目提高时钟','当前存在不同日期的本地 manifest 与板端部署记录，必须按同一构建配套。现有报告含时钟重定义、I/O 延时等告警，需逐项核实，不能只看 WNS；显示相关 FCLK0 也不能为加速规划随意改动。',h=105)

# 16
page('15  PL 数据接口、内存与故障边界','像设计一个 DMA 外设：任务有编号、数据有边界，结果必须能确认属于这一次请求。')
table(151,[117,394],[['区域','建议的 v2 数据契约'],['任务头','abi、job_id、session_id、char_epoch、seq、context_id、capacity、generation、前驱计划哈希。'],['只读上下文','七轴模型、TCP、纸面坐标、关节/动态限制、笔画库版本、速度版本；用摘要绑定，不让排队计划悄悄换配置。'],['笔画输入','模板控制节点及提按/速度系数、标准化放置参数、字号 S、q_seed；不是 CPU 预先算好的完整关节轨迹。'],['规划输出','阶段、轨迹节点/多项式系数、时间信息、q_start/q_end、误差与限位统计、错误位置；整体校验后才能执行。'],['资源预算初值','每笔最多 8192 条、按 128 B/条预算约 1 MiB；1 笔执行+8 笔待处理约 9 MiB，双缓冲约 2 MiB。其余原始点、缓存及 Python 对象另计。'],['执行超时','软超时报告慢任务；硬超时/取消后等待硬件明确退出。PL 仍持有 DDR 时不可复用、释放或只删除锁文件。']],10,16)
note(657,'预算是上限设计，不是已经测出的内存占用','规划队列采用紧凑数组而不是大量 Python 字典。首版为手写子系统预留并测量峰值内存，建议控制在 64 MiB 内；超长轨迹分块但保持同一笔原子状态，不能截尾后执行半笔。',h=116)

# 17
page('16  上一笔没写完，下一笔如何先规划？','规划线程与执行线程并行；PL 内部仍按依赖顺序处理，每一笔都必须知道前一笔的预计结束姿态。')
box(42,151,511,266)
txt(59,166,'下面时间轴只表示重叠关系，不代表毫秒比例',10,MUTED)
lane(202,'手指输入',TEAL);pill(145,208,91,'第 1 笔',TEAL);pill(270,208,91,'第 2 笔',TEAL);pill(395,208,91,'第 3 笔',TEAL)
lane(270,'FPGA 规划',GOLD);pill(175,276,100,'规划 1',GOLD);pill(300,276,100,'规划 2',GOLD);pill(425,276,112,'规划 3',GOLD)
lane(338,'机械臂',BLUE);pill(265,344,147,'执行第 1 笔',BLUE);pill(421,344,116,'执行第 2 笔',BLUE)
table(440,[123,388],[['规则','调度方式'],['三条独立通道','触摸/HTTP 不等待规划；一个识别与 PL 任务调度器；一个 SDK 执行所有者。状态通知只传摘要，不频繁重传整条轨迹。'],['输入顺序优先','按 seq 排队，禁止后完成识别的简单笔画越过前一笔。一个 PL 会话独占共享硬件，避免两线程交错写 DDR。'],['有界队列','初值：最多 8 笔未完成的待处理任务，另加 1 笔正在执行。待处理含待识别、待规划、已规划；总额统一计数。'],['队列满时','画布在下一次按下前明确显示“队列已满，稍候”；不丢弃已接收笔画，不接受后又悄悄覆盖。网络重试凭 ID 去重。']],10,16)
txt(42,757,'“先规划”表示尽快进入规划流水线；若 PL 正忙，显示待规划，不能虚报已规划。',9,MUTED)

# 18
page('17  提前规划最关键的“接缝”','如果用机械臂当前正在运动的姿态去规划下一笔，等真正轮到它执行时，起点很可能已经变了。')
box(42,151,511,151,'#263631')
txt(60,170,'计划 1：q_ready → 写横 → q_hover_1',13,'#FFFFFF','CNB')
txt(60,213,'计划 2：q_hover_1 → 写竖 → q_hover_2',13,'#F5D6A0','CNB')
txt(60,256,'计划 3：q_hover_2 → ……',13,'#FFFFFF','CNB')
table(329,[125,386],[['关键点','具体实现'],['起始种子','第 1 笔使用准备快照 q_ready；第 n 笔使用计划 n−1 的完整抬笔悬停 q_end，不使用 n−1 运动中间的实时 q。'],['依赖关系','计划记录 predecessor_hash；只有前驱计划已封存，后继才能完成规划。前驱尚未规划时，后继最多先做识别和放置参数准备。'],['执行前复核','收到前一笔完成回调后，还要用新鲜反馈检查停稳、悬停高度、七轴与末端误差；回调成功不能单独作为放行条件。'],['端点不一致','若超过已验证接入容差，保留原手写意图，废弃该笔及后续旧计划；用实测姿态在 PL 重建依赖链。不能直接把首帧改成实测 q 然后跳到第二帧。'],['避免反复延迟','没有偏差时直接释放已规划任务，不重复完整规划。重复重规划次数和总时间有预算，超过则暂停说明原因。']],10,16)
note(690,'允许误差也需要定义成可验证的接入段','若实际端点在容差内，执行器仍需保证实际到计划起点的连续接入符合约束；没有可验证的接入契约时，走 PL 短接入规划，不能靠“差不多”放行。',h=83)

# 19
page('18  “下一个字”是一个复位事务','点击后不让已接收的笔画丢失，也不在机械臂仍写旧字时立即接受新字。')
for i,(n,t,b) in enumerate([('1','锁住新输入','把 Next 请求记为 pending；按钮显示“写完后复位”。当前字的墨迹继续显示。'),('2','排空旧字任务','等待已接收笔画依次完成；如果规划/运动失败，进入错误处理，不能自动跳过失败笔画。'),('3','竖直抬笔并复位','从实际姿态出发，经验证的安全路径回到准备阶段记录的 q_ready；速度采用 GUI 当前值。'),('4','确认后再清屏','确认停稳和目标姿态，递增 char_epoch；清除旧字墨迹与队列，启用新的字号，回到 READY。')]):
    yy=151+i*111;heading(yy,t,n);para(75,yy+33,478,b,10.6,18,maxh=59)
box(42,615,511,155,'#F9EDE5')
txt(57,630,'屏幕清除不等于纸面墨迹消失',13,RED,'CNB')
para(57,660,481,'按本次需求，“下一个字”恢复相同准备姿态和同一字框，没有自动换纸或自动平移书写位置。因此换字前需要提供新的空白纸面，否则会叠写在原位置。若以后要连续横排，应另加已标定的字框索引；本版不暗中改变纸面坐标。',10.5,18,maxh=90)

# 20
page('19  后端接口与任务字段','所有接口遵循现有服务的认证和错误处理；同一会话只允许一个客户端拥有运动控制权。')
table(151,[202,309],[['建议接口（均为新增）','返回与语义'],['POST /api/handwriting/start','立即返回 session_id 与 PREPARING；后台准备，不能让 HTTP 一直阻塞到归位结束。'],['POST /api/handwriting/strokes','输入 session_id、char_epoch、stroke_id、seq、归一坐标数组、字号版本；返回 accepted/duplicate/busy 与任务编号。'],['GET /api/handwriting/status','当前模式、各笔阶段、识别名称、执行进度、队列容量、错误、活动/待生效字号与速度版本。'],['POST /api/handwriting/config','设置字号 40～100；速度沿用 /api/tcb/speed，但手写期间改为记录待生效值，在笔边界应用，不直接改变正在执行的倍率。'],['POST /api/handwriting/next','幂等 request_id；设置排空后复位请求，多次点击不能重复归位。'],['POST /api/handwriting/stop','优先停止下发、取消队列并请求控制器停止；反馈确认后给出停稳状态。'],['POST /api/handwriting/exit','空闲退出释放会话；忙时先按停止/退出流程处理，不只隐藏页面。']],9.9,16)
code(42,653,511,114,[
    'StrokeIntent = {session_id, char_epoch, stroke_id, seq,',
    '  points_uvt, module_id, placement, size_mm,',
    '  template_hash, calibration_hash, speed_epoch}',
    'StrokePlan = {intent_hash, predecessor_hash, q_start,',
    '  q_end, pl_build_id, stages, timing, result_hash}'
],9.2)

# 21
page('20  代码具体落在哪些文件？','所有新增路径均相对于 ZYNQArm。旧预设书法与图片绘画入口保留，手写使用独立任务类型。')
table(151,[219,292],[['文件/目录','工作内容'],['user_gui/static/desktop.html<br/>base.css / handwriting.js（新）','增加入口、同风格手写页、画布历史、字号与队列状态。新增模块异步加载，避免原书法页大 DOM 再导致卡顿。'],['user_gui/display_server.py','增加手写路由；快速返回任务编号；复用身份验证、错误码和速度入口。'],['calligraphy/recognition.py（新）<br/>recognition_templates.py（新）','采样归一化、64 点粗排、DTW、确定性选类；模板主线与执行模块 ID 绑定。'],['calligraphy/placement.py（新）<br/>presets.py / curves.py','新增 brush-handwriting-v1 与服务端重建校验；独立支持 40～100 mm，不直接套用 task() 当前 10～80 mm 的居中入口。'],['tcb705/handwriting_session.py（新）<br/>handwriting_queue.py（新）','生命周期、字级版本、前驱依赖、队列预算、Next/Stop 事务、恢复与日志。'],['tcb705/handwriting_pl.py（新）<br/>accel_contract.py / accel_runtime.py','严格 PL 任务封装、常驻缓冲、ABI/结果校验、取消与错误；兼容旧模式但不混用版本。'],['hls_source/tcb705/…<br/>hw/vivado_handwriting/（新）','增加几何/轨迹/时间规划逻辑、复用 IK 核；建立可重建 Vivado 工程并生成部署包。'],['tcb705/sdk_motion.py<br/>native/huacheng_bridge/…','持续会话适配、执行边界、时间契约、反馈与停止验证；不为每笔关闭重开 SDK。']],9.8,16)
txt(42,758,'测试新增：tests/test_handwriting_*.py、HLS 测试台、板端延迟与持续执行脚本。',9,MUTED)

# 22
page('21  低延迟要测哪几个时间？','识别很快并不代表笔已经碰纸。把“首次运动”和“实际落笔”分开测，结果才有意义。')
box(42,151,511,167,'#FFFFFF')
labels=[('t0','松手'),('t1','识别完'),('t2','PL 完'),('t3','开始下发'),('t4','首次位移'),('t5','落纸书写')]
for i,(a,b) in enumerate(labels):
    x=61+i*82;dot(x,223,5,TEAL if i<4 else GOLD);txt(x-8,190,a,11,INK,'CNB');txt(x-17,245,b,9.3,MUTED)
    if i<5:arrow(x+9,223,x+70,223,TEAL)
txt(61,285,'忙时还要单列 queue_wait，不把排队时间藏进规划耗时。',10,MUTED)
table(342,[139,372],[['证据 / 目标','准确含义'],['已测：5 mm 空中直线','2026-10-22 四次，规划/检查约 110～123 ms；SDK 应答约 2.7～3.1 ms；模拟松手到反馈首次位移约 201～206 ms，平均约 203 ms。'],['这不是手写完成时间','不含真实触摸识别、笔画提按和落纸；反馈约 50 ms 刷新，无传感器采样时间戳，不能视为毫秒级物理起动精度。'],['新增性能目标','识别 P95≤30 ms；热态普通单笔“后端收到松手到计划就绪”先争取 P95≤200 ms。属于待实现目标，复杂折钩、100 mm 和重规划单独统计。'],['端到端要求','界面先画出墨迹，建议显示延迟≤1 帧；机器人空闲时立即自动执行。最终松手到运动/落纸 P50、P95、最大值以实测报告为准。']],10,16)
note(690,'测量方法','浏览器单调时钟测触摸/显示，板端单调时钟测识别/PL/下发；跨设备对时或校准偏差。实际起动用同步视频、外部传感器或可靠带时间戳反馈验证。',h=85)

# 23
page('22  一套能判断“真的做好了”的测试','先虚拟与离线，再板端无运动，再空中，最后落纸。测试结果需要覆盖最大字号和连续排队。')
table(151,[125,386],[['测试层','必须验证的情况'],['识别与放置','35 类×每类多样例；不同人、方向、快慢、短点、折钩。建议采集 3 人×35 类×10 次=1050 笔，并按书写者分训练/验证。'],['坐标与毛笔','40/60/80/100 mm 的字框、四角与中心；横竖交叉位置、宽高比例、回锋包络、深度≤4 mm；图像验证不是实际力验证。'],['队列一致性','连续输入 8 笔；识别不同耗时不乱序；重复 HTTP 不重写；旧 char_epoch 不执行；前驱失败不跳过；反馈偏差使后续重规划。'],['FPGA 正确性','CPU 黄金模型对比、C/RTL 协同仿真、批次边界、NaN/越界/超时/取消/旧结果；全路径 PL 标记可追踪。'],['界面稳定性','进入、书写、下一字、返回反复切换；不黑屏、不冻结；笔迹直到复位成功才清除；队列状态实时可读。'],['运动与停止','空中验证连续起停、笔轴方向、限位；执行中 Stop、断网、PL 失败、掉电后不得重放旧队列；到位需反馈确认。'],['性能与耐久','每个字号/笔画复杂度至少 100 次延迟测量；持续 30 分钟与 100 次换字，测内存峰值、排队长度和触摸掉帧。']],10,16)
note(685,'质量验收要落在纸上','以纸面标记点、实际线长和笔轴观测衡量位置/竖直误差，容差按实测能力制定。识别准确率建议先以“可区分类别≥95%”为目标，不把同形笔法变体计成必然可识别。',h=89)

# 24
page('23  建议按这六个阶段实施','先验证两个决定成败的环节：PL 是否放得下并算得够快、控制器是否能执行所需的轨迹契约。')
table(151,[55,181,275],[['阶段','交付物','进入下一阶段的条件'],['A','现状冻结与关键验证<br/>资源/接口/延迟基线','核对最新 bit/hwh/manifest；做最小 PL 扩展资源试验；把 SDK 时间/缓冲/停止契约测清。'],['B','同风格 GUI 与仿真会话','不用机器人就能采集、留痕、调字号、Next、Stop；后端异步返回，连续输入不冻结。'],['C','识别与放置算法','最近笔画稳定、位置/比例正确；后端重建校验通过；40～100 mm 退化/越界用例齐全。'],['D','完整 PL 单笔计划','HLS C/RTL 通过；综合/布线/时序问题可解释并关闭；严格 PL 生成普通与复杂单笔，无 CPU 规划回退。'],['E','持续执行与预测队列','空中连写至少 8 笔、100 次换字；前驱接缝与新鲜反馈通过；归位不会逐笔发生；停止与错误不重放。'],['F','落纸与发布','实际纸面检验尺寸、提按、线形与竖直抬笔；延迟/内存达标；旧图片/书法与显示/网络回归通过。']],10,16)
note(668,'最终部署包应包含','软件版本、识别模板、PL .bit/.hwh/.xsa、ABI 与哈希、机器配置摘要、测试报告、开机自检、回退说明。整个过程不得把旧标定示例覆盖掉当前机器参数。',h=105)

# 25
page('24  用“十”走通全流程与异常流程','这是最小的端到端演练：两笔交叉、忙时排队、抬笔悬停、换字清屏全部覆盖。')
table(151,[94,417],[['时刻','系统发生什么'],['进入模式','准备、归位、读 q_ready；字号 60 mm，GUI 速度 60%。显示“准备完成，请写一笔”。'],['松开横笔','识别为横，保留其位置；PL 从 q_ready 生成“到起点→写横→悬停”，复核后下发。屏幕横笔一直保留。'],['马上补竖','机械臂还写横时，竖笔识别后在 PL 从 q_hover_横 规划；完成后成为队列第 2 笔。它不从当前运动中间姿态出发。'],['横笔结束','用新鲜反馈核对悬停端点，满足接入条件就开始竖笔；不归位。竖笔结束后继续悬停等输入。'],['点下一个字','如果竖笔还在写，先完成已接收任务；回 q_ready 并核对成功，再清屏、换 char_epoch。若字号已改 80 mm，此时应用。']],10,16)
for x,t,col in [(42,'准备中',TEAL),(146,'待写 / 执行',BLUE),(250,'排空旧字',GOLD),(354,'复位中',TEAL),(458,'待写',BLUE)]:
    pill(x,445,95,t,col)
    if x<458:arrow(x+96,460,x+102,460,col,1)
para(42,493,511,'会话状态：任意运动态可转入停止/故障态，确认停稳后才恢复。<br/>单笔状态：接收 → 识别 → 规划 → 待执行 → 执行 → 完成，或失败/取消。',10,17,maxh=51)
heading(574,'发生异常时')
para(42,607,511,'Stop 优先于所有排队/Next 请求：停止下发、取消待执行任务、请求控制器停止，并确认结果。网络恢复、刷新页面或重新进入模式都不自动重播旧队列；若仍有未完成实体笔画，界面保留事实状态。复位失败时保留墨迹，不显示“准备完成”。',10.5,18)
note(700,'这一次不做什么','不识别整个汉字，不自动纠正笔顺，不搜索整字库，也不把半笔与下一笔偷偷合成一笔。多笔怎样组成汉字，由你在画布上的位置和书写顺序决定。',h=76)

# 26
page('25  最终核对表与依据','这是一份可拆成开发任务的方案。只有“界面正确、PL 可证、执行可测、异常可控”同时成立，才算完成。')
table(151,[286,225],[['用户要求','实施与验收页'],['书法旁的同风格手写入口','第 2、4、20、21、23 页'],['进入后自动准备；逐笔不归位','第 5、10、17、19 页'],['最近笔画 + 原位置 + 原比例','第 6～9 页'],['字号 40～100 mm，沿用 GUI 速度','第 2、8、13、20 页'],['FPGA 完成运动规划并可真实执行','第 11～16、23、24 页'],['前笔未完成，后笔先规划再排队','第 17、18、25 页'],['墨迹保留；下一字清屏并复位','第 6、19、25 页']],9.8,15,minrow=31)
heading(474,'源码与实测依据（本机路径均相对项目根目录）')
para(42,508,511,'[1] user_gui/static/desktop.html、base.css、calligraphy.js；display_server.py：当前界面与 API。<br/>[2] calligraphy/library.py、presets.py、curves.py：模块、提按与校验。<br/>[3] tcb705/planner.py、accel_contract.py、accel_runtime.py、sdk_motion.py；hls_source/tcb705/tcb_planner_accel.cpp：当前计算边界。<br/>[4] hw/vivado_lineart/tcb705_lineart.runs/impl_1/ 下 utilization_placed 与 timing_summary_routed 报告（2026-10-20）。<br/>[5] reports/handwriting_latency_20261022/air_response_live_20261022.json：四次空中 5 mm 测试；不是本手写模式端到端验收。',9.2,15)
para(42,679,511,'算法学习：<link href="https://depts.washington.edu/acelab/proj/dollar/index.html" color="#187E79">$1 Unistroke Recognizer（原作者资料）</link>；<link href="https://developer.mozilla.org/en-US/docs/Web/API/Pointer_events" color="#187E79">MDN Pointer Events</link>。本方案保留方向与结构限制，未原样照搬旋转不变识别。<br/>项目根目录：D:\\zhiliao\\TCB705_ZYNQ-10-15\\ZYNQArm<br/>建议先完成第 24 页 A 阶段，再推进可交互原型与完整 FPGA 迁移。',9.5,16,maxh=94)

assert page_no==26,page_no
c.save()
(Path(__file__).parent/'layout_checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'output':str(OUT),'pages':page_no,'bytes':OUT.stat().st_size},ensure_ascii=False))

