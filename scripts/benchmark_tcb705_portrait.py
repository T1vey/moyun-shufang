"""Compare the handoff portrait on CPU and real PL, with no controller I/O."""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tcb705.config import load
from tcb705.model import Model
from tcb705.planner import _plan
from tcb705.planning_batches import ChainDispatcher
from tcb705.planning_session import PlanningSession
from scripts.benchmark_tcb705_hardware import compare_geometry


@contextlib.contextmanager
def measure_ik():
    original = ChainDispatcher.next
    counts = dict(calls=0, wall_s=0.0)
    def measured(self, *args, **kwargs):
        start = time.perf_counter()
        try:
            return original(self, *args, **kwargs)
        finally:
            counts['wall_s'] += time.perf_counter() - start
            counts['calls'] += 1
    with patch.object(ChainDispatcher, 'next', measured):
        yield counts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--repeat', type=int, default=3)
    ap.add_argument('--cpu-only', action='store_true')
    a = ap.parse_args()
    if a.repeat < 1: ap.error('repeat must be positive')
    config = load(ROOT/'robots/tcb705/profile.armvision_web.json')
    config['planning']['sample_step_m'] = .0005
    config['planning']['max_plan_seconds'] = 3600
    picture = ROOT/'examples/motion_portrait.paths.json'
    paths = json.loads(picture.read_text(encoding='utf-8'))
    paths['paths'] = paths['paths'][:8]
    model = Model(config)
    target = np.eye(4); target[:3, :3] = config['tool_rotation']
    target[:3, 3] = np.array([-398.993, 20.039, 274.334])/1000
    seed = np.array(config['q_start_rad'])
    solved = model.solve(target, seed, seed)
    if not solved['ok']: raise RuntimeError('Offline benchmark seed IK failed')
    q0 = solved['q']
    report = dict(platform=platform.platform(),physical_motion=False,
        image='examples/motion_portrait.paths.json',image_sha256=hashlib.sha256(picture.read_bytes()).hexdigest(),
        strokes=8,sample_step_m=.0005,q_start_rad=q0.tolist(),runs=[],
        ik_timing_definition='ChainDispatcher.next wall time per target; includes transport, CPU verification and fallback; excludes one-time attach and initial seed solve')
    session = PlanningSession()
    try:
        if not a.cpu_only:
            from tcb705.accel_runtime import attached_identity
            cfg,_,hashes,_,_ = attached_identity()
            core,reason = session.prepare()
            if core is None: raise RuntimeError(reason)
            report.update(build_id=cfg['build_id'],artifact_hashes=hashes,attach_once_s=session.attach_s)
        for i in range(a.repeat):
            results = {}; row = dict(iteration=i)
            modes = ('cpu',) if a.cpu_only else ('cpu','pl')
            for mode in modes:
                transport = session.core.transport if mode=='pl' else None
                counters = ('write_s','wait_s','read_s')
                before = {key:getattr(transport,key,0.) for key in counters}
                with measure_ik() as timing:
                    start=time.perf_counter()
                    results[mode] = (_plan if mode=='cpu' else session.plan)(paths,config,q0)
                    wall=time.perf_counter()-start
                metrics=results[mode]['metrics']
                row[mode]=dict(total_s=wall,ik_wall_s=timing['wall_s'],ik_targets=timing['calls'],
                    ik_ms_per_target=1000*timing['wall_s']/max(timing['calls'],1),metrics=metrics)
                if transport is not None:
                    row[mode]['transport_s'] = {key:getattr(transport,key,0.)-before[key] for key in counters}
                print(mode,i,'total_s',wall,'ik_ms_per_target',row[mode]['ik_ms_per_target'],flush=True)
                if mode=='pl' and (metrics['ik_backend']!='ZYNQ_PL_7R_BATCH' or metrics['pl_rows_cpu_verified']<=0 or metrics['ik_accel_errors']):
                    raise RuntimeError('Real PL execution did not pass: '+json.dumps(metrics))
            if not a.cpu_only:
                row['comparison']=compare_geometry(results['cpu'],results['pl'],config)
                row['total_speedup']=row['cpu']['total_s']/row['pl']['total_s']
            report['runs'].append(row)
            a.output.parent.mkdir(parents=True,exist_ok=True)
            a.output.write_text(json.dumps(report,indent=2)+'\n')
        print('PORTRAIT_BENCHMARK_PASS',a.output,flush=True)
    finally:
        session.close()


if __name__=='__main__':main()
