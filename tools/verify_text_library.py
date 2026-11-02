"""Offline verification only: FK/IK and SDK program construction; no network.

All selected glyphs in 40-mm six-character pages, plus each at 70 mm. Uses an
explicit saved profile, records its digest. It never reads the live robot.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from calligraphy.glyph_store import manifest
from calligraphy.composer import task
from calligraphy.presets import profile,BRUSH,binding
from tcb705.config import load
from tcb705.model import Model
from tcb705.planner import plan
from tcb705.artifact import freeze,check_frozen
from tcb705.web_executor import prepare_joint,build,settings


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--profile',type=Path,required=True)
    ap.add_argument('--report',type=Path,required=True)
    ap.add_argument('--characters',type=Path,help='Optional explicit subset for a labelled representative check')
    ap.add_argument('--individual',action='store_true',help='Test each selected character separately at both size extremes')
    args=ap.parse_args()
    c=load(args.profile)
    # Explicit simulation-only copy using the user's already confirmed limit.
    c['calligraphy']=dict(BRUSH,max_press_mm=4.,verified=True,calibration_binding=binding(c))
    model=Model(c);q0=model.from_sdk(c['execution']['web_program']['home']['joint_degrees']).tolist()
    chars=manifest()['characters']
    if args.characters:
        chars=''.join(args.characters.read_text(encoding='utf-8').split())
        if not chars or len(chars)!=len(set(chars)) or set(chars)-set(manifest()['characters']):
            raise ValueError('Invalid representative selection')
    results=[];started=time.perf_counter()
    cases=([(ch,40) for ch in chars] if args.individual else [(chars[i:i+6],40) for i in range(0,len(chars),6)])+[(ch,70) for ch in chars]
    for i,(text,size) in enumerate(cases):
        row=dict(text=text,size_mm=size)
        try:
            p=plan(task(text,size,0,c),c,q0)
            doc,nodes=freeze(p,'real');check_frozen(doc,nodes,c)
            row.update({k:p['metrics'][k] for k in ('nodes','planning_s','max_path_error_m','max_orientation_error_rad')})
            # Program construction on representative multi-character pages and
            # 70-mm complex glyphs, not a physical SDK execute() call.
            if i<3 or text in ('福','国','意'):
                prepared=prepare_joint(c,nodes)
                program=build(c,nodes,settings(c),joint_keep=prepared.keep)
                row.update(program_checked=True,blocks=len(prepared.keep)-1)
            row['status']='PASS'
        except Exception as exc:row.update(status='FAIL',error=str(exc))
        results.append(row)
        if (i+1)%25==0:print('%d/%d checked, failures=%d'%(i+1,len(cases),sum(x['status']=='FAIL' for x in results)),flush=True)
    report=dict(profile=str(args.profile),profile_sha256=hashlib.sha256(args.profile.read_bytes()).hexdigest(),
                library=manifest()['version'],library_count=manifest()['count'],verified_characters=chars,
                coverage='representative subset' if args.characters else 'full library',
                layout_test='individual at 40 and 70 mm' if args.individual else 'six-character 40 mm pages and individual 70 mm',
                physical_motion=False,press_mm=4.,elapsed_s=time.perf_counter()-started,
                cases=results,passed=sum(r['status']=='PASS' for r in results),failed=sum(r['status']=='FAIL' for r in results))
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False),flush=True)
    return int(report['failed']>0)


if __name__=='__main__':raise SystemExit(main())
