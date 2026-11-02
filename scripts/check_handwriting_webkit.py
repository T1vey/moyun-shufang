"""Real board WebKitGTK regression, isolated Xvfb + loopback fake API only.

Does not import robot code or contact the real app/controller. Run with:
WEBKIT_DISABLE_COMPOSITING_MODE=1 xvfb-run -a python3 scripts/check_handwriting_webkit.py
"""
import ctypes as C
import json
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import threading,time,traceback
import gi
gi.require_version('Gtk','3.0');gi.require_version('WebKit2','4.0')
from gi.repository import Gtk,WebKit2,GLib

ROOT=Path(__file__).resolve().parents[1]/'user_gui/static'
state=dict(session_id='isolated-test',phase='READY',character=1,size_mm=60,pending_size_mm=60,
           speed_pct=60,message='隔离浏览器测试',revision=1,simulation=True,stop_confirmed=False,
           next_requested=False,strokes=[])
requests=[];result={};errors=[]
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path=='/api/state':return self.reply({'control_token':'test-only'})
        if self.path.startswith('/api/handwriting/'):return self.reply(state)
        if self.path=='/handwriting':file=ROOT/'handwriting.html'
        elif self.path.startswith('/static/handwriting.'):file=ROOT/self.path.rsplit('/',1)[1]
        else:
            self.send_response(200);self.end_headers();self.wfile.write(b'<title>returned</title>');return
        data=file.read_bytes();self.send_response(200)
        self.send_header('Content-Type',{'.js':'application/javascript','.css':'text/css','.html':'text/html'}[file.suffix]+'; charset=utf-8')
        self.end_headers();self.wfile.write(data)
    def reply(self,data):
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
        try:self.wfile.write(json.dumps(data).encode())
        except (BrokenPipeError,ConnectionResetError):pass  # Browser may leave during heartbeat.
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
        requests.append(self.path)
        if self.path.endswith('/stroke'):
            state['strokes'].append(dict(id=data['stroke_id'],number=len(state['strokes'])+1,
                points=data['points'],status='DONE',match={'name':'横','ambiguous':False}))
            state['revision']+=1
        elif self.path.endswith('/close'):
            state.update(phase='FAULT',message='测试：停止未确认，仍持有后台锁',stop_confirmed=False)
            state['revision']+=1
        self.reply(state)

server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
url='http://127.0.0.1:%d'%server.server_port
w=Gtk.Window();w.set_decorated(False);w.set_default_size(1024,600);w.move(0,0)
view=WebKit2.WebView();w.add(view)
view.get_settings().set_enable_write_console_messages_to_stdout(True)
manager=view.get_user_content_manager()
manager.add_script(WebKit2.UserScript.new('window.testErrors=[];window.onerror=function(m){window.testErrors.push(String(m));};',
    WebKit2.UserContentInjectedFrames.ALL_FRAMES,WebKit2.UserScriptInjectionTime.START,None,None))
w.show_all();view.load_uri(url+'/handwriting')
def js(code):
    event=threading.Event();out=[]
    def done(v,r,_):
        try:out.append(v.run_javascript_finish(r).get_js_value().to_string())
        except Exception as e:out.append(e)
        event.set()
    def begin():view.run_javascript(code,None,done,None);return False
    GLib.idle_add(begin)
    if not event.wait(8):raise RuntimeError('WebKit JS timeout')
    if isinstance(out[0],Exception):raise out[0]
    return out[0]
def until(code,test,timeout=12):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=js(code)
        if test(value):return value
        time.sleep(.15)
    raise AssertionError('Wait failed: '+code+' = '+value)

def run():
    try:
        until("document.getElementById('statusTitle')&&document.getElementById('statusTitle').textContent",lambda x:x=='悬停等待')
        caps=json.loads(js("JSON.stringify({pointer:typeof PointerEvent,capture:typeof document.getElementById('ink').setPointerCapture,errors:window.testErrors})"))
        assert caps['pointer']=='undefined',caps
        rect=json.loads(js("JSON.stringify(document.getElementById('ink').getBoundingClientRect().toJSON())"))
        assert rect['width']>400 and rect['height']>400,rect
        js("""(function(){var c=document.getElementById('ink'),ctx=c.getContext('2d'),old=ctx.clearRect;window.inkClearCount=0;ctx.clearRect=function(){window.inkClearCount++;return old.apply(ctx,arguments);};c.addEventListener('mousedown',function(){window.inkClearCount=0;},true);return 'instrumented';})()""")
        x11=C.CDLL('libX11.so.6');xt=C.CDLL('libXtst.so.6')
        x11.XOpenDisplay.argtypes=[C.c_char_p];x11.XOpenDisplay.restype=C.c_void_p
        x11.XFlush.argtypes=[C.c_void_p]
        xt.XTestFakeMotionEvent.argtypes=[C.c_void_p,C.c_int,C.c_int,C.c_int,C.c_ulong]
        xt.XTestFakeButtonEvent.argtypes=[C.c_void_p,C.c_uint,C.c_int,C.c_ulong]
        display=x11.XOpenDisplay(None);assert display
        def move(x,y):xt.XTestFakeMotionEvent(display,-1,int(x),int(y),0);x11.XFlush(display)
        def button(down):xt.XTestFakeButtonEvent(display,1,int(down),0);x11.XFlush(display)
        # Same mouse-input path used by the actual GT911 X11 bridge.
        move(rect['x']+80,rect['y']+150);button(True)
        for i in range(16):move(rect['x']+80+i*15,rect['y']+150);time.sleep(.025)
        assert js("String(document.getElementById('emptyHint').hidden)")=='true'
        ink=js("(function(){var c=document.getElementById('ink');return String(c.getContext('2d').getImageData(0,0,c.width,c.height).data.some(function(v,i){return i%4===3&&v>0;}));})()")
        assert ink=='true','No immediate canvas ink'
        clears=int(js('String(window.inkClearCount)'))
        assert clears==1,('Full canvas redraw during drag',clears)
        bitmap=int(js("String(document.getElementById('ink').width)"));assert bitmap==420
        button(False)
        until("document.getElementById('characterCounter').textContent",lambda x:'1 笔' in x)
        assert len(state['strokes'])==1 and len(state['strokes'][0]['points'])>=3
        # Synthetic touch events exercise the second fallback without relying
        # on the availability of the Touch constructor in this old browser.
        js("""(function(){var c=document.getElementById('ink'),r=c.getBoundingClientRect();function t(type,x){var e=new Event(type,{bubbles:true,cancelable:true}),p={identifier:7,clientX:r.left+x,clientY:r.top+230};Object.defineProperty(e,'changedTouches',{value:[p]});Object.defineProperty(e,'touches',{value:type==='touchend'?[]:[p]});c.dispatchEvent(e);}t('touchstart',60);t('touchmove',160);t('touchend',300);return 'ok';})()""")
        until("document.getElementById('characterCounter').textContent",lambda x:'2 笔' in x)
        assert len(state['strokes'])==2
        # FAULT and an unconfirmed stop must not trap navigation.
        state.update(phase='FAULT',message='测试准备故障');state['revision']+=1
        until("document.getElementById('statusTitle').textContent",lambda x:x=='需要处理')
        errors.extend(json.loads(js('JSON.stringify(window.testErrors)')))
        start=time.monotonic();js("document.querySelector('[data-mode=\"书法模式\"]').click();'clicked'")
        until('location.href',lambda x:x==url+'/?mode=calligraphy',timeout=4)
        assert state['phase']=='FAULT' and not state['stop_confirmed']
        assert '/api/handwriting/close' in requests and not errors,errors
        first_nav=round((time.monotonic()-start)*1000)
        js("location.href="+json.dumps(url+'/handwriting')+";'return to test'")
        until("document.getElementById('statusTitle')&&document.getElementById('statusTitle').textContent",lambda x:x=='需要处理')
        js("document.querySelector('[data-mode=\"图案模式\"]').click();'clicked'")
        until('location.href',lambda x:x==url+'/',timeout=4)
        result.update(status='PASS',capabilities=caps,strokes=2,ink_before_release=True,
            full_canvas_redraws_during_drag=clears,canvas_size=bitmap,
            fault_navigation_ms=first_nav,modes=['calligraphy','pattern'],robot_io=False)
    except Exception as e:
        result.update(status='FAIL',error=str(e),traceback=traceback.format_exc())
    finally:GLib.idle_add(Gtk.main_quit)
threading.Thread(target=run,daemon=True).start()
Gtk.main();server.shutdown();print('WEBKIT_CHECK '+json.dumps(result,ensure_ascii=False),flush=True)
raise SystemExit(0 if result.get('status')=='PASS' else 1)
