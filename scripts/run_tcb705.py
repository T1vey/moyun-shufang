"""Start the inherited sugar UI and the seven-axis backend without robot motion."""
import argparse
import os
from pathlib import Path
import subprocess
import signal
import sys
import time
import urllib.request
import webbrowser

ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--simulation',action='store_true');ap.add_argument('--allow-real',action='store_true')
    ap.add_argument('--profile',type=Path);ap.add_argument('--data-dir',type=Path,default=ROOT/'tcb705_data')
    ap.add_argument('--backend-port',type=int,default=8785);ap.add_argument('--web-port',type=int,default=8095)
    ap.add_argument('--secrets-file',type=Path,default=ROOT/'config/secrets.local.json');ap.add_argument('--no-browser',action='store_true')
    args=ap.parse_args()
    for port in (args.backend_port,args.web_port):
        if not 1024<=port<=65535:ap.error('invalid port')
    if args.backend_port==args.web_port:ap.error('ports must differ')
    backend=[sys.executable,'-B',str(ROOT/'app.py'),'--robot','tcb705','--port',str(args.backend_port),'--data-dir',str(args.data_dir)]
    if args.simulation:backend+=['--simulation']
    if args.allow_real:backend+=['--allow-real']
    if args.profile:backend+=['--tcb-profile',str(args.profile)]
    if args.secrets_file.is_file():backend+=['--secrets-file',str(args.secrets_file)]
    display=[sys.executable,'-B',str(ROOT/'user_gui/display_server.py'),'--no-browser','--bind','0.0.0.0','--port',str(args.web_port),'--workflow','--backend-url','http://127.0.0.1:%d'%args.backend_port,'--data-dir',str(args.data_dir),'--secrets-file',str(args.secrets_file)]
    children=[];flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    def terminate(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,terminate)
    try:
        children.append(subprocess.Popen(backend,cwd=str(ROOT),creationflags=flags))
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            if children[0].poll() is not None:raise RuntimeError('天链后端启动失败，请检查端口或编译依赖')
            try:
                with opener.open('http://127.0.0.1:%d/api/status'%args.backend_port,timeout=1) as response:response.read()
                break
            except OSError:time.sleep(.1)
        else:raise RuntimeError('后端启动超时')
        children.append(subprocess.Popen(display,cwd=str(ROOT),creationflags=flags))
        url='http://127.0.0.1:%d/'%args.web_port
        print('TCB705 UI:',url,'simulation=',args.simulation,flush=True)
        if not args.no_browser:time.sleep(1);webbrowser.open(url)
        while all(p.poll() is None for p in children):time.sleep(.5)
        raise RuntimeError('天链服务已退出，请检查日志')
    except KeyboardInterrupt:pass
    finally:
        for p in reversed(children):
            if p.poll() is None:
                p.terminate()
                if p is children[0]:
                    # Backend may own live CMA buffers: let cancellation drain
                    # through the inherited 1013 guardian, never SIGKILL it.
                    p.wait();continue
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:p.kill();p.wait()
if __name__=='__main__':main()
