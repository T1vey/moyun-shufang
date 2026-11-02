"""Replay a saved drawing with fixed q0; no serial port or motor commands.

Full PL mode requires exclusive ownership: stop the workbench service first.
Postprocess mode uses only saved commands and never loads an overlay.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
import numpy as np


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime-dir',type=Path,required=True)
    p.add_argument('--job-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--overlay',type=Path)
    p.add_argument('--runs',type=int,default=3)
    p.add_argument('--legacy-save',action='store_true',help='Reproduce original asdict + indented JSON')
    a=p.parse_args()
    if not 1<=a.runs<=10:p.error('runs must be 1..10')
    sys.path.insert(0,str(a.runtime_dir.resolve()))
    from planning import Model, load, quantization_report, preview
    from r1b.planner import Plan, plan
    from motion import counts_from_angles
    baseline=json.loads((a.job_dir/'plan.json').read_text(encoding='utf-8'))
    baseline_quant=dict(baseline['metrics']['quantization'])
    spec=json.loads((a.job_dir/'drawing.json').read_text(encoding='utf-8'))
    machine=json.loads((a.job_dir/'machine.json').read_text(encoding='utf-8'))
    cfg=baseline['metrics']['effective_trajectory']
    model=Model(machine['model'])
    backend=None
    if a.overlay:
        from ik_target_backend import PynqIKTarget
        backend=PynqIKTarget(a.overlay)
    out=a.output.parent
    out.mkdir(parents=True,exist_ok=True)
    runs=[]
    for i in range(a.runs):
        started=time.perf_counter()
        result=plan(model,spec,spec['q0'],load('contract.json'),cfg,backend=backend) if backend else Plan(**baseline)
        result.metrics=dict(result.metrics)
        if result.status!='OK':raise AssertionError(result.status)
        t=time.perf_counter()
        quant=quantization_report(model,machine,result.commands)
        result.metrics['quantization']=quant
        quant_s=time.perf_counter()-t
        print('RUN',i+1,'QUANTIZATION',round(quant_s,3),flush=True)
        t=time.perf_counter()
        (out/'drawing.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
        preview(model,spec,result,out/'preview.svg')
        preview_s=time.perf_counter()-t
        print('RUN',i+1,'PREVIEW',round(preview_s,3),flush=True)
        t=time.perf_counter()
        if a.legacy_save:
            from dataclasses import asdict
            encoded=json.dumps(asdict(result),indent=2,allow_nan=False)
        else:encoded=json.dumps(vars(result),separators=(',',':'),allow_nan=False)
        (out/'plan.json').write_text(encoded,encoding='utf-8')
        save_s=time.perf_counter()-t
        pipeline_s=time.perf_counter()-started
        del encoded
        # Validation is outside the measured generation/save time.
        if len(result.commands)!=len(baseline['commands']):raise AssertionError('command count changed')
        original=baseline['commands']
        max_difference=0.
        for c,b in zip(result.commands,original):
            for field in ('phase','stroke','pen_down','physical_authorized'):
                if c[field]!=b[field]:raise AssertionError(field+' changed')
            for field in ('q_rad','velocity_rad_s','acceleration_rad_s2','tip_target_m','axis_target','t_s'):
                difference=float(np.max(np.abs(np.asarray(c[field])-b[field])))
                max_difference=max(max_difference,difference)
                if difference>1e-12:raise AssertionError(field+' changed: '+str(difference))
            if counts_from_angles(machine,c['q_rad'])!=counts_from_angles(machine,b['q_rad']):
                raise AssertionError('integer servo counts changed')
        for field in ('max_target_error_m','max_rounding_displacement_m','max_tilt_rad'):
            if abs(quant[field]-baseline_quant[field])>1e-12:
                raise AssertionError('quantization metric changed: '+field)
        svg_same=(out/'preview.svg').read_bytes()==(a.job_dir/'preview.svg').read_bytes()
        if not svg_same:raise AssertionError('preview SVG changed')
        decoded=json.loads((out/'plan.json').read_text(encoding='utf-8'))
        if decoded['commands']!=result.commands:raise AssertionError('JSON roundtrip changed commands')
        del decoded
        timing=dict(result.metrics.get('timing',{})) if backend else {}
        timing.update(quantization_s=quant_s,drawing_preview_s=preview_s,plan_save_s=save_s,build_total_s=pipeline_s)
        record=dict(run=i+1,status='PASS',targets=len(result.targets),commands=len(result.commands),
                    timing=timing,max_command_difference=max_difference,integer_counts_identical=True,
                    preview_bytes_identical=svg_same,quantization=quant)
        runs.append(record)
        doc=dict(scope='FIXED_SAVED_INPUT_PL_NO_MOTOR_IO' if backend else 'SAVED_COMMAND_POSTPROCESS_NO_HARDWARE_IO',
                 status='PASS',runtime_dir=str(a.runtime_dir),input_job=str(a.job_dir),
                 effective_trajectory=cfg,q0=spec['q0'],runs=runs,
                 median_s=statistics.median(r['timing']['build_total_s'] for r in runs),
                 minimum_s=min(r['timing']['build_total_s'] for r in runs),
                 maximum_s=max(r['timing']['build_total_s'] for r in runs),
                 backend=backend.metrics() if backend else None)
        a.output.write_text(json.dumps(doc,indent=2)+'\n',encoding='utf-8')
        print('RUN_PASS',i+1,'TOTAL',round(pipeline_s,3),flush=True)
        del result
    print('PIPELINE_BENCHMARK_PASS',round(doc['median_s'],3),flush=True)


if __name__=='__main__':main()
