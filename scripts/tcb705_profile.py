"""Prepare/validate profiles or make a read-only controller query. No motion."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tcb705.config import load,demo_config,readiness
from tcb705.model import Model
from tcb705.artifact import atomic_write
from tcb705.calibration import apply_armvision

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('action',choices=('validate','demo','armvision','feedback','world'))
    ap.add_argument('--profile',type=Path);ap.add_argument('--output',type=Path)
    ap.add_argument('--settings',type=Path,help='ArmVision backend/config/settings.yaml')
    args=ap.parse_args();cfg=demo_config() if args.action=='demo' else load(args.profile)
    if args.action=='world':
        from tcb705.armvision_feedback import read_world
        if not args.profile:ap.error('world requires --profile')
        print(json.dumps(read_world(cfg['controller'],cfg['robot_id']),ensure_ascii=False,indent=2));return
    if args.action=='feedback':
        from tcb705.bridge import feedback
        if not args.profile:ap.error('feedback requires --profile')
        print(json.dumps(feedback(cfg),ensure_ascii=False,indent=2));return
    if args.action=='armvision':
        from tcb705.armvision_import import import_settings
        if not args.settings:ap.error('armvision requires --settings')
        calibration,source=import_settings(args.settings)
        cfg=apply_armvision(cfg,calibration);cfg['calibration_source']=source
    model=Model(cfg)
    if args.action in ('demo','armvision'):
        if not args.output:ap.error('requires --output')
        if args.output.exists():ap.error('output already exists; choose a new filename')
        atomic_write(args.output,json.dumps(cfg,ensure_ascii=False,allow_nan=False,indent=2).encode())
    print(json.dumps(dict(model_sha256=model.model_sha256,readiness=readiness(cfg),
        configured_start_tcp_m=model.fk(cfg['q_start_rad'])[:3,3].tolist(),
        output=str(args.output) if args.output else None),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
