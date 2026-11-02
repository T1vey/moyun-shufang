"""Board target-solver gate; no servo port or motion execution."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from ik_target_backend import PynqIKTarget
from ik_target_contract import STATUSES
from scripts.generate_target_vectors import cases

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--overlay',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--attach-only',action='store_true')
    p.add_argument('--platform-manifest',type=Path)
    p.add_argument('--platform-ready',type=Path)
    a=p.parse_args()
    core=PynqIKTarget(a.overlay,load_policy='attach' if a.attach_only else 'download',
        platform_manifest=a.platform_manifest,platform_ready=a.platform_ready)
    count=0;maximum=0.;statuses={}
    for m,pos,axis,q,cfg,mode,want,golden in cases():
        result=core.solve_target(m,pos,axis,q,cfg,mode=mode)
        expected=STATUSES.get(want)
        if (want<0 and result.status=='OK') or (want>=0 and result.status!=expected):
            raise AssertionError('case %d: %s expected %s'%(count,result.status,expected))
        if core.faulted:raise AssertionError('PL session faulted at case '+str(count))
        if result.status=='OK':
            np.testing.assert_allclose(result.q_solution,golden,atol=.003,rtol=0)
            maximum=max(maximum,result.position_error_m)
        statuses[result.status]=statuses.get(result.status,0)+1;count+=1
    report=dict(scope='BOARD_TARGET_PS_PL_NO_MOTOR_IO',status='PASS',cases=count,
        statuses=statuses,max_position_error_m=maximum,metrics=core.metrics(),
        hashes={suffix:hashlib.sha256(a.overlay.with_suffix(suffix).read_bytes()).hexdigest()
            for suffix in ('.bit','.hwh','.registers.json')})
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('TARGET_OVERLAY_PASS',count)
if __name__=='__main__':main()
