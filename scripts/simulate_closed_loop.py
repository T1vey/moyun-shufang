"""Plan through PS/reference/compiled C++ and replay a servo feedback plant."""
import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from planning import build,load,nominal
from r1a.native import python_f32_inputs
from r1a.task_step import ReferenceTaskStep,NativeTaskStep
from closed_loop import replay_commands
from motion import counts_from_angles
from vision import preset


def machine_fixture(model,paper):
    machine=json.loads((ROOT/'config/machine.example.json').read_text(encoding='utf-8'))
    machine['model']=copy.deepcopy(model.config)
    machine['paper']=paper
    for j in machine['joints']:
        j.update(zero_count=2048,min_count=100,max_count=3900)
    machine['checks']=dict(limits=True,kinematics=True,single_joint=True)
    return machine


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--shape',choices=('line','circle','square'),default='circle')
    p.add_argument('--backend',choices=('ps','full_reference','native'),default='full_reference')
    p.add_argument('--library',type=Path)
    p.add_argument('--controller',choices=('open_loop','feedback_retime'),default='open_loop')
    for name,default in (('rate',190.),('speed',100.),('bias-id2',0.),('bias-id3',0.),('deadband',0.),('width-mm',20.),('height-mm',20.)):
        p.add_argument('--'+name,type=float,default=default)
    a=p.parse_args()
    m,paper,q0=nominal(); machine=machine_fixture(m,paper)
    initial=counts_from_angles(machine,q0)
    if a.backend=='native' and not a.library: p.error('native requires --library')
    backend=NativeTaskStep(m,a.library) if a.backend=='native' else (ReferenceTaskStep(m) if a.backend=='full_reference' else python_f32_inputs)
    with tempfile.TemporaryDirectory() as d:
        paths=preset(a.shape,Path(d)/a.shape,a.width_mm,a.height_mm)
        result,_,cfg=build(paths,Path(d)/'plan',machine,initial,backend=backend)
        report=dict(scope='OFFLINE_NO_MOTOR_IO',backend=a.backend,plan_status=result.status,planner_metrics=result.metrics)
        if result.status=='OK':
            report['replay']=replay_commands(m,machine,result.commands,initial,a.speed,a.rate,
                {2:a.bias_id2,3:a.bias_id3},a.deadband,controller=a.controller)
            report['status']=report['replay']['tracking_status']
        else: report['status']='PLAN_FAILED'
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=report['status'],output=str(a.output))))
    return int(report['status']!='PASS')
if __name__=='__main__': raise SystemExit(main())
