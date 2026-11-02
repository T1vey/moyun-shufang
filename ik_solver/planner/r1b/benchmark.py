import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time
from r1a.evidence import write_new
from r1a.model import Model
from r1a.native import NativeStep,python_f32_inputs
from .fixtures import drawings
from .planner import plan

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--run',required=True); args=parser.parse_args()
    run=Path(args.run); model=Model.load(ROOT/'config/nominal_so101.json')
    ik=json.loads((ROOT/'config/contract.json').read_text()); cfg=json.loads((ROOT/'config/trajectory.json').read_text())
    native=NativeStep(run/'wls_step.dll'); specs=drawings(model)
    write_new(run/'drawing_fixtures.json',dict(scope='nominal only',training_count=5,holdout_count=3,specs=specs))
    folder=run/'trajectories'; folder.mkdir(); results=[]
    for i,spec in enumerate(specs):
        for name,backend in [('python',python_f32_inputs),('cpp',native)]:
            for recovery in (False,True):
                start=time.perf_counter_ns()
                result=plan(model,spec,spec['q0'],ik,cfg,backend,recovery)
                elapsed=(time.perf_counter_ns()-start)/1e6
                label=f"{spec['name']}_{name}_{'recovery' if recovery else 'baseline'}"
                write_new(folder/f'{label}.json',asdict(result))
                if result.status=='OK':
                    if result.metrics['completed_targets']!=result.metrics['total_targets']: raise AssertionError('incomplete accepted path')
                    if not result.commands or result.physical_authorized: raise AssertionError('bad command authorization')
                    if any(c['physical_authorized'] for c in result.commands): raise AssertionError('physical flag set')
                elif result.commands is not None: raise AssertionError('failure leaked partial path')
                for d in result.diagnostics:
                    if sum(a['iterations'] for a in d['attempts'])>cfg['iterations_per_target']: raise AssertionError('recovery budget exceeded')
                row=dict(name=label,split='development' if i<5 else 'holdout',status=result.status,elapsed_ms=elapsed,**result.metrics)
                results.append(row)
                print(f"PATH {label} {result.status} {result.metrics['completed_targets']}/{result.metrics['total_targets']}",flush=True)
    # Canonical simulation examples must pass. All other failures remain recorded.
    required=[r for r in results if r['name'].endswith('_cpp_recovery')]
    if any(r['status']!='OK' for r in required): raise AssertionError('nominal reference drawings did not all pass')
    write_new(run/'trajectory_summary.json',dict(status='PASS',paths=len(specs),evaluations=len(results),
        successful=sum(r['status']=='OK' for r in results),results=results,
        scope='Offline nominal trajectories, sampled geometry and analytical quintic joint bounds. No collision certificate or hardware authorization.'))
    print(f"R1B_TRAJECTORY_GATE_PASS evaluations={len(results)}")


if __name__=='__main__': main()
