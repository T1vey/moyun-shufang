"""Read-only Ethernet setup inspection and offline coordinate analysis."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tcb705.config import load
from tcb705.commissioning import capture,audit,pivot_tcp
from tcb705.ethernet import inspect

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=('network','capture','audit','pivot'))
    ap.add_argument('--profile',type=Path);ap.add_argument('--input',type=Path)
    ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--probe-ports',action='store_true')
    ap.add_argument('--pose-convention',choices=('xyz_mm_uvw_deg_zyx',))
    args=ap.parse_args()
    if args.output.exists():ap.error('输出已存在，请选择新文件名')
    config=load(args.profile)
    if args.action=='network':data=inspect(config['controller'],args.probe_ports)
    elif args.action=='capture':data=capture(config)
    else:
        if not args.input:ap.error('audit/pivot 需要 --input')
        source=json.loads(args.input.read_text(encoding='utf-8-sig'))
        if args.action=='audit':
            if not args.pose_convention:ap.error('先确认 SDK 位姿约定，再传 --pose-convention')
            data=audit(config,source,args.pose_convention)
        else:data=pivot_tcp(source)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,allow_nan=False,indent=2)
    print('只读/离线结果已保存：'+str(args.output))
if __name__=='__main__':main()
