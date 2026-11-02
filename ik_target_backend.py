"""One call per target; PS independently validates every returned final pose."""
import ctypes
import json
import math
from pathlib import Path
import time
import numpy as np
from ik_backend import PynqIKStep
from ik_target_contract import MAGIC,STATUSES,model_matches_nominal,validate_ip,validate_registers,validate_overlay_files

def target_inputs(model,position,axis,q0,config,mode):
    if not model_matches_nominal(model): raise ValueError('target kernel link geometry mismatch')
    values=[np.asarray(v,dtype=float) for v in
        (q0,position,axis,config['weights'],config['scales'],model.tool,model.tool_axis,model.limits)]
    if [v.shape for v in values]!=[(5,),(3,),(3,),(6,),(6,),(3,),(3,),(5,2)]:
        raise ValueError('invalid target shapes')
    scalars=[float(config[k]) for k in ('mu','max_joint_step_rad','position_tolerance_m',
        'tilt_tolerance_rad','stagnation_cost_change')]
    integers=[config[k] for k in ('max_iterations','line_search_trials','stagnation_window')]
    if (any(not np.isfinite(v).all() for v in values) or not np.isfinite(scalars).all()
        or min(scalars[:4])<=0 or scalars[4]<0 or np.any(values[3]<0) or np.any(values[4]<=0)
        or not model.legal(values[0]) or abs(np.linalg.norm(values[2])-1)>1e-8
        or any(type(v) is not int or not 1<=v<=cap for v,cap in zip(integers,(120,32,32)))
        or mode not in ('wls','rhs_only')): raise ValueError('invalid target values/config')
    with np.errstate(over='raise',invalid='raise'):
        arrays=[np.ascontiguousarray(v,dtype=np.float32).reshape(-1) for v in values]
        floats=np.asarray(scalars,dtype=np.float32)
    if min(floats[:4])<=0 or np.any(arrays[4]<=0): raise ValueError('float32 underflow')
    return arrays,floats,integers+[int(mode=='rhs_only')]

class TargetResultMixin:
    def _inputs(self,model,position,axis,q0,config,mode):
        """Reuse validated static inputs only while their exact values match.

        Arrays are fingerprinted including shape, so edits to an existing
        model/config invalidate the cache. Every new q/position/axis is still
        validated and converted; every returned pose is independently checked.
        """
        if not all(isinstance(v,np.ndarray) for v in (model.offsets,model.axes)):
            raise ValueError('target kernel link geometry mismatch')
        values=[np.asarray(v,dtype=float) for v in
                (q0,position,axis,config['weights'],config['scales'],model.tool,model.tool_axis,model.limits)]
        scalars=tuple(float(config[k]) for k in ('mu','max_joint_step_rad','position_tolerance_m',
                                             'tilt_tolerance_rad','stagnation_cost_change'))
        integers=tuple(config[k] for k in ('max_iterations','line_search_trials','stagnation_window'))
        key=(tuple((v.shape,v.tobytes()) for v in values[3:]+[model.offsets,model.axes]),
             scalars,tuple((type(v),v) for v in integers),mode)
        if key!=getattr(self,'_input_key',None):
            arrays,floats,ints=target_inputs(model,position,axis,q0,config,mode)
            self._input_key=key;self._prepared_static=(arrays[3:],floats,ints)
            self.input_cache_misses=getattr(self,'input_cache_misses',0)+1
            return arrays,floats,ints
        dynamic=values[:3]
        if ([v.shape for v in dynamic]!=[(5,),(3,),(3,)]
                or any(not math.isfinite(float(x)) for v in dynamic for x in v.flat)
                or any(not lo<=float(x)<=hi for x,lo,hi in zip(dynamic[0],model.limits[:,0],model.limits[:,1]))
                or abs(math.sqrt(sum(float(x)*float(x) for x in dynamic[2]))-1)>1e-8):
            raise ValueError('invalid target values/config')
        with np.errstate(over='raise',invalid='raise'):
            arrays=[np.ascontiguousarray(v,dtype=np.float32) for v in dynamic]
        self.input_cache_hits=getattr(self,'input_cache_hits',0)+1
        static,floats,ints=self._prepared_static
        return arrays+static,floats,ints

    def _pose_key(self,model,q):
        return tuple(np.asarray(v,dtype=float).tobytes() for v in
            (q,model.offsets,model.axes,model.tool,model.tool_axis,model.limits))

    def _cached_success(self,model,position,axis,q,config):
        from r1a.solve import Result
        if getattr(self,'_last_pose_key',None)!=self._pose_key(model,q): return None
        pe,te=model.pose_errors(self._last_pose,np.asarray(position),np.asarray(axis))
        if pe>config['position_tolerance_m'] or te>config['tilt_tolerance_rad']: return None
        self.cached_successes=getattr(self,'cached_successes',0)+1
        values=np.asarray(q,dtype=float).tolist()
        return Result('OK',values,values,0,pe,te,[dict(iteration=0,q=values,position_m=pe,tilt_rad=te)])

    def _result(self,model,position,axis,config,status,q,iterations,cancel):
        from planning import SOURCE  # establish planner layout
        from r1a.solve import Result
        if status not in STATUSES or not 0<=iterations<=config['max_iterations']:
            raise FloatingPointError('target status/iteration contract mismatch')
        if any(not math.isfinite(float(v)) for v in q):raise FloatingPointError('nonfinite target result')
        if status==1: return Result('INVALID_INPUT',None,None,iterations,None,None,[])
        # Limits are float32 in PL; clamp only conversion-sized deviations.
        if any(not lo-2e-7<=v<=hi+2e-7 for v,lo,hi in zip(q,model.limits[:,0],model.limits[:,1])):
            raise FloatingPointError('target result outside limits')
        if any(not lo<=v<=hi for v,lo,hi in zip(q,model.limits[:,0],model.limits[:,1])):
            q=np.clip(q,model.limits[:,0],model.limits[:,1])
        pose=model.pose(q); pe,te=model.pose_errors(pose,np.asarray(position),np.asarray(axis))
        label=STATUSES[status]
        if status==0 and (pe>config['position_tolerance_m'] or te>config['tilt_tolerance_rad']):
            raise FloatingPointError('PL success failed independent PS pose check')
        if cancel and cancel(): label='ABORT'
        if label=='OK':
            self._last_pose_key=self._pose_key(model,q); self._last_pose=pose
        history=[dict(iteration=iterations,q=q.tolist(),position_m=pe,tilt_rad=te)]
        return Result(label,q.tolist() if label=='OK' else None,q.tolist(),iterations,pe,te,history)

class PynqIKTarget(TargetResultMixin):
    name='PL_z20_ik_target'
    _write=PynqIKStep._write
    _read=PynqIKStep._read

    def validate_model(self,model):
        return model_matches_nominal(model)

    def __init__(self,bitfile=None,ip_name='z20_ik_target_0',mmio=None,registers=None,timeout_s=2.,
                 load_policy='download',platform_manifest=None,platform_ready=None):
        if not np.isfinite(timeout_s) or timeout_s<=0: raise ValueError('invalid timeout')
        if load_policy not in ('download','attach'): raise ValueError('invalid PL load policy')
        self.load_policy=load_policy
        if mmio is None:
            bitfile=Path(bitfile).resolve()
            if not bitfile.is_file() or not bitfile.with_suffix('.hwh').is_file():
                raise ValueError('需要 target bit/hwh/registers.json 三件套')
            registers, self.artifact_hashes = validate_overlay_files(bitfile, ip_name)
            required=validate_registers(registers,True)
            if load_policy=='attach':
                import platform
                from platform_runtime import READY, validate_attached
                base,size=validate_attached(bitfile,ip_name,self.artifact_hashes,platform_manifest,
                    platform_ready or READY,kernel_release=platform.release())
                from pynq import MMIO
                mmio=MMIO(base,size)
            else:
                from pathlib import Path as _Path
                if (_Path('/run/so101-platform/ready.json').exists()
                        or list(_Path('/sys/class/drm').glob('card*-*'))):
                    raise RuntimeError('显示平台已在使用 PL；必须使用 attach 模式，禁止重载')
                from pynq import Overlay
                self.overlay=Overlay(str(bitfile),download=False)
                validate_ip(self.overlay.ip_dict.get(ip_name,{}),required)
                self.overlay.download(); mmio=getattr(self.overlay,ip_name).mmio
        required=validate_registers(registers)
        self.mmio,self.registers,self.timeout_s=mmio,dict(registers),timeout_s
        array=getattr(mmio,'array',None)
        self.array=array if (isinstance(array,np.ndarray) and array.ndim==1
            and array.dtype==np.dtype('uint32') and array.flags.c_contiguous
            and array.flags.writeable and array.nbytes>=required) else None
        self.calls=self.input_words=self.output_words=self.evaluations=0
        self.total_s=self.write_s=self.wait_s=self.read_s=self.validate_s=0.
        self.faulted=False; self._cache={}; self.failed_calls=0; self.last_error=None
        self.inputs_s=self.pose_cache_s=0.

    def _write_inputs(self,arrays,floats,integers):
        # q/position always change. Avoid rebuilding twelve static register
        # buffers on every target; the validated byte key detects all edits.
        self._write('q_init',arrays[0]);self._write('target_position',arrays[1])
        self._write('target_axis',arrays[2],cache=True)
        if getattr(self,'_register_input_key',None)==self._input_key:return
        for key,value in zip(('weights','scales','tool','tool_axis','limits'),arrays[3:]):
            self._write(key,value,cache=True)
        for key,value in zip(('mu','max_step','position_tolerance','tilt_tolerance','stagnation_cost_change'),floats):
            if key in ('position_tolerance','tilt_tolerance'):value*=.999
            self._write(key,[value],cache=True)
        for key,value in zip(('max_iterations','line_search_trials','stagnation_window','mode'),integers):
            self._write(key,[value],integer=True,cache=True)
        self._register_input_key=self._input_key

    def solve_target(self,model,position,axis,q0,config,cancel=None,mode='wls'):
        from planning import SOURCE
        from r1a.solve import Result
        if cancel and cancel(): return Result('ABORT',None,list(q0),0,None,None,[])
        inputs_started=time.monotonic()
        try: arrays,floats,integers=self._inputs(model,position,axis,q0,config,mode)
        except (ValueError,KeyError,TypeError,OverflowError,FloatingPointError):
            return Result('INVALID_INPUT',None,None,0,None,None,[])
        self.inputs_s+=time.monotonic()-inputs_started
        if self.faulted: return Result('NUMERIC',None,None,0,None,None,[])
        cache_started=time.monotonic()
        cached=self._cached_success(model,position,axis,q0,config)
        self.pose_cache_s+=time.monotonic()-cache_started
        if cached is not None: return cached
        started=time.monotonic()
        try:
            self.mmio.read(0)
            self._write_inputs(arrays,floats,integers)
            self.mmio.write(0,1); written=time.monotonic(); polls=0
            # On cancellation drain this bounded call before returning ABORT.
            # A timeout faults the session; never reuse a still-running kernel.
            while not self.mmio.read(0)&2:
                if time.monotonic()-written>=self.timeout_s: raise FloatingPointError('target timeout; reload overlay')
                polls+=1
                if polls>32: time.sleep(.0001)
            completed=time.monotonic()
            status=int(self.mmio.read(self.registers['return']))
            magic=int(self.mmio.read(self.registers['abi_version']))
            iterations=int(self.mmio.read(self.registers['iterations_used']))
            evaluations=int(self.mmio.read(self.registers['evaluations_used']))
            if magic!=MAGIC or not 0<=evaluations<=1+integers[0]*integers[1]:
                raise FloatingPointError('target ABI/evaluation contract mismatch')
            q=self._read('q_result',5)
            reported=(float(self._read('position_error',1)[0]),float(self._read('tilt_error',1)[0]))
            if any(not math.isfinite(x) or x<0 for x in reported):
                raise FloatingPointError('invalid target errors')
            read=time.monotonic()
            result=self._result(model,position,axis,config,status,q,iterations,cancel)
            if result.position_error_m is not None and (
                abs(reported[0]-result.position_error_m)>2e-6 or abs(reported[1]-result.tilt_error_rad)>2e-5):
                raise FloatingPointError('target reported error disagrees with PS')
        except (ValueError,FloatingPointError,OSError,RuntimeError,OverflowError) as exc:
            self.faulted=True; self._cache.clear()
            self.failed_calls+=1; self.last_error=str(exc)
            return Result('NUMERIC',None,None,0,None,None,[])
        ended=time.monotonic(); self.calls+=1; self.evaluations+=evaluations
        self.output_words+=4; self.total_s+=ended-started; self.write_s+=written-started
        self.wait_s+=completed-written; self.read_s+=read-completed; self.validate_s+=ended-read
        return result

    def metrics(self):
        return dict(calls=self.calls,total_s=self.total_s,write_s=self.write_s,wait_s=self.wait_s,
            read_s=self.read_s,validate_s=self.validate_s,evaluations=self.evaluations,
            input_words=self.input_words,output_words=self.output_words,static_input_cache=True,
            transport='mapped_array' if self.array is not None else 'register_calls',
            kernel='z20_ik_target',abi='so101-ik-target-v1',faulted=self.faulted,
            pl_load_policy=self.load_policy,
            failed_calls=self.failed_calls,last_error=self.last_error,
            artifact_hashes=getattr(self,'artifact_hashes',{}),
            inputs_s=self.inputs_s,pose_cache_s=self.pose_cache_s,
            input_cache_hits=getattr(self,'input_cache_hits',0),input_cache_misses=getattr(self,'input_cache_misses',0),
            cached_successes=getattr(self,'cached_successes',0))

class NativeIKTarget(TargetResultMixin):
    name='HOST_CPP_z20_ik_target'
    def __init__(self,library):
        self.library=ctypes.CDLL(str(Path(library).resolve())); self.fn=self.library.z20_ik_target
        self.ptr=ctypes.POINTER(ctypes.c_float); iptr=ctypes.POINTER(ctypes.c_int)
        self.fn.argtypes=[self.ptr]*8+[ctypes.c_float]*5+[ctypes.c_int]*4+[self.ptr]*3+[iptr]*2+[ctypes.POINTER(ctypes.c_uint)]
        self.fn.restype=ctypes.c_int; self.calls=self.evaluations=0; self.total_s=0.
    def solve_target(self,model,position,axis,q0,config,cancel=None,mode='wls'):
        from planning import SOURCE
        from r1a.solve import Result
        if cancel and cancel(): return Result('ABORT',None,list(q0),0,None,None,[])
        try: arrays,floats,integers=self._inputs(model,position,axis,q0,config,mode)
        except (ValueError,KeyError,TypeError,OverflowError,FloatingPointError):
            return Result('INVALID_INPUT',None,None,0,None,None,[])
        cached=self._cached_success(model,position,axis,q0,config)
        if cached is not None: return cached
        floats=floats.copy(); floats[2:4]*=.999
        q,pe,te=[np.zeros(n,np.float32) for n in (5,1,1)]
        used=ctypes.c_int(); evaluations=ctypes.c_int(); magic=ctypes.c_uint()
        started=time.perf_counter()
        status=self.fn(*[v.ctypes.data_as(self.ptr) for v in arrays],*floats,*integers,
            *[v.ctypes.data_as(self.ptr) for v in (q,pe,te)],ctypes.byref(used),ctypes.byref(evaluations),ctypes.byref(magic))
        if magic.value!=MAGIC: raise FloatingPointError('native target ABI mismatch')
        self.calls+=1; self.evaluations+=evaluations.value; self.total_s+=time.perf_counter()-started
        return self._result(model,position,axis,config,status,q.astype(float),used.value,cancel)
    def metrics(self):
        return dict(calls=self.calls,total_s=self.total_s,evaluations=self.evaluations,
            input_cache_hits=getattr(self,'input_cache_hits',0),input_cache_misses=getattr(self,'input_cache_misses',0),
            cached_successes=getattr(self,'cached_successes',0),transport='ctypes_host_cpp')
