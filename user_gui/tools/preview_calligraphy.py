"""Local GUI preview backed by the real planner and a simulated arm. Never drives hardware."""
import argparse
from pathlib import Path
import sys
import threading

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from app import State,Server
from user_gui.workflow import BoardPipeline,Workflow
from user_gui.display_server import Hub,DisplayServer

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--port',type=int,default=8096)
    args=ap.parse_args()
    folder=ROOT/'build/calligraphy/gui_preview'
    backend=Server(('127.0.0.1',0),State(folder),robot='tcb705',simulation=True,
                   profile=ROOT/'robots/tcb705/profile.demo.json')
    threading.Thread(target=backend.serve_forever,daemon=True).start()
    workflow=Workflow(BoardPipeline('http://127.0.0.1:%d'%backend.server_port,folder),folder)
    display=DisplayServer(('127.0.0.1',args.port),Hub(folder/'uploads',token='local-preview-only'),
                          interfaces=[],workflow=workflow)
    print('SIMULATION_ONLY http://127.0.0.1:%d'%args.port,flush=True)
    try:display.serve_forever()
    finally:
        display.server_close();backend.shutdown();backend.server_close()
