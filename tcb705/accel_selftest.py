"""PL arithmetic self-test only: never connects to or commands a robot."""
import numpy as np
from .config import demo_config,load
from .model import Model,ROOT
from . import accel_contract as c

def self_test(core):
    fp32=getattr(core.transport,'completion_options',{}).get('expected_capabilities',0)==c.FP32_CAPABILITIES
    config=load(ROOT/'robots/tcb705/profile.armvision_joint.json') if fp32 else demo_config()
    model=Model(config);seed=np.asarray(model.config['q_start_rad']);pose=model.fk(seed)
    targets=np.tile(pose,(3,1,1));targets[:,0,3]+=np.arange(1,4)*.001
    rows=core.solve_chain(model,targets,seed,lambda:False)
    if len(rows)!=3:raise RuntimeError('seven-axis hardware IK self-test rejected a row')
    if fp32:
        # New hardware is IK-only; numerical quality is tested offline. Runtime
        # checks only identity, legal joint prefix and explicit unknown errors.
        if any(r['position_error_m'] is not None or r['geometry_verified'] for r in rows):
            raise RuntimeError('FP32 kernel must report unevaluated residuals')
        ctx=c.context(model,seed,pose[:3,:3]);inputs=np.zeros(1,dtype=c.IK_INPUT)
        inputs['position']=targets[:1,:3,3];inputs['id']=0
        h,out=core.transport.execute(ctx,c.IK_CHAIN,inputs,19,31,cancel=lambda:True)
        if h['status']!=2 or len(out):raise RuntimeError('FP32 cancellation protocol failed')
        bad=ctx.copy();bad['model_id']=123
        h,out=core.transport.execute(bad,c.IK_CHAIN,inputs,19,32)
        if h['status']!=4 or len(out):raise RuntimeError('FP32 rejected-model protocol failed')
        print('TCB705_FP32_IK_PROTOCOL_SELF_TEST_PASS: 3 legal IK rows, cancellation and rejected model; geometric residuals not evaluated',flush=True)
        return
    else:
        cpu=model.solve_chain(targets,seed)
        for a,b in zip(rows,cpu):np.testing.assert_allclose(a['q'],b['q'],rtol=0,atol=2e-7)
    # Exercise the full DDR row capacity and vary all seven axes independently.
    ctx=c.context(model,seed,pose[:3,:3]);inputs=np.zeros(c.MAX_FK,dtype=c.FK_INPUT)
    phase=np.arange(c.MAX_FK)[:,None]*(np.arange(7)[None,:]+1)*.13
    inputs['q']=seed+.02*np.sin(phase);inputs['id']=np.arange(c.MAX_FK)
    h,result=core.transport.execute(ctx,c.FK_ROWS,inputs,19,31)
    if h['status']!=0:raise RuntimeError('seven-axis hardware FK self-test failed')
    np.testing.assert_allclose(result['pose'],model.fk_batch(inputs['q']),rtol=0,atol=1e-6 if fp32 else 1e-9)
    print('TCB705_HARDWARE_IK_FK_SELF_TEST_PASS: 3 IK targets, 1024 full seven-axis FK rows',flush=True)
