"""Plan frozen paths and save history without any servo/device I/O.

PL mode requires exclusive ownership of the IK IP. Planner v2 attaches to the
matching boot-loaded display/touch platform by default; legacy target mode
retains its download default. Select the load policy explicitly when needed.
Do not run it concurrently with the board service. This never executes motion.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace


def peak_process_rss_kib():
    """Linux board high-water RSS; unavailable platforms return None."""
    try:
        import resource
        value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return float(value/1024 if sys.platform=='darwin' else value)
    except ImportError:return None


def compare_commands(actual,baseline,machine):
    """Compare physical commands, geometry coverage, and model predictions."""
    import numpy as np
    from motion import counts_from_angles
    if actual.status!=baseline['status']:raise AssertionError('planning status changed')
    old=baseline.get('commands') or [];new=actual.commands or []
    if len(old)!=len(new):raise AssertionError('command count changed')
    maximum=0.
    for a,b in zip(new,old):
        for field in ('phase','stroke','pen_down','physical_authorized'):
            if a[field]!=b[field]:raise AssertionError(field+' changed')
        for field in ('q_rad','velocity_rad_s','acceleration_rad_s2','tip_target_m','axis_target','t_s'):
            difference=float(np.max(np.abs(np.asarray(a[field])-b[field])))
            maximum=max(maximum,difference)
            if difference>1e-12:raise AssertionError(field+' changed: '+str(difference))
        if machine and counts_from_angles(machine,a['q_rad'])!=counts_from_angles(machine,b['q_rad']):
            raise AssertionError('integer servo counts changed')
    if actual.targets!=baseline['targets']:raise AssertionError('IK targets changed')
    for field in ('geometry_samples','moving_draw_knots'):
        if actual.metrics[field]!=baseline['metrics'][field]:raise AssertionError(field+' changed')
    for field in ('max_draw_path_error_m','max_draw_tilt_rad','max_requested_sample_error_m',
                  'max_interpolation_error_m','peak_velocity_rad_s','peak_acceleration_rad_s2'):
        if abs(actual.metrics[field]-baseline['metrics'][field])>1e-12:
            raise AssertionError(field+' changed')
    for field in ('max_target_error_m','max_rounding_displacement_m','max_tilt_rad'):
        if abs(actual.metrics['quantization'][field]-baseline['metrics']['quantization'][field])>1e-12:
            raise AssertionError('quantization changed: '+field)
    return dict(max_command_difference=maximum,integer_counts_identical=True,
                all_targets_identical=True,geometry_coverage_identical=True)


def persist_history(output,result,spec,paths,machine):
    """Exercise the production history writer in an isolated benchmark folder."""
    from workbench import Workbench
    state=SimpleNamespace(directory=output/'session',record=lambda *args:None)
    state.directory.mkdir(parents=True,exist_ok=True)
    bench=Workbench(state,allow_motion=False)
    stored=dict(result=result,q0=spec['q0'],mode='real',digest='BENCHMARK_NO_EXECUTION',
                machine=machine,paths=paths,drawing=spec,port=None,baudrate=None)
    if not bench._save_plan('benchmark',stored):raise AssertionError('history save failed')
    if not bench._plan_path('benchmark').is_file():raise AssertionError('history save failed')


def benchmark_backend(native_library,overlay,pl_mode='target',load_policy=None,platform_manifest=None):
    if pl_mode not in ('target','planner'):raise ValueError('Unsupported benchmark PL mode')
    if (native_library is None)==(overlay is None):raise ValueError('Choose exactly one benchmark backend')
    if native_library is not None:
        if pl_mode=='planner':
            from planner_accel_backend import NativePlannerAccel
            return NativePlannerAccel(native_library)
        from ik_target_backend import NativeIKTarget
        return NativeIKTarget(native_library)
    from engine import make_backend
    return make_backend('wls',overlay,pl_mode=pl_mode,
        pl_load_policy=load_policy or ('attach' if pl_mode=='planner' else 'download'),
        platform_manifest=platform_manifest)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime-dir',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--paths',type=Path,required=True)
    p.add_argument('--machine',type=Path,required=True)
    p.add_argument('--q0',type=Path,required=True,help='JSON list of five fixed joint angles')
    kernel=p.add_mutually_exclusive_group(required=True)
    kernel.add_argument('--native-library',type=Path,help='HOST numerical gate; not board timing')
    kernel.add_argument('--overlay',type=Path,help='Actual board PL; exclusive ownership required')
    p.add_argument('--pl-mode',choices=('target','planner'),default='target',help='Explicit hardware/native ABI')
    p.add_argument('--pl-load-policy',choices=('attach','download'),help='Default: planner attach, target download')
    p.add_argument('--platform-manifest',type=Path,help='Matching boot platform manifest for attach')
    p.add_argument('--baseline-plan',type=Path)
    p.add_argument('--motion-mode',choices=('standard','gentle','smooth_fast','speed_priority','classic_fast'),default='standard')
    p.add_argument('--runs',type=int,default=3)
    p.add_argument('--target-seconds',type=float,default=30.)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if not 1<=a.runs<=10:p.error('runs must be 1..10')
    if not 0<a.target_seconds<3600:p.error('target seconds must be positive and less than 3600')
    sys.path.insert(0,str(a.runtime_dir.resolve()))
    from planning import build
    from motion import counts_from_angles
    paths=json.loads(a.paths.read_text(encoding='utf-8'))
    machine=json.loads(a.machine.read_text(encoding='utf-8'))
    q0=json.loads(a.q0.read_text(encoding='utf-8'))
    counts=counts_from_angles(machine,q0)
    baseline=json.loads(a.baseline_plan.read_text(encoding='utf-8')) if a.baseline_plan else None
    backend=benchmark_backend(a.native_library,a.overlay,a.pl_mode,a.pl_load_policy,a.platform_manifest)
    a.output.mkdir(parents=True,exist_ok=True)
    runs=[]
    for i in range(a.runs):
        folder=a.output/('run%d'%(i+1));started=time.perf_counter();cpu_started=time.process_time()
        result,spec,_=build(paths,folder,machine,counts,backend=backend,motion_mode=a.motion_mode)
        if result.status!='OK':raise AssertionError(result.status+': '+str(result.metrics.get('detail')))
        t=time.perf_counter();persist_history(folder,result,spec,paths,machine)
        timing=dict(result.metrics['timing'],saved_plan_s=time.perf_counter()-t,
                    plan_and_history_s=time.perf_counter()-started,cpu_time_s=time.process_time()-cpu_started)
        # Validation is outside timing and never replaces generation.
        parity=compare_commands(result,baseline,machine) if baseline else None
        runs.append(dict(status='PASS',timing=timing,targets=len(result.targets),commands=len(result.commands),
                         geometry_samples=result.metrics['geometry_samples'],
                         geometry_fk_batches=result.metrics.get('geometry_fk_batches'),
                         peak_process_rss_kib=peak_process_rss_kib(),
                         pl_job=result.metrics.get('pl_job'),
                         native_geometry=result.metrics.get('native_geometry'),parity=parity))
        median=statistics.median(r['timing']['plan_and_history_s'] for r in runs)
        report=dict(scope='HOST_NATIVE_NO_MOTOR_IO' if a.native_library else 'BOARD_PL_NO_MOTOR_IO',
                    pl_mode=a.pl_mode,backend=backend.metrics(),
                    board_30s_acceptance='NOT_RUN' if a.native_library else ('PASS' if max(
                        r['timing']['plan_and_history_s'] for r in runs)<=a.target_seconds else 'FAIL'),
                    measured_scope='full build and production history save; excludes HTTP and servo preflight',
                    source_sha256=paths.get('source_sha256'),path_sha256=paths.get('path_sha256'),
                    width_mm=paths['width_mm'],height_mm=paths['height_mm'],
                    motion_mode=a.motion_mode,motion_algorithm_version=result.metrics.get('motion_algorithm_version'),
                    motion_metrics={k:result.metrics.get(k) for k in ('duration_s','peak_velocity_rad_s',
                        'peak_acceleration_rad_s2','peak_jerk_rad_s3','hard_stop_knots','avoidable_stop_knots',
                        'max_draw_path_error_m','max_knot_velocity_jump_rad_s','max_knot_acceleration_jump_rad_s2',
                        'max_knot_jerk_jump_rad_s3','retime_passes','fallback_blocks','blended_blocks')},
                    strokes=paths['strokes'],segments=paths['segments'],q0=spec['q0'],
                    target_s=a.target_seconds,median_s=median,
                    minimum_s=min(r['timing']['plan_and_history_s'] for r in runs),
                    maximum_s=max(r['timing']['plan_and_history_s'] for r in runs),runs=runs)
        (a.output/'benchmark.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('RUN_PASS %d plan_and_history_s=%.3f'%(i+1,timing['plan_and_history_s']),flush=True)
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
