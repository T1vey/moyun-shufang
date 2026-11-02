"""URDF-based seven-axis model and native CPU numerical core (m, rad, s)."""
import ctypes as ct
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

def vector(value, size, name):
    a = np.asarray(value, dtype=np.float64)
    if a.shape != (size,) or not np.isfinite(a).all():
        raise ValueError('%s must contain %d finite values' % (name, size))
    return a

def transform(value, name='transform'):
    a = np.asarray(value, dtype=np.float64)
    if (a.shape != (4, 4) or not np.isfinite(a).all() or
            not np.allclose(a[3], [0, 0, 0, 1], atol=1e-10) or
            not np.allclose(a[:3,:3].T @ a[:3,:3], np.eye(3), atol=1e-7) or
            abs(np.linalg.det(a[:3,:3])-1) > 1e-7):
        raise ValueError(name+' is not a rigid transform')
    return a.copy()

def rpy_matrix(rpy):
    r,p,y=rpy
    cr,sr,cp,sp,cy,sy=math.cos(r),math.sin(r),math.cos(p),math.sin(p),math.cos(y),math.sin(y)
    return np.array([[cy*cp,cy*sp*sr-sy*cr,cy*sp*cr+sy*sr],
                     [sy*cp,sy*sp*sr+cy*cr,sy*sp*cr-cy*sr],[-sp,cp*sr,cp*cr]])

MAX_CORRECTION_M=.02;MAX_CORRECTION_RAD=.05

def correction(config,joint):
    """Measured geometry correction applied after URDF joint origin `joint`.

    config['model_corrections'] = {'origin_xyz_m': 7x3, 'origin_rpy_rad': 7x3},
    written by tcb705.kinematic_fit (calibrated link geometry). Bounded so a bad
    fit cannot silently turn the URDF into a different robot. The corrected rows
    are what the CPU core and the FPGA IK core both receive (model.data)."""
    c=config.get('model_corrections')
    t=np.eye(4)
    if not c:return t
    xyz=np.asarray(c['origin_xyz_m'],dtype=float);rpy=np.asarray(c['origin_rpy_rad'],dtype=float)
    if xyz.shape!=(7,3) or rpy.shape!=(7,3) or not np.isfinite(xyz).all() or not np.isfinite(rpy).all():raise ValueError('invalid model_corrections')
    if np.abs(xyz).max()>MAX_CORRECTION_M or np.abs(rpy).max()>MAX_CORRECTION_RAD:raise ValueError('model_corrections exceed 20 mm / 0.05 rad: re-check the calibration')
    t[:3,:3]=rpy_matrix(rpy[joint]);t[:3,3]=xyz[joint];return t

def pose_error(a,b):
    d=a[:3,:3] @ b[:3,:3].T
    return float(np.linalg.norm(a[:3,3]-b[:3,3])), math.acos(float(np.clip((np.trace(d)-1)/2,-1,1)))

def dh_rows(kin):
    """Standard DH (a, d, alpha, theta; mm/deg) read from the controller (r_dh_1_) ->
    the same row format as the URDF chain: frame_k = frame_{k-1} @ origin_k @ Rz(q_k).
    origin_1 = Rz(theta_1); origin_k = Tz(d_{k-1}) Tx(a_{k-1}) Rx(alpha_{k-1}) Rz(theta_k).
    The last DH link (to the controller flange/TCP) is returned separately."""
    dh=np.asarray(kin['dh'],dtype=float);lim=np.radians(np.asarray(kin['joint_limits_deg'],dtype=float))
    if dh.shape!=(7,4) or lim.shape!=(7,2) or not np.isfinite(dh).all() or np.any(lim[:,0]>=lim[:,1]):raise ValueError('invalid controller DH kinematics')
    def link(a,d,alpha):
        t=np.eye(4);ca,sa=math.cos(math.radians(alpha)),math.sin(math.radians(alpha))
        t[:3,:3]=[[1,0,0],[0,ca,-sa],[0,sa,ca]];t[0,3]=a;t[2,3]=d;return t
    def rz(theta):
        t=np.eye(4);c,s=math.cos(math.radians(theta)),math.sin(math.radians(theta));t[:2,:2]=[[c,-s],[s,c]];return t
    rows=[]
    for i in range(7):
        o=rz(dh[i,3]) if i==0 else link(dh[i-1,0]/1000,dh[i-1,1]/1000,dh[i-1,2])@rz(dh[i,3])
        rows.append(list(o.ravel())+[0.,0.,1.]+list(lim[i]))
    return rows,link(dh[6,0]/1000,dh[6,1]/1000,dh[6,2])

class Model:
    def __init__(self, config, library=None):
        self.config=config
        kin=config.get('kinematics')
        if kin and kin.get('source')=='controller_dh':
            # Controller's own kinematics: reproduces its reported poses to 0.02 mm (2026-10-18).
            rows,self.dh_flange=dh_rows(kin)
            self.model_sha256=hashlib.sha256(json.dumps(kin,sort_keys=True).encode()).hexdigest()
            rows=[list((np.asarray(r[:16]).reshape(4,4)@correction(config,i)).ravel())+r[16:] for i,r in enumerate(rows)]
        else:
            rows=self._urdf_rows(config)
        self._finish(config,rows,library)

    def _urdf_rows(self,config):
        self.dh_flange=np.eye(4)
        urdf=ROOT/'robots/tcb705/model_source/tcb705.urdf'
        self.model_sha256=hashlib.sha256(urdf.read_bytes()).hexdigest()
        tree=ET.fromstring(urdf.read_bytes())
        joints={e.get('name'):e for e in tree.findall('joint')}
        rows=[]
        for i in range(7):
            e=joints['joint%d'%(i+1)]
            if e.get('type')!='revolute' or e.find('parent').get('link')!='link%d'%i or e.find('child').get('link')!='link%d'%(i+1):
                raise ValueError('unexpected TCB705 chain')
            orig=e.find('origin'); t=np.eye(4)
            t[:3,:3]=rpy_matrix(vector([float(x) for x in orig.get('rpy').split()],3,'rpy'))
            t[:3,3]=vector([float(x) for x in orig.get('xyz').split()],3,'xyz')
            t=t@correction(config,i)
            axis=vector([float(x) for x in e.find('axis').get('xyz').split()],3,'axis')
            if abs(np.linalg.norm(axis)-1)>1e-7:raise ValueError('URDF axis must be normalized')
            lim=e.find('limit');lo,hi=float(lim.get('lower')),float(lim.get('upper'))
            if not math.isfinite(lo+hi) or lo>=hi:raise ValueError('invalid URDF limits')
            rows.append(list(t.ravel())+list(axis)+[lo,hi])
        return rows

    def _finish(self,config,rows,library):
        self.data=np.array(rows,dtype=np.float64)
        self.lower=self.data[:,19].copy();self.upper=self.data[:,20].copy()
        if 'joint_limits_rad' in config:
            limits=np.asarray(config['joint_limits_rad'],dtype=float)
            if limits.shape!=(7,2) or not np.isfinite(limits).all():raise ValueError('invalid seven-axis limits')
            self.lower=np.maximum(self.lower,limits[:,0]);self.upper=np.minimum(self.upper,limits[:,1])
            if np.any(self.lower>=self.upper):raise ValueError('empty joint limit intersection')
            self.data[:,19]=self.lower;self.data[:,20]=self.upper
        # DH models end at the J7 joint frame: the controller flange is one DH link further.
        self.tool=transform(self.dh_flange@transform(config['T_flange_tcp'],'T_flange_tcp'),'tool')
        # Paper coordinates and FK outputs live in the controller base frame.
        # The native URDF chain remains in its model base frame.
        self.base=transform(config.get('T_controller_base_from_model',np.eye(4)),
                            'T_controller_base_from_model')
        self.base_inverse=np.linalg.inv(self.base)
        self.base_identity=bool(np.array_equal(self.base,np.eye(4)))
        mapping=config['sdk_mapping'];self.order=mapping['sdk_to_model_index']
        if sorted(self.order)!=list(range(7)):raise ValueError('invalid SDK joint permutation')
        self.sign=vector(mapping['sign'],7,'sign');self.offset=vector(mapping['offset_rad'],7,'offset')
        if not np.all(np.isin(self.sign,[-1,1])):raise ValueError('SDK sign must be -1 or +1')
        lib=Path(library) if library else ROOT/'build/tcb705'/('tcb_core.dll' if sys.platform=='win32' else 'libtcb_core.so')
        if not lib.is_file():raise ValueError('先运行 python scripts/build_tcb705.py 编译七轴 CPU 核')
        self.lib=ct.CDLL(str(lib));ptr=ct.POINTER(ct.c_double)
        self.lib.tcb_abi_version.restype=ct.c_int
        if self.lib.tcb_abi_version()!=2:raise ValueError('native ABI mismatch; rebuild seven-axis batch core')
        self.lib.tcb_fk.argtypes=[ptr]*6;self.lib.tcb_fk.restype=ct.c_int
        self.lib.tcb_ik.argtypes=[ptr]*8;self.lib.tcb_ik.restype=ct.c_int
        self.lib.tcb_fk_batch.argtypes=[ptr]*4+[ct.c_int];self.lib.tcb_fk_batch.restype=ct.c_int
        self.lib.tcb_ik_chain.argtypes=[ptr]*7+[ct.POINTER(ct.c_int),ct.c_int]
        self.lib.tcb_ik_chain.restype=ct.c_int
        self.native_joint_preparation = (hasattr(self.lib, 'tcb_joint_merge') and
                                         hasattr(self.lib, 'tcb_joint_block_error'))
        if self.native_joint_preparation:
            ip = ct.POINTER(ct.c_int)
            self.lib.tcb_joint_merge.argtypes = [ptr]*6 + [ip]*3 + [ct.c_int] + [ct.c_double]*3 + [ip]
            self.lib.tcb_joint_merge.restype = ct.c_int
            self.lib.tcb_joint_block_error.argtypes = [ptr]*5 + [ip, ct.c_int, ip, ct.c_int, ct.c_int, ptr]
            self.lib.tcb_joint_block_error.restype = ct.c_int
        self.lib.tcb_extrema_batch.argtypes=[ptr,ptr,ct.c_int];self.lib.tcb_extrema_batch.restype=ct.c_int
        # Optional (2026-10-18): native capsule self-collision; older builds fall back to numpy.
        self.native_collision=hasattr(self.lib,'tcb_self_collision_batch')
        if self.native_collision:
            ip=ct.POINTER(ct.c_int)
            self.lib.tcb_self_collision_batch.argtypes=[ptr]*3+[ip,ip,ct.c_int,ct.c_double,ct.c_int,ip]
            self.lib.tcb_self_collision_batch.restype=ct.c_int
        # Optional (2026-10-18): final-frame Horner + SDK float32 rounding in C++ (bit-identical).
        self.native_sampling=hasattr(self.lib,'tcb_sample_rows')
        if self.native_sampling:
            self.lib.tcb_sample_rows.argtypes=[ptr,ct.c_int,ct.POINTER(ct.c_longlong),ptr,ct.c_int,ct.POINTER(ct.c_int),ptr,ptr,ct.POINTER(ct.c_float),ptr]
            self.lib.tcb_sample_rows.restype=ct.c_int
        opts=config['ik']
        self.ik_options=np.array([opts['position_tolerance_m'],opts['orientation_tolerance_rad'],opts['max_iterations'],opts['step_limit_rad'],.1,opts['damping'],opts['reference_weight']],dtype=float)

    @staticmethod
    def ptr(a):return a.ctypes.data_as(ct.POINTER(ct.c_double))
    def legal(self,q):
        q=vector(q,7,'q');return bool(np.all(q>=self.lower)&np.all(q<=self.upper))
    def evaluate(self,q):
        q=vector(q,7,'q').copy();pose=np.zeros((4,4));jac=np.zeros((6,7));frames=np.zeros((8,4,4))
        args=[self.data,q,self.tool,pose,jac,frames]
        if self.lib.tcb_fk(*[self.ptr(a) for a in args]):raise ValueError('native FK rejected input')
        if not self.base_identity:
            pose=self.base@pose;frames=np.matmul(self.base,frames)
            jac[:3]=self.base[:3,:3]@jac[:3];jac[3:]=self.base[:3,:3]@jac[3:]
        return pose,jac,frames
    def fk(self,q):return self.evaluate(q)[0]
    def jacobian(self,q):return self.evaluate(q)[1]
    def fk_batch(self,q):
        q=np.ascontiguousarray(q,dtype=np.float64)
        if q.ndim!=2 or q.shape[1]!=7 or len(q)>1000000 or not np.isfinite(q).all():raise ValueError('invalid FK batch')
        poses=np.zeros((len(q),4,4))
        if self.lib.tcb_fk_batch(self.ptr(self.data),self.ptr(q),self.ptr(self.tool),self.ptr(poses),len(q)):raise ValueError('native batch rejected input')
        if not self.base_identity:poses=np.matmul(self.base,poses)
        return poses
    def solve(self,target,seed,reference=None):
        target=transform(target,'target');seed=vector(seed,7,'seed').copy()
        if not self.base_identity:target=np.ascontiguousarray(self.base_inverse@target)
        reference=seed.copy() if reference is None else vector(reference,7,'reference').copy()
        opt=self.ik_options
        out=np.zeros(7);stats=np.zeros(3)
        status=self.lib.tcb_ik(*[self.ptr(a) for a in [self.data,self.tool,target,seed,reference,opt,out,stats]])
        return dict(ok=status==0,status=status,q=out,position_error_m=float(stats[0]),orientation_error_rad=float(stats[1]),iterations=int(stats[2]))
    def solve_chain(self,targets,seed):
        targets=np.ascontiguousarray(targets,dtype=float)
        if targets.ndim!=3 or targets.shape[1:]!=(4,4) or not 1<=len(targets)<=64 or not np.isfinite(targets).all():raise ValueError('invalid IK batch')
        if not self.base_identity:targets=np.ascontiguousarray(np.matmul(self.base_inverse,targets))
        seed=vector(seed,7,'seed').copy();n=len(targets);out=np.zeros((n,7));stats=np.zeros((n,3));status=np.ones(n,dtype=np.int32)
        done=self.lib.tcb_ik_chain(*[self.ptr(a) for a in [self.data,self.tool,targets,seed,self.ik_options,out,stats]],status.ctypes.data_as(ct.POINTER(ct.c_int)),n)
        if not 1<=done<=n:raise ValueError('native IK chain rejected input')
        return [dict(ok=status[i]==0,status=int(status[i]),q=out[i].copy(),position_error_m=float(stats[i,0]),orientation_error_rad=float(stats[i,1]),iterations=int(stats[i,2])) for i in range(done)]
    def extrema_batch(self,coeff):
        coeff=np.ascontiguousarray(coeff,dtype=float)
        if coeff.ndim!=3 or coeff.shape[1:]!=(6,7) or not 1<=len(coeff)<=1024:raise ValueError('invalid coefficient batch')
        out=np.zeros((len(coeff),4,3,7))
        if self.lib.tcb_extrema_batch(self.ptr(coeff),self.ptr(out),len(coeff)):raise ValueError('native extrema rejected input')
        return out
    def self_collision_batch(self,q,pairs,limit):
        """First (row, pair index) whose capsule segments are closer than limit, else None."""
        q=np.ascontiguousarray(q,dtype=np.float64)
        if q.ndim!=2 or q.shape[1]!=7 or len(q)>1000000 or not np.isfinite(q).all():raise ValueError('invalid collision batch')
        I=np.ascontiguousarray([p[0] for p in pairs],dtype=np.int32);J=np.ascontiguousarray([p[1] for p in pairs],dtype=np.int32)
        hit=ct.c_int(-1);ip=lambda a:a.ctypes.data_as(ct.POINTER(ct.c_int))
        row=self.lib.tcb_self_collision_batch(self.ptr(self.data),self.ptr(q),self.ptr(self.tool),ip(I),ip(J),len(pairs),float(limit),len(q),ct.byref(hit))
        if row==-2:raise ValueError('native collision rejected input')
        return None if row<0 else (row,hit.value)
    def sample_rows(self,coeff,seg,u):
        """(sdk float32 degrees, model-space rounded radians) of the planner's final frames."""
        coeff=np.ascontiguousarray(coeff,dtype=np.float64);seg=np.ascontiguousarray(seg,dtype=np.int64)
        u=np.ascontiguousarray(u,dtype=np.float64);order=np.ascontiguousarray(self.order,dtype=np.int32)
        sign=np.ascontiguousarray(self.sign,dtype=np.float64);offset=np.ascontiguousarray(self.offset,dtype=np.float64)
        n=len(u);sdk=np.empty((n,7),dtype=np.float32);rounded=np.empty((n,7))
        if self.lib.tcb_sample_rows(self.ptr(coeff),len(coeff),seg.ctypes.data_as(ct.POINTER(ct.c_longlong)),self.ptr(u),n,
                order.ctypes.data_as(ct.POINTER(ct.c_int)),self.ptr(sign),self.ptr(offset),
                sdk.ctypes.data_as(ct.POINTER(ct.c_float)),self.ptr(rounded)):raise ValueError('native sampling rejected input')
        return sdk,rounded
    def to_sdk(self,q):
        q=vector(q,7,'q');return ((q[self.order]-self.offset)*self.sign*180/math.pi).tolist()
    def from_sdk(self,q):
        values=vector(q,7,'SDK degrees')*math.pi/180*self.sign+self.offset
        out=np.empty(7);out[self.order]=values;return out
    def to_sdk_batch(self,q):
        q=np.asarray(q,dtype=np.float64)
        if q.ndim!=2 or q.shape[1]!=7 or not np.isfinite(q).all():
            raise ValueError('q must contain finite seven-axis rows')
        return (q[:,self.order]-self.offset)*self.sign*180/math.pi
    def from_sdk_batch(self,q):
        q=np.asarray(q,dtype=np.float64)
        if q.ndim!=2 or q.shape[1]!=7 or not np.isfinite(q).all():
            raise ValueError('SDK degrees must contain finite seven-axis rows')
        out=np.empty_like(q);out[:,self.order]=q*math.pi/180*self.sign+self.offset
        return out
