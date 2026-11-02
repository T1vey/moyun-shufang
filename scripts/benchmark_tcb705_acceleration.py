"""Compare frozen pre-port planner with 1013-style batching; no robot commands."""
import argparse,importlib.util,json,platform,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tcb705.config import demo_config
from tcb705.planner import plan

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--repeat',type=int,default=3);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--small-only',action='store_true');args=ap.parse_args()
    fixture=ROOT/'tests/fixtures/tcb705_accel'
    spec=importlib.util.spec_from_file_location('tcb705.before_acceleration',fixture/'planner_before.py');before=importlib.util.module_from_spec(spec);spec.loader.exec_module(before)
    cases={'two_strokes':dict(units='mm',width_mm=100,height_mm=100,paths=[[[40,45],[60,45]],[[40,55],[60,55]]])}
    if not args.small_only:
        portrait=json.loads((fixture/'portrait_100mm.json').read_text())
        # Full 25-stroke file exceeds the existing 150k frame budget on this
        # uncommissioned demo profile. Name this limited benchmark honestly.
        portrait['paths']=portrait['paths'][:8];cases['portrait_excerpt_8strokes_100mm']=portrait
    report=dict(platform=platform.platform(),python=sys.version,physical_motion=False,results=[])
    for name,paths in cases.items():
        cfg=demo_config();cfg['planning']['max_plan_seconds']=3600
        # This frozen portrait exceeds the original curve-error gate at 1 mm.
        # Use identical 0.5 mm spacing for BOTH versions, without relaxing gates.
        if name.startswith('portrait_'):cfg['planning']['sample_step_m']=.0005
        durations={'before':[],'after':[]};baseline=None;result=None
        for i in range(args.repeat):
            for label,fn in [('before',before.plan),('after',plan)]:
                start=time.perf_counter();r=fn(paths,cfg);durations[label].append(time.perf_counter()-start)
                if label=='before':baseline=r
                else:result=r
                print(name,label,i,durations[label][-1],flush=True)
            np.testing.assert_allclose(result['q_rad'],baseline['q_rad'],atol=3e-7,rtol=0)
            np.testing.assert_allclose(result['times'],baseline['times'],atol=1e-6,rtol=0)
        row=dict(case=name,strokes=len(paths['paths']),sample_step_m=cfg['planning']['sample_step_m'],durations_s=durations,
            median_before_s=float(np.median(durations['before'])),median_after_s=float(np.median(durations['after'])),
            max_q_difference_rad=float(np.max(abs(result['q_rad']-baseline['q_rad']))),
            max_time_difference_s=float(np.max(abs(result['times']-baseline['times']))),metrics=result['metrics'])
        row['speedup']=row['median_before_s']/row['median_after_s'];report['results'].append(row)
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('BENCHMARK_COMPLETE',args.output)
if __name__=='__main__':main()
