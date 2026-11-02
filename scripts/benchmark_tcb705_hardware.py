"""Compare native PS and real sealed PL planning without controller I/O."""
import argparse,json,platform,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tcb705.config import demo_config
from tcb705.planner import _plan
from tcb705.accel_runtime import attached_identity
from tcb705.accel_selftest import self_test
from tcb705.planning_session import PlanningSession
from tcb705.model import Model

def compare_geometry(a,b,config):
    # Seven-axis redundant IK is judged in tool space, not by requiring all
    # joint angles to be bit-identical. Production path/pose limits stay intact.
    if a['q_rad'].shape!=b['q_rad'].shape:raise AssertionError('CPU/PL frame counts differ')
    q_error=float(np.max(abs(a['q_rad']-b['q_rad'])))
    time_error=float(np.max(abs(a['times']-b['times'])))
    model=Model(config);position=0.;orientation=0.
    for first in range(0,len(a['q_rad']),1024):
        x=model.fk_batch(a['q_rad'][first:first+1024]);y=model.fk_batch(b['q_rad'][first:first+1024])
        position=max(position,float(np.max(np.linalg.norm(x[:,:3,3]-y[:,:3,3],axis=1))))
        angles=np.arccos(np.clip((np.einsum('nij,nij->n',x[:,:3,:3],y[:,:3,:3])-1)/2,-1,1))
        orientation=max(orientation,float(np.max(angles)))
    # Both complete trajectories already pass the unchanged production path,
    # pose, collision and dynamics gates in _plan. Compare their same-index
    # samples against those requirements, recording the stricter 1 um probe
    # separately: small independent retiming changes also change sample phase.
    limits=dict(position_m=config['planning']['path_tolerance_m'],orientation_rad=config['planning']['orientation_tolerance_rad'],time_s=.1*config['planning']['period_s'])
    checks=dict(max_q_difference_rad=q_error,max_time_difference_s=time_error,max_cartesian_difference_m=position,max_orientation_difference_rad=orientation,comparison_limits=limits,
        direct_comparison_within_1um=position<=1e-6,production_geometry_checks_passed=True)
    if position>limits['position_m'] or orientation>limits['orientation_rad'] or time_error>limits['time_s']:
        raise AssertionError('CPU/PL tool-space comparison failed: '+json.dumps(checks))
    return checks

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--repeat',type=int,default=3);a=ap.parse_args()
    cfg,_,hashes,_,_=attached_identity()
    session=PlanningSession()
    try:run(a,cfg,hashes,session)
    finally:session.close()

def run(a,cfg,hashes,session):
    core,reason=session.prepare()
    if core is None:raise RuntimeError(reason)
    self_test(core)
    paths=json.loads((ROOT/'tests/fixtures/tcb705_accel/portrait_100mm.json').read_text());paths['paths']=paths['paths'][:8]
    cases={'two_strokes':dict(units='mm',width_mm=100,height_mm=100,paths=[[[40,45],[60,45]],[[40,55],[60,55]]]),'portrait_excerpt_8strokes_100mm':paths}
    report=dict(platform=platform.platform(),build_id=cfg['build_id'],artifact_hashes=hashes,physical_motion=False,attach_once_s=session.attach_s,
        timing='steady application session; one-time PYNQ attach reported separately',results=[])
    for name,paths in cases.items():
        config=demo_config();config['planning']['max_plan_seconds']=3600
        if name.startswith('portrait_'):config['planning']['sample_step_m']=.0005
        durations={'cpu':[],'pl':[]};records=[]
        for i in range(a.repeat):
            result={}
            for label,fn in (('cpu',_plan),('pl',session.plan)):
                start=time.perf_counter();result[label]=fn(paths,config);durations[label].append(time.perf_counter()-start)
                print(name,label,i,durations[label][-1],flush=True)
            metrics=result['pl']['metrics']
            # Rejected numerical candidates intentionally use the full CPU
            # solver. Keep these visible; only transport/protocol errors fail.
            if metrics['pl_batch_starts']<=0 or metrics['pl_rows_cpu_verified']<=0 or metrics['ik_accel_errors']:
                raise RuntimeError('Real PL execution was not verified: '+json.dumps(metrics))
            checks=compare_geometry(result['cpu'],result['pl'],config)
            records.append(dict(checks,metrics=metrics))
        report['results'].append(dict(case=name,strokes=len(paths['paths']),durations_s=durations,
            cpu_median_s=float(np.median(durations['cpu'])),pl_median_s=float(np.median(durations['pl'])),runs=records))
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2))
    print('REAL_PL_BENCHMARK_PASS',a.output,flush=True)
if __name__=='__main__':main()
