"""Use the same bounded IK loop for quantized Python and host C++ steps."""
import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import time
import numpy as np
from .model import Model
from .native import NativeStep,python_f32_inputs
from .solve import solve
from .evidence import write_new

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--run',required=True); args=parser.parse_args()
    run=Path(args.run); model=Model.load(ROOT/'config/nominal_so101.json')
    cfg=json.loads((ROOT/'config/contract.json').read_text())
    targets=json.loads((run/'targets.json').read_text())['targets']
    native=NativeStep(run/'wls_step.dll')
    counts={name:Counter() for name in ('python_f32_input','cpp_mixed')}; paired=Counter(); gaps=[]
    with (run/'backend_results.jsonl').open('x',encoding='utf-8') as out:
        for target in targets:
            results={}; c=dict(cfg,weights=target['weights'])
            for name,backend in [('python_f32_input',python_f32_inputs),('cpp_mixed',native)]:
                start=time.perf_counter_ns()
                r=solve(model,target['position'],target['axis'],target['q0'],c,backend=backend)
                elapsed=(time.perf_counter_ns()-start)/1e6
                if r.history[-1]['q']!=r.q_last or r.history[-1]['iteration']!=r.iterations: raise AssertionError('history mismatch')
                if any(not model.legal(h['q']) for h in r.history): raise AssertionError('illegal iteration')
                if r.status=='OK':
                    _,_,p,a=model.task(r.q_solution,target['position'],target['axis'])
                    if p>cfg['position_tolerance_m'] or a>cfg['tilt_tolerance_rad']: raise AssertionError('false success')
                elif r.q_solution is not None: raise AssertionError('stale solution')
                counts[name][r.status]+=1; results[name]=dict(elapsed_ms=elapsed,**asdict(r))
            a,b=results.values(); key=f"python_{a['status']}/cpp_{b['status']}"; paired[key]+=1
            if a['status']=='OK' and b['status']=='OK':
                gaps.append(float(np.max(np.abs(np.array(a['q_solution'])-b['q_solution']))))
            out.write(json.dumps(dict(id=target['id'],results=results),allow_nan=False)+'\n')
    summary=dict(status='PASS',meaning='valid outputs and bounds; success counts are descriptive, not a 100% success gate',
        targets=len(targets),calls=len(targets)*2,native_step_calls=native.calls,status_counts=counts,paired=paired,
        max_joint_difference_when_both_successful=max(gaps,default=None),
        scope='x86 DLL integrated into IK, not ARM/FPGA timing or motion')
    write_new(run/'backend_summary.json',summary)
    print('BACKEND_IK_GATE_PASS '+json.dumps(summary))


if __name__=='__main__': main()
