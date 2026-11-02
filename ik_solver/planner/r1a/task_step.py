"""Task-step reference and actual C++ host adapter; neither accesses hardware."""
import ctypes
import json
from pathlib import Path
import numpy as np
from .linear import step
from .model import finite_array


def reference_task_step(model, position, axis, q, weights, scales, mu, max_step, mode='wls'):
    q = finite_array(q,(5,),'q')
    if not model.legal(q) or not np.isfinite(max_step) or max_step<=0:
        raise ValueError('invalid joint state or step bound')
    error,jacobian,pe,te = model.task(q,position,axis)
    dq = step(jacobian,error,weights,scales,mu,mode)
    dq *= min(1.,max_step/max(float(np.max(np.abs(dq))),1e-30))
    next_q = np.clip(q+dq,model.limits[:,0],model.limits[:,1])
    return dict(dq=next_q-q,q_next=next_q,error=error,jacobian=jacobian,
                position_error_m=pe,tilt_error_rad=te,status=0)


class ReferenceTaskStep:
    name = 'HOST_REFERENCE_z20_ik_step'
    def __init__(self, model, max_step=.12):
        self.model,self.max_step,self.calls = model,max_step,0
    def validate_model(self, model):
        self.model = model
        return True
    def solve_task(self,position,axis,q,weights,scales,mu,max_step=None,mode='wls'):
        self.calls += 1
        return reference_task_step(self.model,position,axis,q,weights,scales,mu,
            self.max_step if max_step is None else max_step,mode)
    def metrics(self):
        return dict(calls=self.calls,backend=self.name,transport='host_reference')


class NativeTaskStep(ReferenceTaskStep):
    name = 'HOST_CPP_z20_ik_step'
    def __init__(self, model, library):
        super().__init__(model)
        self.library = ctypes.CDLL(str(Path(library).resolve()))
        self.fn = self.library.z20_ik_step
        self.ptr = ctypes.POINTER(ctypes.c_float)
        self.fn.argtypes = [self.ptr]*8+[ctypes.c_float,ctypes.c_float,ctypes.c_int]+[self.ptr]*5+[ctypes.POINTER(ctypes.c_uint)]
        self.fn.restype = ctypes.c_int
        self.nominal = json.loads((Path(__file__).resolve().parents[1]/'config/nominal_so101.json').read_text(encoding='utf-8'))
        if not self.validate_model(model):
            raise ValueError('native kernel link geometry mismatch')
    def validate_model(self, model):
        if (not np.allclose(model.offsets,self.nominal['offsets_m'],atol=1e-9,rtol=0) or
                not np.allclose(model.axes,self.nominal['axes'],atol=1e-9,rtol=0)):
            return False
        self.model = model
        return True
    def solve_task(self,position,axis,q,weights,scales,mu,max_step=.12,mode='wls'):
        if mode not in ('wls','rhs_only'):
            raise ValueError('invalid weighting mode')
        arrays = [np.ascontiguousarray(v,dtype=np.float32) for v in
            (q,position,axis,weights,scales,self.model.tool,self.model.tool_axis,self.model.limits.reshape(-1))]
        if [a.size for a in arrays] != [5,3,3,6,6,3,3,10]:
            raise ValueError('invalid native buffer size')
        dq,nxt,err,pe,te = [np.full(n,np.nan,np.float32) for n in (5,5,6,1,1)]
        magic = ctypes.c_uint()
        status = self.fn(*[v.ctypes.data_as(self.ptr) for v in arrays],mu,max_step,int(mode=='rhs_only'),
            *[v.ctypes.data_as(self.ptr) for v in (dq,nxt,err,pe,te)],ctypes.byref(magic))
        self.calls += 1
        if status or magic.value!=0x534F0202:
            raise FloatingPointError('native IK status=%d ABI=%X' % (status,magic.value))
        if any(not np.isfinite(v).all() for v in (dq,nxt,err,pe,te)):
            raise FloatingPointError('nonfinite native IK output')
        return dict(dq=dq.astype(float),q_next=nxt.astype(float),error=err.astype(float),
                    position_error_m=float(pe[0]),tilt_error_rad=float(te[0]),status=status)
    def metrics(self):
        return dict(calls=self.calls,backend=self.name,transport='ctypes_host_cpp')
