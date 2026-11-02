"""Planning benchmark on host or PYNQ; never opens a servo port."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'): os.environ[key]='1'
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from planning import nominal,load,drawing_spec,quantization_report,SOURCE
from r1a.model import Model
from r1a.native import python_f32_inputs
from r1b.planner import plan

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--paths',type=Path,default=ROOT/'examples/motion_portrait.paths.json')
    p.add_argument('--backend',choices=('ps','full','target','native'),default='ps')
    p.add_argument('--overlay',type=Path);p.add_argument('--library',type=Path)
    p.add_argument('--machine',type=Path);p.add_argument('--counts',type=Path)
    p.add_argument('--repeats',type=int,default=5);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.repeats<1 or a.repeats>100: p.error('repeats must be 1..100')
    if bool(a.machine)!=bool(a.counts):p.error('machine and fixed counts JSON must be provided together')
    if a.backend in ('full','target') and not a.overlay:p.error('board backend needs overlay')
    if a.backend=='native' and not a.library:p.error('native needs library')
    paths=json.loads(a.paths.read_text(encoding='utf-8'));m,paper,q=nominal();machine=None
    cfg=load('trajectory.json');cfg.update(max_velocity_rad_s=.12,max_acceleration_rad_s2=.3,
        command_period_s=.1,motion_profile='continuous_quintic',max_targets=10000,max_total_ik_iterations=120000)
    if a.machine:
        from motion import angles_from_counts
        machine=json.loads(a.machine.read_text(encoding='utf-8'));m=Model(machine['model']);paper=machine['paper']
        q=angles_from_counts(machine,json.loads(a.counts.read_text(encoding='utf-8')));cfg.update(machine['trajectory'])
    backend=python_f32_inputs
    if a.backend=='native':
        from ik_target_backend import NativeIKTarget
        backend=NativeIKTarget(a.library)
    elif a.backend in ('full','target'):
        from engine import make_backend
        backend=make_backend('wls',a.overlay,pl_mode=a.backend)
    spec=drawing_spec(paths,paper,q);ik=load('contract.json');runs=[]
    warm=plan(m,spec,q,ik,cfg,backend)
    if warm.status!='OK': raise RuntimeError('Warmup failed: '+warm.status)
    for _ in range(a.repeats):
        started=time.perf_counter();result=plan(m,spec,q,ik,cfg,backend)
        if result.status!='OK':raise RuntimeError('Planning failed: '+result.status)
        quant=None
        if machine:
            t=time.perf_counter();quant=quantization_report(m,machine,result.commands)
            result.metrics['timing']['quantization_s']=time.perf_counter()-t
        runs.append(dict(seconds=time.perf_counter()-started,metrics=result.metrics,quantization=quant))
    errors=[];tilts=[]
    for q_result,target in zip([d['attempts'][-1]['q_solution'] for d in result.diagnostics],result.targets):
        pe,te=m.pose_errors(m.pose(q_result),np.asarray(target['position']),np.asarray(target['axis']))
        errors.append(pe);tilts.append(te)
    report=dict(scope='BOARD_PS_PL_NO_MOTOR' if a.backend in ('full','target') else 'HOST_NOT_FPGA_TIMING',
        platform=platform.platform(),backend=a.backend,input_sha256=hashlib.sha256(a.paths.read_bytes()).hexdigest(),
        planner_source=str(SOURCE),effective_trajectory=cfg,ik_config=ik,initial_q=np.asarray(q).tolist(),
        runs=runs,median_s=statistics.median(r['seconds'] for r in runs),
        range_s=[min(r['seconds'] for r in runs),max(r['seconds'] for r in runs)],
        final_target_max_error_m=max(errors),final_target_max_tilt_rad=max(tilts),
        iterations=result.metrics['ik_iterations'],targets=len(result.targets),commands=len(result.commands),
        backend_session=backend.metrics() if hasattr(backend,'metrics') else None,status='PASS')
    if a.overlay:
        report['overlay_hashes']={suffix:hashlib.sha256(a.overlay.with_suffix(suffix).read_bytes()).hexdigest()
            for suffix in ('.bit','.hwh','.registers.json')}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('TARGET_BENCHMARK_PASS',a.backend,'median_s=',round(report['median_s'],4),'targets=',len(result.targets))
if __name__=='__main__':main()
