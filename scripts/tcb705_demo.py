"""No-controller demonstration of planning, prediction and native execution."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tcb705.config import demo_config
from tcb705.planner import plan
from tcb705.artifact import save
from tcb705.bridge import execute
from vision import preset
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--shape',choices=('line','circle','square','two-strokes'),default='square');ap.add_argument('--output',type=Path,default=ROOT/'build/tcb705/demo');ap.add_argument('--paths',type=Path);args=ap.parse_args()
    paths=json.loads(args.paths.read_text(encoding='utf-8')) if args.paths else preset(args.shape,args.output,100,100)
    cfg=demo_config();result=plan(paths,cfg);save(result,args.output,'demo');outcome=execute(args.output,cfg,simulation=True)
    print(json.dumps({'planning':result['metrics'],'execution':outcome,'preview':str(args.output/'preview.svg')},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
