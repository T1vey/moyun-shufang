"""Offline planner CLI. Input and output units are m/rad, no motor driver."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import numpy as np
from r1a.model import Model
from r1a.native import NativeStep,python_f32_inputs
from r1a.acceptance import validate
from .fixtures import drawings
from .planner import plan

ROOT=Path(__file__).resolve().parents[1]


def preview(model,spec,result,path):
    """Standalone paper-basis projection of requested/FK curves, no hardware claim."""
    desired_samples=[t for t in result.targets if t['phase']=='DRAW']
    desired=np.asarray([t['position'] for t in desired_samples], dtype=float).reshape(-1,3)
    if not len(desired): return
    drawn_commands=[c for c in (result.commands or []) if c['pen_down']]
    if drawn_commands:
        joints=np.asarray([c['q_rad'] for c in drawn_commands], dtype=float)
        actual=model.pose_many(joints)[:, :3, 3]
    else:
        actual=np.empty((0,3))
    # Retain every plotted sample, computing FK once without a Jacobian.
    desired_by_stroke={}
    actual_by_stroke={}
    for target,point in zip(desired_samples,desired):
        desired_by_stroke.setdefault(target['stroke'],[]).append(point)
    for command,point in zip(drawn_commands,actual):
        actual_by_stroke.setdefault(command['stroke'],[]).append(point)
    origin=np.asarray(spec['plane_origin_m'])
    basis=np.asarray([spec.get('plane_u',[1,0,0]),spec.get('plane_v',[0,1,0])]).T
    projected_desired=(desired-origin)@basis
    projected_actual=(actual-origin)@basis
    all_points=np.vstack([projected_desired,projected_actual]) if len(actual) else projected_desired
    span=max(float(np.max(np.ptp(all_points,axis=0))),.02)
    def points(data):
        data=(np.asarray(data)-origin)@basis
        return ' '.join(f'{300+p[0]*400/span:.3f},{280-p[1]*400/span:.3f}' for p in data)
    # Display the calibrated paper basis; validation remains fully 3D.
    paths=[]
    for stroke in sorted({t['stroke'] for t in result.targets}):
        d=desired_by_stroke.get(stroke,[])
        a=actual_by_stroke.get(stroke,[])
        if len(d): paths.append(f'<polyline points="{points(d)}" fill="none" stroke="#2563eb" stroke-width="3"/>')
        if len(a): paths.append(f'<polyline points="{points(a)}" fill="none" stroke="#ea580c" stroke-width="1.5"/>')
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="600" height="560" viewBox="0 0 600 560">
<rect width="600" height="560" fill="white"/><text x="30" y="32" font-family="Arial" font-size="18">SO-101 nominal simulation | {result.status}</text>
<text x="30" y="55" font-family="Arial" font-size="12">Paper projection; blue = requested samples; orange = nominal FK</text>
<path d="M 50 280 H 550 M 300 80 V 500" stroke="#ddd"/>
{''.join(paths)}
<text x="30" y="535" font-family="Arial" font-size="12">SIMULATION ONLY | physical_authorized=false | displayed span {span*1000:.1f} mm</text></svg>'''
    path.write_bytes(svg.encode('utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    choice=parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--input',type=Path); choice.add_argument('--demo',choices=['line','circle','two-strokes'])
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--validated-run',type=Path,help='Use execution-verified host C++ DLL; omit for Python')
    parser.add_argument('--no-recovery',action='store_true')
    args=parser.parse_args()
    if args.out.exists(): raise SystemExit('Refusing to overwrite output; choose a new directory')
    model=Model.load(ROOT/'config/nominal_so101.json')
    ik=json.loads((ROOT/'config/contract.json').read_text()); cfg=json.loads((ROOT/'config/trajectory.json').read_text())
    spec=json.loads(args.input.read_text(encoding='utf-8-sig')) if args.input else drawings(model)[{'line':0,'circle':1,'two-strokes':4}[args.demo]]
    backend=python_f32_inputs
    if args.validated_run:
        validate(args.validated_run)
        # The importing Python model and planning code must match the accepted run.
        from r1a.evidence import sha,read
        inputs=read(args.validated_run/'inputs.json')['files']
        for rel,digest in inputs.items():
            if rel.startswith('source/') and sha(ROOT/rel[7:])!=digest:
                raise ValueError(f'current code differs from validated source: {rel}')
        backend=NativeStep(args.validated_run/'wls_step.dll')
    result=plan(model,spec,spec['q0'],ik,cfg,backend,not args.no_recovery)
    args.out.mkdir(parents=True)
    (args.out/'drawing.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    (args.out/'plan.json').write_text(json.dumps(asdict(result),indent=2,allow_nan=False),encoding='utf-8')
    preview(model,spec,result,args.out/'preview.svg')
    print(json.dumps(dict(status=result.status,physical_authorized=False,output=str(args.out),metrics=result.metrics)))
    if result.status!='OK': raise SystemExit(2)


if __name__=='__main__': main()
