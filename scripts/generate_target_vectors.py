"""Independent PS reference fixtures for target HLS C/RTL simulation."""
import argparse
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from planning import nominal,load
from r1a.solve import solve

def cases():
    model,_,q0=nominal(); cfg=load('contract.json'); rng=np.random.default_rng(101)
    for i in range(80):
        target=np.clip(np.asarray(q0)+rng.uniform(-.18,.18,5),model.limits[:,0]+.01,model.limits[:,1]-.01)
        seed=np.clip(target+rng.uniform(-.04,.04,5),model.limits[:,0],model.limits[:,1])
        pose=model.pose(target); local=dict(cfg,max_iterations=40)
        if i%3==0: seed=target.copy()
        mode='rhs_only' if i%4==0 else 'wls'
        p=pose[:3,3]; axis=pose[:3,:3]@model.tool_axis
        expected=solve(model,p,axis,seed,local,mode=mode)
        if expected.status!='OK': raise AssertionError('reference fixture '+expected.status)
        yield model,p,axis,seed,local,mode,0,np.asarray(expected.q_solution)
    pose=model.pose(q0);p=pose[:3,3];axis=pose[:3,:3]@model.tool_axis
    for label,local,pos,seed,want in [
        ('unreachable',dict(cfg,max_iterations=12),p+np.array([2.,0,0]),q0,-1),
        ('zero_weights',dict(cfg,weights=[0]*6),p+np.array([.02,0,0]),q0,4),
        ('max_iter',dict(cfg,max_iterations=1,max_joint_step_rad=.00001),p+np.array([.02,0,0]),q0,3),
        ('invalid',dict(cfg,mu=0),p,q0,1),
        ('numeric',dict(cfg,weights=[1e38]*6,scales=[1e38]*6),p+np.array([.02,0,0]),q0,2),
    ]:
        yield model,pos,axis,seed,local,'wls',want,np.asarray(q0)

def write(path):
    rows=[]
    for m,p,a,q,cfg,mode,want,golden in cases():
        values=np.r_[q,p,a,cfg['weights'],cfg['scales'],m.tool,m.tool_axis,m.limits.reshape(-1),
            cfg['mu'],cfg['max_joint_step_rad'],cfg['position_tolerance_m']*.999,
            cfg['tilt_tolerance_rad']*.999,cfg['stagnation_cost_change']]
        ints=[cfg['max_iterations'],cfg['line_search_trials'],cfg['stagnation_window'],int(mode=='rhs_only'),want]
        rows.append(' '.join(format(float(v),'.10g') for v in values)+' '+' '.join(map(str,ints))+
            ' '+' '.join(format(float(v),'.10g') for v in golden))
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(str(len(rows))+'\n'+'\n'.join(rows)+'\n',encoding='ascii')
    print('TARGET_VECTORS',len(rows),path)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args();write(a.output)
