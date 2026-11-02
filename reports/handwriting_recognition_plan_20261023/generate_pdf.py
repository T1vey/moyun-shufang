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
OUT=Path(r'C:\Users\gongj\Desktop\ZYNQ毛笔机器人_手写笔画识别匹配图解与实施方案_20261023.pdf')
pdfmetrics.registerFont(TTFont('CN',r'C:\Windows\Fonts\msyh.ttc',subfontIndex=0))
pdfmetrics.registerFont(TTFont('CNB',r'C:\Windows\Fonts\msyhbd.ttc',subfontIndex=0))
pdfmetrics.registerFont(TTFont('KAI',r'C:\Windows\Fonts\simkai.ttf'))
W,H=595.276,841.89
INK='#29251F';MUTED='#6B706D';PAPER='#F7F4EC';GOLD='#C58B36';TEAL='#187E79';BLUE='#426B94';RED='#B9513E';LINE='#DEDCD3'
c=canvas.Canvas(str(OUT),pagesize=(W,H),pageCompression=1)
c.setTitle('ZYNQ毛笔机器人：手写笔画识别匹配图解与实施方案')
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
def page(title,sub,section='识别匹配 / 工程实施'):
    global page_no
    if page_no:c.showPage()
    page_no+=1;c.setFillColor(HexColor(PAPER));c.rect(0,0,W,H,fill=1,stroke=0)
    txt(42,26,'ZYNQ × TCB705  |  手写毛笔实验室',8.5,TEAL,'CNB')
    txt(403,26,section,8.2,MUTED)
    line(42,46,553,46)
    txt(42,63,title,23,INK,'CNB');para(42,101,510,sub,10.4,16,color=MUTED,maxh=32)
    line(42,798,553,798);txt(42,812,'2026.10.23  /  实施规划，非已部署功能',8,MUTED)
    txt(493,811,f'{page_no:02d} / 16',9,MUTED,'CNB')
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

# 01
page('写一笔，识别一笔，机器人写一笔','从触摸坐标到毛笔轨迹：给电子信息专业学生的一份图解实施方案','学习版 / 方案总览')
box(42,150,511,254,'#263631',r=15)
txt(64,170,'把它想成一个带机械输出的信号处理系统',13,'#F5D6A0','CNB')
grid(65,212,139,137,4);trace([[0,.1],[.85,.1],[.85,.9]],83,233,102,94,TEAL,4,False,False)
txt(91,365,'手指写横折',11,'#FFFFFF')
arrow(215,280,253,280,GOLD,2)
box(264,236,98,80,'#E9B968',r=10);txt(285,252,'ZYNQ',18,INK,'CNB');txt(276,283,'识别 + 规划',10,INK)
arrow(372,280,408,280,GOLD,2)
line(425,328,425,286,'#E6E4DA',6);line(425,286,466,247,'#E6E4DA',6);line(466,247,507,279,'#E6E4DA',6);line(507,279,507,309,GOLD,3)
for a,b in [(425,286),(466,247),(507,279)]:dot(a,b,6,GOLD)
line(415,337,531,337,'#D5C6A9',2);trace([[0,0],[.8,0],[.8,.7]],448,321,66,13,GOLD,2,False,False)
txt(428,365,'机械臂写出来',11,'#FFFFFF')
card(42,426,161,108,'你将学会','轨迹怎样变成数据；<br/>算法怎样认出横折。')
card(217,426,161,108,'你将看懂','屏幕位置怎样映射到纸面；<br/>毛笔怎样继承提按笔法。',GOLD)
card(392,426,161,108,'你将知道','代码改在哪里；<br/>怎样测试速度与正确性。',BLUE)
heading(561,'本方案的边界')
para(42,592,511,'输入是一笔连续触摸轨迹，输出是现有毛笔笔画模块。每次松手处理一笔；多个笔画按顺序组成汉字。第一版采用本地模板匹配，不依赖云端识别，也不搜索整字字库。',11,19)
note(681,'先记住一句话','识别回答“像哪种笔画”；坐标映射回答“写在哪里”；运动规划回答“七个关节怎么动”。',h=79)

# 02
page('01  先看懂：一个“十”怎么写出来','先建立直觉，再学习算法。屏幕上的笔画顺序，就是机械臂执行的顺序。')
for x,label,kind in [(42,'① 手指写一横',0),(219,'② 手指补一竖',1),(396,'③ 两笔组成“十”',2)]:
    grid(x,158,157,166,4)
    line(x+30,220,x+127,220,GOLD if kind==2 else TEAL,5)
    if kind:line(x+79,183,x+79,299,GOLD if kind==2 else BLUE,5)
    txt(x+13,339,label,11,INK,'CNB')
for y,n,title,body in [(389,'1','识别这一笔','第一笔匹配到“横”；第二笔匹配到“竖”。系统可以始终不知道你正在写“十”字。'),(487,'2','位置关系保持不变','第一横在哪，机器人就放在哪；第二竖在哪，就在对应位置穿过第一横。不能每一笔都重新居中。'),(585,'3','写完后悬停等下一笔','完成一笔后保持笔轴竖直抬起，停在空中等待。下一笔到来再移动到它的起点，不逐笔返回归位点。')]:
    heading(y,title,n);para(75,y+33,478,body,10.7,18,maxh=57)
note(700,'想一想','如果你写的是字库里没有的生僻字，仍可逐笔写出。条件是每笔能由现有模板近似，且轨迹位于已标定、可到达的区域。',h=76)

# 03
page('02  现有工程里，哪些可以直接用？','把“基本笔画、偏旁、整字”看成三个层次。手写识别入口先处理最底层。')
for x,num,label,body in [(42,'35','基本笔画模块','横、竖、撇、点、横折等。<br/>手写识别的主要候选。'),(217,'53','偏旁模块','多个笔画的组合。<br/>第一版不把整串手势认成偏旁。'),(392,'3500','常用整字目标库','用于输入文字后整段书写。<br/>本次识别流程不检索它。')]:
    box(x,155,161,178);txt(x+14,174,num,32,TEAL if x==42 else GOLD,'CNB');txt(x+14,219,label,12,INK,'CNB');para(x+14,248,133,body,10,17,maxh=70)
heading(365,'两条路线可以共存')
card(42,402,246,111,'输入文字路线','输入“你好” → 查整字笔顺与轨迹<br/>→ 排版 → 规划 → 连续书写',BLUE)
card(303,402,250,111,'手写单笔路线','手指写一笔 → 匹配基本笔画<br/>→ 按当前位置摆放 → 规划 → 写一笔')
heading(542,'工程核对结果')
para(42,574,511,'已有模块保存在 calligraphy/library.py 与 extended.py；presets.py 负责生成轨迹，curves.py 负责平滑采样。目前 task() 会把模块居中摆放，validate_task() 只接受预设笔画和整字格式，因此需要新增“手写放置”数据格式和验证分支。',10.5,18)
note(680,'功能状态','35 种笔画、53 种偏旁是本次源码实查数量；手写识别、任意位置放置及持续悬停会话仍属本方案待实现功能。3500 字库不作为本次识别依赖。',h=92)

# 04
page('03  触摸屏输出的是一串采样数据','把手指运动看成二维信号 p(t) = [x(t), y(t)]，时间戳帮助检查事件顺序。')
grid(42,157,245,204,5)
raw=np.array([[15,20],[29,19],[55,20],[78,22],[111,20],[150,21],[181,20],[182,49],[182,71],[184,116],[181,151]])
trace(raw,66,185,194,143,TEAL,2,True)
txt(61,337,'金点：按下 / 蓝绿色：移动采样',8.4,MUTED)
box(305,157,248,204)
txt(320,175,'一笔数据示例',12,INK,'CNB')
for i,row in enumerate([('序号','x / px','y / px','t / ms'),('0','120','180','0'),('1','136','181','12'),('2','159','180','25'),('...','...','...','...'),('N','480','490','460')]):
    yy=208+i*23
    for j,v in enumerate(row):txt(319+j*56,yy,v,9.3,TEAL if i==0 else INK)
heading(389,'事件规则要比分类算法先写好')
for x,t,b,col in [(42,'按下','建立 stroke_id；捕获单一触点。',TEAL),(217,'移动','记录坐标与时间；立即画出屏幕墨迹。',BLUE),(392,'松开','只提交一次；随后异步识别。',GOLD)]:card(x,426,161,105,t,b,col)
para(42,554,511,'优先使用 Pointer Events；在板载 WebKit 上做能力检测，必要时增加 Touch Events 适配层。只接通一条事件通道，避免同一触摸被当成两笔。[2]',10.5,18)
note(625,'取消事件绝不能当作松手','pointercancel、失去触点捕获、切换页面或第二个手指介入时，取消当前未提交笔画。普通有效短按可以识别为“点”，但屏幕滚动或异常断点不能自动触发写字。',h=110)

# 05
page('04  预处理：把不同采样速度变得可比较','目标是保留笔画结构，去掉触摸设备带来的重复和抖动。')
noisy=np.vstack([np.column_stack([np.linspace(0,100,29),3*np.sin(np.arange(29)*1.6)]),np.column_stack([100+2*np.sin(np.arange(20)),np.linspace(0,90,20)])])
clean=np.array([[0,0],[100,0],[100,90]],float);rs=resample(clean,64)
for x,t,pts in [(42,'原始采样：忽密忽疏',noisy),(217,'轻度去噪：保留折角',clean),(392,'等弧长重采样：64 点',rs)]:
    box(x,155,161,195);trace(pts,x+24,183,113,117,TEAL,2,True);para(x+10,319,145,t,9.3,14)
heading(380,'为什么要按“路程”重采样？')
para(42,412,511,'你在转角处会写慢，触摸点因此变密。若直接逐点比较，转角会被重复计算很多次。按路径累计长度重新取 64 个等间隔点，可以让快写与慢写更容易匹配。',11,19)
box(42,490,511,79,'#EAF3EF');txt(60,508,'每隔 Δs = 总路径长度 / 63，取一个新点',14,TEAL,'CNB');txt(60,540,'例如总长 126 px，重采样间隔就是 2 px。',10,MUTED)
heading(593,'识别时只改“副本”')
para(42,626,511,'识别副本：平移到统一中心，用同一个比例缩放 X、Y；保存原长宽比与书写方向。原始坐标另行保留，后面用于确定纸上位置。不能把所有笔画都拉成正方形，也不能任意旋转、镜像或颠倒点序。',10.5,18)
note(702,'建议初值，后续用屏幕实测调整','去重距离约 1～2 个显示像素；仅消除小抖动，不抹掉末端钩。零长度或极短轨迹进入“点”的专用判断，避免归一化除零。',h=74)

# 06
page('05  一种笔画，要准备两套模板','识别关注大形状；执行还要表达起笔、转折、收笔和下压变化。')
box(42,155,246,234);box(303,155,250,234)
txt(57,171,'识别模板：横折的主线',12,TEAL,'CNB')
trace([[0,0],[1,0],[1,1]],86,214,147,127,TEAL,4,False,False)
txt(58,363,'干净、有方向、转折位置清楚',9.4,MUTED)
txt(318,171,'执行模板：带笔法的横折',12,GOLD,'CNB')
trace(STROKES['heng_zhe'][1],350,215,151,125,GOLD,3,True)
txt(318,363,'小回锋 + 提按 + 转折与收笔',9.4,MUTED)
heading(418,'为什么不把执行轨迹直接拿来识别？')
para(42,450,511,'手指画横折时，通常不会模仿毛笔的逆锋入纸、局部回转和原地提按。如果把这些细节全算进形状距离，一个正常横折反而可能匹配不好。因此每个模块另外配置一条简化的识别主线。',11,19)
heading(542,'第一版模板怎样准备')
para(42,574,511,'逐一检查现有 35 个模块，为每类配置起点、终点、主要转角、曲线段和末端钩。先各做 3 个形状样例，覆盖略斜、略长、略弯等常见差异；随后用真实手写样本补充。微小回锋从识别主线中移除，执行模板保留。',10.5,18)
note(685,'一个固定编号连接两层','例如识别结果 module_id="heng_zhe"，就调用原工程的横折毛笔模块。修改识别样例不会自动改变毛笔下压上限。',h=85)

# 07
page('06  先快速找候选，再仔细比较','第一版采用可解释的几何模板匹配：每个分数都能画出来、检查出来。')
grid(42,155,151,171,4);trace([[0,0],[.95,.04],[1,.96]],63,182,104,112,TEAL,3,False,False)
txt(62,336,'待识别：手写横折',10.2,INK,'CNB')
arrow(204,240,236,240)
box(246,155,307,191)
txt(262,170,'先计算这些特征',12,TEAL,'CNB')
for i,(a,b) in enumerate([('整体方向','起点到终点朝哪里'),('转折结构','几个明显转弯、怎样转'),('形状比例','宽高比、弯曲程度'),('末端走势','有没有钩，钩向哪里')]):
    yy=207+i*31;txt(262,yy,a,10.5,INK,'CNB');txt(349,yy,b,10,MUTED)
heading(379,'两级计算，避免每次都做重活')
card(42,417,246,119,'第一级：全库快速比较','把每个样例都变成 64 点，计算平均点距与方向差。保留得分最好的 5 个样例；不靠一个硬角度阈值排除整类。')
card(303,417,250,119,'第二级：候选精细对齐','对这 5 个样例做带窗口的 DTW，再结合方向、转折与长宽比评分。弱匹配时可扩大候选。',BLUE)
box(42,560,511,95,'#263631');txt(59,578,'总距离 J = 0.60 × 形状 + 0.15 × 方向',13,'#FFFFFF','CNB');txt(166,607,'+ 0.15 × 转折 + 0.10 × 长宽比',13,'#FFFFFF','CNB')
para(42,678,511,'上述权重是开发初值。各项先归一到 0～1，再用真实手写数据调整；距离越小越相似。它不是“正确率百分比”，不能显示成未经校准的 98% 置信度。',10.5,18)
txt(42,753,'算法参考：几何单笔模板匹配思路见资料 [1]；本页是项目定制设计。',8.7,MUTED)

# 08
page('07  DTW：允许相似笔画“错开一点”','DTW = 动态时间规整。这里用于对齐两条有顺序的轨迹，并非要求手写速度一致。')
box(42,155,511,137)
a=np.array([[0,0],[.2,0],[.4,0],[.6,0],[.8,0],[1,0],[1,.3],[1,.6],[1,1]])
b=np.array([[0,0],[.22,0],[.43,0],[.65,0],[.86,0],[.86,.25],[.86,.5],[.86,.75],[.86,1]])
ap=trace(a,65,183,211,70,TEAL,2,True,False);bp=trace(b,314,183,211,70,GOLD,2,True,False)
txt(65,265,'手写：横段稍长',9.5,MUTED);txt(314,265,'模板：横竖比例略有差异',9.5,MUTED)
heading(318,'像对齐两段采样信号')
para(42,350,511,'普通逐点距离只比较“第 i 个点对第 i 个点”。DTW 允许附近点错位配对，使两个转角对齐；配对次序只能向前，不能把先横后竖改成先竖后横。',10.7,18)
gx,gy,step=56,437,17
txt(56,418,'列：输入点 i；行：模板点 j',8.8,MUTED)
for i in range(11):
    for j in range(11):box(gx+i*step,gy+j*step,step-1,step-1,'#DAEAE5' if abs(i-j)<=2 else '#EDECE6',r=0)
route=[(0,0),(1,1),(2,2),(3,2),(4,3),(5,4),(5,5),(6,6),(7,7),(8,8),(9,9),(10,10)]
for (i,j),(k,l) in zip(route,route[1:]):line(gx+(i+.5)*step,gy+(j+.5)*step,gx+(k+.5)*step,gy+(l+.5)*step,TEAL,2.5)
txt(58,637,'绿色带：只允许附近点对齐',9.2,MUTED)
code(274,431,279,116,['D[i,j] = cost(i,j) + min(','  D[i-1,j],','  D[i,j-1],','  D[i-1,j-1])'],9)
para(274,562,279,'cost(i,j)：两个位置的距离。<br/>D[i,j]：走到这一对点时，累计最小代价。<br/>最终按配对路径长度归一，避免偏爱短路径。',10,17)
note(686,'计算量可以控制','建议 64 点、窗口 ±8 点、精排 5 个样例，约 5×64×17 个格子。识别目标 P95 ≤30 ms，属于待板测的工程目标，不是已达到的成绩。',h=87)

# 09
page('08  模糊、短点、反向书写，怎样处理？','执行你的规则：有效笔画自动选最接近的模块，不再弹窗让你确认。')
for x,t,pts in [(42,'竖与竖钩',[[.5,0],[.5,.8],[.35,.66]]),(217,'点与短撇',[[.65,.25],[.5,.5],[.3,.65]]),(392,'垂露与悬针',[[.5,0],[.5,1]])]:
    box(x,154,161,151);trace(pts,x+42,176,76,86,TEAL,3,False,False);txt(x+25,280,t,10.5,INK,'CNB')
heading(335,'先分清“几何类别”与“笔法变体”')
para(42,368,511,'一条普通竖线无法可靠表达“垂露收笔”还是“悬针收笔”。这类样式由固定默认规则选择；有明显末端钩时再优先匹配竖钩。不要声称仅凭同一条直线就能识别用户的全部笔法意图。',10.5,18)
card(42,451,246,131,'有效但不像标准笔画','始终输出距离最小的候选。第一、第二候选分差很小时，使用稳定的优先级，不随机切换；界面可显示名称，不阻塞执行。')
card(303,451,250,131,'取消或无效输入','取消事件、非有限坐标、跨出有效书写区等不提交运动。轨迹很短时走“点”分支；短按时长与尺寸阈值通过屏幕采样确定。',RED)
heading(610,'反向书写如何约定')
para(42,642,511,'识别时保留点序并对反向轨迹加惩罚；若仍匹配为横或竖，默认采用模板的标准书写方向，位置由整条手写轨迹拟合。这样可保留标准起收笔，但机械臂不一定从手指最先按下的一端起笔。',10.5,18)
note(704,'不需要识别整字','两笔交叉是否成为“十”、三笔是否成为“土”，由你在屏幕上的相对位置决定。第一版不做汉字语义纠错。',h=73)

# 10
page('09  写在哪里？固定屏幕到纸面的映射','识别可以归一化，真正执行必须回到原始位置。整次会话使用同一张“坐标地图”。')
grid(42,159,215,215,5);grid(338,159,215,215,5)
line(85,223,214,223,TEAL,3);line(149,192,149,331,BLUE,3)
line(381,223,510,223,GOLD,3);line(445,192,445,331,GOLD,3)
arrow(271,269,324,269)
txt(64,389,'屏幕有效区域：600 × 600 px',10,INK,'CNB');txt(355,389,'纸面示例区域：60 × 60 mm',10,INK,'CNB')
box(42,429,511,112,'#EAF3EF')
txt(58,445,'u = x / 600，v = y / 600',14,TEAL,'CNB')
txt(58,476,'纸面局部位置：X = 60u，Y = 60v',13,INK,'CNB')
txt(58,508,'屏幕 (120, 180) → 纸面示例区域内 (12, 18) mm',10,MUTED)
para(42,567,511,'上图按左上角为局部原点、Y 向下解释。转换到已有机器人纸面坐标系时，统一处理 Y 轴翻转、区域偏移和纸面基向量；不能在前端和后端各翻转一次。',10.5,18)
para(42,633,511,'模块放置：直线类优先拟合两端；折线类拟合起点、拐点和终点；曲线类做有限度平滑变形。微小回锋保留模板形状。不能仅按包围盒强拉伸，否则水平线的高度接近零时会把笔法压扁。',10.5,18)
note(704,'这张图是换算示例，不是扩大工作区','60 mm 示例区域应放在当前已标定范围内。500×500 mm 工作区仍需另做可达性与纸面验证，本方案不默认启用。',h=73)

# 11
page('10  匹配成功后，怎样生成毛笔轨迹？','手指负责位置和大形状；模板负责提按笔法。最后再求七轴关节轨迹。')
box(42,154,511,239)
txt(60,170,'现有“横”模板的下压安排示意',12,GOLD,'CNB')
xx=np.linspace(89,519,len(STROKES['heng'][1]));dep=np.array([p[2]*4 for p in STROKES['heng'][1]])
for k in range(5):
    yy=221+k*31;line(89,yy,521,yy,LINE,.8);txt(58,yy-5,str(k)+' mm',8.5,MUTED)
for i in range(len(xx)-1):line(xx[i],221+dep[i]*31,xx[i+1],221+dep[i+1]*31,GOLD,2.5)
for i in range(len(xx)):dot(xx[i],221+dep[i]*31,2.3,GOLD)
txt(89,363,'起笔',9.4,INK);txt(274,363,'行笔',9.4,INK);txt(473,363,'收笔',9.4,INK)
txt(227,199,'接触面：下压量为 0',9,MUTED)
heading(423,'四步生成')
para(42,455,511,'① 根据识别结果取执行模板。<br/>② 用手写起点、转角、终点做受控 XY 变形，重新采样。<br/>③ 沿笔法阶段插值下压量，并生成抬笔、空移、落笔段。<br/>④ 以当前关节反馈为逆解种子，检查连续性、笔轴、限位和实际执行路径。',10.8,21)
note(562,'你的毛笔参数怎样进入计算','毛长 9 mm、最粗处约 2 mm；已确认最大允许下压量为 4 mm。模板比例 0.69 对应指令下压 2.76 mm。XY 放大不同比放大 Z 下压；下压量不是牛顿意义的“力”，实际线宽仍需实物验证。',h=112)
para(42,697,511,'现有模板保存 feed_ratio，但当前 SDK 执行路径统一采用 GUI 速度，不会自动兑现每个点的快慢。第一版识别接入沿用该行为；局部速度笔法需另做执行接口与效果验证。',10,17)
txt(42,759,'图为模板指令示意；横坐标是笔法关键帧顺序，不是实测时间。',8.7,MUTED)

# 12
page('11  低延迟：哪些提前做，哪些松手后做？','识别只占整条链路的一部分；不要把发送成功或算法耗时当作真实起动时间。')
for x,t,b,col in [(42,'进入模式时','加载识别模板、机械臂模型；建立持续 SDK 连接；完成就绪检查。',BLUE),(217,'手指移动时','显示墨迹、缓存坐标；更新候选类别。保持执行模板尚未下发。',TEAL),(392,'松手以后','最终匹配、位置拟合、轨迹检查与规划；通过后下发。',GOLD)]:card(x,156,161,149,t,b,col)
heading(340,'已有实测：简单 5 mm 空中直线')
box(42,377,511,120)
barx,bary,bw=61,411,470
left=bw*(113.677/203.446)
box(barx,bary,left,27,TEAL,r=0);box(barx+left,bary,bw-left,27,GOLD,r=0)
txt(barx,385,'约 114 ms：逆解与路径检查',10,TEAL,'CNB');txt(barx+left+8,385,'约 90 ms：下发至运动反馈',9.1,GOLD,'CNB')
txt(61,455,'4 次合计 201～206 ms，平均约 203 ms。',11,INK,'CNB')
para(42,518,511,'该测试未包含触摸识别、完整毛笔模板和落纸。SDK 反馈约每 50 ms 刷新一次，因此结果是“检测到位移超过 0.05 mm”的时间，不是毫秒级精确的物理起动时刻。[3]',10.3,18)
card(42,598,246,133,'识别模块的目标','只对识别计时，目标 P95 ≤30 ms。64 点、模板常驻内存；若 Python 未达标，再将距离与 DTW 内核改为 C++。')
card(303,598,250,133,'完整响应的边界','40 mm 毛笔原型计算约 0.57～0.81 s；此前 0.7～1.0 s 是合成估算，仍需实测识别、移到起点和落纸。',GOLD)
txt(42,755,'约 105 个样例 × 64 点 × 2 坐标 × float32 ≈ 53 KB 原始坐标；Python 对象另占内存。',8.5,MUTED)

# 13
page('12  连续写：把系统分成两条并行工作线','屏幕一直能响应；机械臂每次只执行一笔。线程与队列负责协调，不由触摸回调直接驱动。')
txt(42,159,'输入工作线',12,TEAL,'CNB')
for i,t in enumerate(['采集一笔','识别与放置','提交有序队列']):
    xx=42+i*177;box(xx,190,157,54,'#EAF3EF');txt(xx+18,207,t,11,TEAL,'CNB')
    if i<2:arrow(xx+160,217,xx+173,217)
arrow(475,254,475,286,GOLD)
txt(42,281,'执行工作线',12,GOLD,'CNB')
for i,t in enumerate(['悬停等待','移到起点','落笔与书写','竖直抬笔']):
    xx=42+i*131;box(xx,315,118,56,'#F5E6CE');txt(xx+13,333,t,10.8,INK,'CNB')
    if i<3:arrow(xx+119,343,xx+129,343,GOLD)
line(494,382,494,404,GOLD,1.5);line(494,404,100,404,GOLD,1.5);arrow(100,404,100,380,GOLD)
txt(223,412,'回到等待状态，保持连接',9.7,GOLD)
heading(453,'会话必须有这几条规则')
para(42,486,511,'• 第一版限制最多 2 笔待执行；满队列时提示等待，不静默丢笔。<br/>• session_id + stroke_id 去重，网络重试不得重复画同一笔。<br/>• 正式执行前复核真实关节起点；上一笔没结束，不能用过期姿态直接启动下一笔。<br/>• 停止时停止运动并清空待执行队列；重连不自动重放旧命令。<br/>• 笔画间保持竖直抬笔；退出时只有在状态可信、路径检查通过后才按既有规则归位。',10.5,21)
note(635,'两种“立刻”要分清','你松手后可以立刻识别。如果机械臂还在写上一笔，新笔画必须排队，起动等待时间包含剩余执行时间。不能承诺任意输入速度下都无等待。',h=92)
txt(42,752,'已有的停止、限位、下压上限和运动反馈检查继续保留。',9.5,MUTED)

# 14
page('13  具体改哪些文件、怎么接接口？','以下是拟新增与拟修改清单。识别、放置、规划、下发各自有清楚的边界。')
rows=[('新增识别模板','calligraphy/recognition_templates.py','35 类主线、方向、锚点、变体与模板版本。'),
('新增识别器','calligraphy/recognizer.py','去噪、64 点重采样、候选排序、DTW、稳定选解。'),
('新增手写放置','calligraphy/handwriting.py','原始位置拟合执行模板；生成可重建的手写笔画规格。'),
('新增执行会话','tcb705/handwriting_session.py','持久模型与 SDK、串行执行、悬停等待、停止与去重。'),
('新增界面资源','user_gui/static/handwriting.js / .css','触摸采集、实时墨迹、状态提示；沿用糖画坊风格。'),
('修改现有入口','display_server.py / workbench.py / app.py','转发接口、后台 worker 与现有控制锁互斥。'),
('扩展轨迹校验','calligraphy/presets.py','新增 brush-handwriting-v1；后端按规格重建再校验。')]
yy=153
for i,(a,b,d) in enumerate(rows):
    box(42,yy,511,65,'#FFFFFF' if i%2==0 else '#EEEEE5',r=4)
    txt(54,yy+10,a,10.2,TEAL,'CNB');txt(164,yy+11,b,8.2,INK)
    para(164,yy+30,374,d,9.3,15,maxh=30);yy+=69
box(42,651,511,117,'#263631')
txt(57,664,'建议接口：/api/handwriting/...',11,'#F4D39D','CNB')
for i,s in enumerate(['POST session/start   |  POST strokes','GET  status          |  POST stop','request: session_id, stroke_id, canvas_revision, points[x,y,t]','result: module_id, fit_spec, queue_state, timing']):
    c.setFillColor(white);c.setFont('Courier',8.1);c.drawString(57,H-692-i*17,s)

# 15
page('14  分阶段实施：先认准，再接动作','每一步都有看得见的产物和过关条件，避免把界面、识别与机器人问题混在一起。')
stages=[('A','先做屏幕采集','显示原始轨迹、时间戳和取消原因；连续操作不卡顿；一次松手只提交一次。'),
('B','建立模板并识别','35 类各约 3 个主线样例；显示前 3 名候选和分项距离；任何合法模糊笔画稳定返回最近类。'),
('C','做放置与轨迹预览','先写“十、土、口”：检查相交、相对位置、折角和边界；验证画布缩放后映射不变。'),
('D','做模拟和空中联调','用假 SDK 验证拒绝、超时、重复提交、停止和队列；通过后空中验证实际起点与悬停。'),
('E','最后再验证落纸','在另行确认落纸条件后，按横、竖、撇、横折顺序测；评估粗细、转折和多笔对齐。')]
for i,(tag,title,body) in enumerate(stages):
    yy=151+i*86;box(42,yy,511,77);box(54,yy+15,33,33,TEAL,r=8);txt(64,yy+21,tag,16,'#FFFFFF','CNB')
    txt(101,yy+12,title,11.5,INK,'CNB');para(101,yy+34,435,body,9.7,16,maxh=37)
heading(601,'识别测试集与性能验收')
para(42,633,511,'建议采集 3 人 × 35 模块 × 10 次，共约 1050 笔。按书写人分组留出测试，不能把同一条轨迹的扰动副本同时放进模板和测试集。垂露/悬针等不可辨笔法按几何家族统计，另外统计默认样式选择。目标：可辨家族正确率 ≥95%，识别 P95 ≤30 ms；均待实测。',10.1,17)
para(42,727,511,'至少记录 100 笔的采集、识别、规划、队列和反馈耗时。浏览器与板端时钟未对齐时分别计时，不能直接相减。识别低置信度与运动校验失败必须分开统计。',9.7,16)

# 16
page('15  带着这张清单开始开发','读完后，你应能解释数据怎样流动，也能指出每种错误应该在哪一层处理。','术语 / 资料 / 检查表')
terms=[('重采样','按固定路程间隔重新取点。'),('模板匹配','比较输入轨迹与已知样例。'),('DTW','让两条轨迹局部错位对齐。'),('IK / 逆运动学','由笔尖目标姿态求关节角。'),('SDK','与控制器通信的开发接口。'),('P95','95% 的样本不超过该耗时。')]
for i,(a,b) in enumerate(terms):
    x=42+(i%2)*262;yy=151+(i//2)*63;box(x,yy,249,55);txt(x+12,yy+9,a,10.7,TEAL,'CNB');txt(x+12,yy+31,b,9.2,INK)
heading(362,'能回答这四题，就理解了核心')
para(42,395,511,'1. 为什么识别时可以缩放副本，却不能每一笔都重新居中执行？<br/>2. 为什么仅凭一条直竖，不能可靠区分垂露与悬针？<br/>3. 为什么收到 SDK 成功应答，还不能说机械臂已经开始移动？<br/>4. 为什么“自动匹配最近模板”不意味着取消限位与轨迹检查？',10.4,21)
heading(504,'资料与证据')
refs=[
('[1] 单笔几何模板匹配：$1 Recognizer 原作者页面','https://depts.washington.edu/acelab/proj/dollar/index.html'),
('[2] 触摸事件与取消语义：MDN Pointer Events','https://developer.mozilla.org/en-US/docs/Web/API/Pointer_events')]
yy=538
for title,url in refs:
    txt(42,yy,title,9.7,INK,'CNB');txt(42,yy+18,url,8,BLUE)
    c.linkURL(url,(42,H-yy-32,553,H-yy),relative=0);yy+=49
para(42,642,511,'[3] 本工程空中实测记录：reports/handwriting_latency_20261022/<br/>air_response_live_20261022.json（2026-10-22，4 次成功测试）。<br/>源码核对：calligraphy/library.py、presets.py、curves.py，<br/>tcb705/sdk_motion.py、workbench.py，user_gui/display_server.py。',8.9,15)
note(707,'开始实现时的第一件事','先完成“屏幕画一笔 → 显示匹配模块与放置预览”的闭环；数据和位置都对，再接持久执行会话。当前交付是实施教程，未改动板端程序或让机械臂运动。',h=78)

assert page_no==16
c.save()
OUT.parent.mkdir(parents=True,exist_ok=True)
(Path(__file__).parent/'layout_checks.json').write_text(json.dumps(checks),encoding='utf8')
print(str(OUT));print('PAGES',page_no,'SIZE',OUT.stat().st_size)
