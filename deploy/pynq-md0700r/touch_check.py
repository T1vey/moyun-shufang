"""Temporary, full-screen touch acceptance overlay; contains no motion actions."""
import json,os,subprocess,time,tkinter as tk
from pathlib import Path
os.environ['DISPLAY']=':9'
folder=Path('/run/so101-lcd')
result=folder/'touch-check.json'
dismiss=folder/'touch-check-dismiss'
if dismiss.exists():dismiss.unlink()
root=tk.Tk()
root.overrideredirect(True)
root.geometry('1024x600+0+0')
root.attributes('-topmost',True)
canvas=tk.Canvas(root,width=1024,height=600,bg='#101f32',highlightthickness=0)
canvas.pack()
targets=[(160,160),(850,440),(512,300)]
index=0
clicks=[]
started=time.monotonic()
accepted=False
normal_exit=False
def save():
    result.write_text(json.dumps({'status':'PASS' if accepted else 'WAITING',
                                 'completed':index,'clicks':clicks,'targets':targets})+'\n')
def paint():
    canvas.delete('all')
    canvas.create_text(512,52,text='触摸位置确认',fill='white',font=('sans',25,'bold'))
    if accepted:
        canvas.create_text(512,260,text='三处点击均正确',fill='#4ade80',font=('sans',30,'bold'))
        canvas.create_text(512,325,text='正在恢复绘画控制台，请稍候',fill='white',font=('sans',20))
    else:
        canvas.create_text(512,95,text='请点击圆心，然后松开手指  ·  %d / 3'%(index+1),fill='#cbd5e1',font=('sans',18))
        x,y=targets[index]
        canvas.create_oval(x-44,y-44,x+44,y+44,fill='#ea580c',outline='white',width=3)
        canvas.create_text(x,y,text=str(index+1),fill='white',font=('sans',24,'bold'))
def released(event):
    global index,accepted
    if accepted:return
    x,y=targets[index]
    hit=(event.x-x)**2+(event.y-y)**2<=55**2
    clicks.append(dict(x=event.x,y=event.y,target=index+1,hit=hit))
    if hit:index+=1
    accepted=index==len(targets)
    save();paint()
def tick():
    global normal_exit
    root.lift()
    if accepted and dismiss.exists():normal_exit=True;root.destroy();return
    if time.monotonic()-started>180:root.destroy();return
    root.after(250,tick)
canvas.bind('<ButtonRelease-1>',released)
save();paint();root.after(250,tick)
try:root.mainloop()
finally:
    if not normal_exit:subprocess.run(['systemctl','stop','so101-gt911.service'],timeout=20)
