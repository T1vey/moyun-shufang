"""Bounded DDR transport and speculative IK prefixes; PS remains authoritative.

The new hardware is opt-in and requires its own sealed platform. FK_ROWS is
shadow-only: no unproved FP32 error bound is used to accept a motion sample.
"""
import ctypes
import os
import threading
import time
from pathlib import Path
import numpy as np
from ik_target_backend import TargetResultMixin
import planner_accel_contract as contract
from planner_accel_lease import acquire_planner_lease


# A timeout must not turn the last Python reference into a free of live CMA.
# The non-daemon guardian also postpones normal interpreter shutdown until idle.
_INFLIGHT = {}
_INFLIGHT_LOCK = threading.Lock()


class NativePlannerTransport:
    """Host C++ differential tests, not evidence of ARM/FPGA performance."""
    def __init__(self,library,protocol=contract,top=None):
        self.contract=protocol
        self.library=ctypes.CDLL(str(Path(library).resolve()))
        selected_top=top or protocol.TOP
        self.fn=getattr(self.library,selected_top)
        self.completion_options=({'expected_capabilities':protocol.capabilities_for_top(selected_top)}
                                 if hasattr(protocol,'capabilities_for_top') else {})
        self.ptr=ctypes.POINTER(ctypes.c_uint64)
        self.fn.argtypes=[self.ptr]*5+[ctypes.c_uint32]*5
        self.fn.restype=None
        self.faulted=False;self.starts=0

    def execute(self,ctx,mode,inputs,job_id,generation,cancel=None):
        contract=self.contract
        count=len(inputs)
        dtype=contract.IK_OUTPUT if mode==contract.IK_CHAIN else contract.FK_OUTPUT
        output=np.zeros(count,dtype=dtype);header=np.zeros(1,dtype=contract.HEADER)
        cancellation=np.zeros(8,dtype='<u8')
        if cancel and cancel():cancellation[0]=(job_id<<32)|generation
        arrays=[ctx,inputs,output,header,cancellation]
        self.fn(*[a.ctypes.data_as(self.ptr) for a in arrays],mode,count,count,job_id,generation)
        self.starts+=1
        return contract.validate_completion(header,output,inputs,ctx,mode,job_id,generation,**self.completion_options)


class DDRTransport:
    """Bounded buffers retained through faults until hardware idle is observed.

    An unresponsive IP deliberately keeps a non-daemon guardian alive. SIGKILL,
    os._exit and kernel failure are outside userspace lifetime guarantees; the
    persistent lease marker then requires a platform reset/reboot before reuse.
    """
    def __init__(self,mmio,registers,allocator=None,timeout_s=10.,lease=None,owns_lease=False,protocol=contract):
        self.contract=protocol
        contract=protocol
        contract.validate_registers(registers)
        self.completion_options=({'expected_capabilities':contract.expected_capabilities(registers)}
                                 if hasattr(contract,'expected_capabilities') else {})
        if not np.isfinite(timeout_s) or timeout_s<=0:raise ValueError('invalid planner timeout')
        if allocator is None:
            from pynq import allocate
            allocator=allocate
        self.mmio=mmio;self.registers=dict(registers);self.timeout_s=float(timeout_s)
        self.owner_pid=os.getpid()
        self.faulted=False;self.inflight=False;self.starts=0
        self.lock=threading.RLock();self.buffers={}
        self.lease=lease;self.owns_lease=owns_lease
        self.write_s=self.wait_s=self.read_s=0.
        self._settled=None;self._handoff=None;self._guardian=None
        self._cancel_identity=None
        if lease is not None:
            lease.assert_owned(getattr(mmio,'base_addr',None))
            lease.claim(self)
        try:
            regions=[]
            sizes=getattr(contract,'BUFFER_SIZES',(('config_words',512),('input_words',65536),
                ('output_words',32768),('result_words',64),('cancel_words',64)))
            for name,size in sizes:
                b=allocator(shape=(size//8,),dtype=np.uint64)
                self.buffers[name]=b
                address=int(b.device_address)
                if address%64 or address<0 or address+size>2**32 or not b.flags.c_contiguous:
                    raise ValueError('planner DDR buffer must be contiguous, aligned and in 32-bit DDR')
                regions.append((address,address+size))
            regions.sort()
            if any(right[0]<left[1] for left,right in zip(regions,regions[1:])):
                raise ValueError('planner DDR buffer physical regions must not overlap')
        except Exception:
            self.close()
            raise

    def close(self):
        with self.lock:
            self._assert_process()
            if self.inflight:raise RuntimeError('planner still owns DDR; cannot release buffers')
            for b in self.buffers.values():
                if hasattr(b,'freebuffer'):b.freebuffer()
            self.buffers={}
            self.faulted=True
            if self.lease is not None:
                self.lease.release_claim(self)
                if self.owns_lease:self.lease.close()

    def _assert_process(self):
        if self.owner_pid!=os.getpid():
            raise RuntimeError('planner transport inherited by another process; fork with PYNQ buffers is unsupported')

    def __del__(self):
        # In-flight objects have strong owners; this runs only after drain or
        # before launch. PynqBuffer.__del__ alone is not a hardware lifetime rule.
        try:self.close()
        except Exception:pass

    def _drained(self):
        if self.lease is not None:self.lease.mark_drained()
        self.inflight=False
        if self._settled is not None:self._settled.set()
        with _INFLIGHT_LOCK:_INFLIGHT.pop(id(self),None)

    def _guard_until_idle(self,settled,handoff):
        while not settled.wait(.02):
            if not handoff.is_set():continue
            try:
                with self.lock:
                    if not self.inflight:return
                    if self.mmio.read(0)&4:
                        self._drained()
                        self.close()
                        return
            except Exception:
                # Failed MMIO reads are not evidence of drain. Retain buffers,
                # lease and thread until explicit maintenance can prove idle.
                continue

    def _retain_before_start(self,job_id,generation):
        self._settled=threading.Event();self._handoff=threading.Event()
        self._cancel_identity=(job_id<<32)|generation
        if self.lease is not None:self.lease.mark_inflight(job_id,generation)
        self.inflight=True
        with _INFLIGHT_LOCK:_INFLIGHT[id(self)]=self
        self._guardian=threading.Thread(target=self._guard_until_idle,
            args=(self._settled,self._handoff),name='so101-planner-ddr-drain',daemon=False)
        try:self._guardian.start()
        except BaseException:
            # Doorbell has not been written, so the previous idle observation
            # still proves no hardware access to these buffers.
            self._drained()
            raise

    def _request_cancel(self):
        self.buffers['cancel_words'][0]=self._cancel_identity
        self.buffers['cancel_words'].flush()

    def release_after_idle(self):
        """Maintenance only: no reset, no recovery into a usable session."""
        with self.lock:
            self._assert_process()
            if not self.buffers:return
            if not self.mmio.read(0)&4:raise RuntimeError('planner has not drained outstanding work')
            self._drained();self.faulted=True
            self.close()

    def _pointer(self,name):
        value=int(self.buffers[name].device_address);offset=self.registers[name]
        self.mmio.write(offset,value & 0xffffffff);self.mmio.write(offset+4,value>>32)

    def execute(self,ctx,mode,inputs,job_id,generation,cancel=None):
        with self.lock:
            self._assert_process()
            try:return self._execute_locked(ctx,mode,inputs,job_id,generation,cancel)
            finally:
                # Also covers BaseException between launch and polling phases.
                if self.inflight:
                    self.faulted=True
                    try:self._request_cancel()
                    except BaseException:pass
                    self._handoff.set()

    def _execute_locked(self,ctx,mode,inputs,job_id,generation,cancel=None):
        contract=self.contract
        with self.lock:
            if 'supported_modes' in self.registers and mode not in self.registers['supported_modes']:
                raise ValueError('planner mode is not supported by the sealed kernel; use CPU for this operation')
            if self.faulted or self.inflight:raise FloatingPointError('planner session faulted; platform maintenance required')
            if self.lease is not None:self.lease.assert_owned(getattr(self.mmio,'base_addr',None))
            # An attached platform may still be running a previous owner. Do
            # not change addresses or cache lines until idle has been observed.
            if not self.mmio.read(0)&4:
                self.faulted=True
                raise FloatingPointError('planner is not idle; no buffers were changed')
            capacity=contract.MAX_IK if mode==contract.IK_CHAIN else contract.MAX_FK
            expected=contract.IK_INPUT if mode==contract.IK_CHAIN else contract.FK_INPUT
            if mode not in (contract.IK_CHAIN,contract.FK_ROWS):raise ValueError('invalid planner mode')
            if ctx.dtype!=contract.CONTEXT or ctx.shape!=(1,):raise ValueError('invalid planner context buffer')
            if inputs.dtype!=expected or inputs.ndim!=1 or not 1<=len(inputs)<=capacity:raise ValueError('invalid planner batch')
            if not 1<=generation<=0xffffffff or not 0<job_id<=0xffffffff:raise ValueError('invalid planner generation')
            output_dtype=contract.IK_OUTPUT if mode==contract.IK_CHAIN else contract.FK_OUTPUT
            write_started=time.perf_counter()
            try:
                # Cache maintenance and durable ownership precede the doorbell.
                for b in self.buffers.values():b.fill(0)
                for name,value in (('config_words',ctx),('input_words',inputs)):
                    self.buffers[name].view(np.uint8)[:value.nbytes]=value.view(np.uint8).reshape(-1)
                if (self.completion_options.get('expected_capabilities')==getattr(contract,'FP32_CAPABILITIES',-1)
                    and cancel and cancel()):self.buffers['cancel_words'][0]=(job_id<<32)|generation
                for b in self.buffers.values():b.flush()
                for name in contract.POINTERS:self._pointer(name)
                for name,value in (('mode',mode),('count',len(inputs)),('output_capacity',len(inputs)),
                                   ('job_id',job_id),('generation',generation)):
                    self.mmio.write(self.registers[name],int(value))
                self.mmio.read(0)  # clear a completed predecessor before launch
                self._retain_before_start(job_id,generation)
                self.mmio.write(0,1);self.starts+=1
            except BaseException:
                self.faulted=True
                if self.inflight:
                    try:self._request_cancel()
                    except Exception:pass
                    self._handoff.set()
                raise
            finally:self.write_s+=time.perf_counter()-write_started
            wait_started=time.perf_counter();started=time.monotonic();cancelled=False;done_seen=False
            try:
                while True:
                    control=self.mmio.read(0)
                    done_seen=done_seen or bool(control&2)
                    if done_seen and control&4:break
                    if cancel and cancel() and not cancelled:
                        self._request_cancel();cancelled=True
                    if time.monotonic()-started>=self.timeout_s:
                        raise FloatingPointError('planner timeout: retain DDR buffers until platform is idle')
                    time.sleep(.0001)
                self._drained()
            except BaseException:
                self.faulted=True
                try:self._request_cancel()
                except Exception:pass
                self._handoff.set()
                raise
            finally:self.wait_s+=time.perf_counter()-wait_started
            read_started=time.perf_counter()
            try:
                self.buffers['output_words'].invalidate();self.buffers['result_words'].invalidate()
                output=self.buffers['output_words'].view(output_dtype)[:len(inputs)]
                header=self.buffers['result_words'].view(contract.HEADER)
                return contract.validate_completion(header,output,inputs,ctx,mode,job_id,generation,**self.completion_options)
            except BaseException:
                self.faulted=True
                raise
            finally:self.read_s+=time.perf_counter()-read_started


class PlannerAccel(TargetResultMixin):
    name='PL_planner_accel_v2'
    def __init__(self,transport):
        self.transport=transport;self.faulted=False
        self.calls=self.evaluations=self.batch_calls=self.cached_successes=0
        self.total_s=self.inputs_s=self.pose_cache_s=self.validate_s=0.
        self.write_s=self.wait_s=self.read_s=0.
        self.input_words=self.output_words=self.failed_calls=0
        self.last_error=None;self._prefetched=[];self._prepared=None
        self._generation=0;self._job_id=1;self._work_budget=None;self._work_used=0
        self.fk_rows_checked=0;self.fk_max_position_difference=0.;self.fk_max_axis_difference=0.
        self.prepare_calls=0;self.prepare_s=0.

    def validate_model(self,model):return contract.model_matches_nominal(model)

    def begin_plan(self,total_iteration_budget):
        self._prefetched=[];self._prepared=None;self._work_used=0
        self._work_budget=2*int(total_iteration_budget)
        self._job_id=(self._job_id % 0xffffffff)+1

    def needs_target_batch(self):
        """Only copy a new prefix after the previously computed rows are used.

        This is a scheduling hint, not an authority-seed acceptance check. A
        later seed/config mismatch still discards the tail in solve_target and
        uses its single-target fallback for that call.
        """
        return not self.faulted and not self._prefetched and self._prepared is None

    def prepare_targets(self,targets,index,total_remaining):
        """Schedule only first attempts; solve_target checks the authority seed."""
        started=time.perf_counter()
        self._prepared=(tuple((np.array(t['position'],dtype=float,copy=True),
                               np.array(t['axis'],dtype=float,copy=True),index+i)
                              for i,t in enumerate(targets[:contract.MAX_IK])),int(total_remaining))
        self.prepare_calls+=1;self.prepare_s+=time.perf_counter()-started

    def _execute(self,ctx,mode,inputs,cancel):
        self._generation=(self._generation % 0xffffffff)+1
        started=time.perf_counter()
        try:
            header,output=self.transport.execute(ctx,mode,inputs,self._job_id,self._generation,cancel)
        except (ValueError,FloatingPointError,OSError,RuntimeError,OverflowError):
            self.faulted=True
            raise
        finally:
            self.total_s+=time.perf_counter()-started
            for key in ('write_s','wait_s','read_s'):
                setattr(self,key,getattr(self.transport,key,0.))
        self.batch_calls+=1
        self.input_words+=(ctx.nbytes+inputs.nbytes)//4
        self.output_words+=(64+output.nbytes)//4
        self.evaluations+=header['total_evaluations'];self._work_used+=header['total_iterations']
        return header,output

    @staticmethod
    def _same(entry,position,axis,q,key):
        return (entry[4]==key and np.array_equal(entry[0],position)
                and np.array_equal(entry[1],axis) and np.array_equal(entry[2],q))

    def solve_target(self,model,position,axis,q0,config,cancel=None,mode='wls'):
        from planning import SOURCE
        from r1a.solve import Result
        if cancel and cancel():return Result('ABORT',None,list(q0),0,None,None,[])
        started=time.perf_counter()
        try:self._inputs(model,position,axis,q0,config,mode)
        except (ValueError,KeyError,TypeError,OverflowError,FloatingPointError):
            self._prefetched=[];self._prepared=None
            return Result('INVALID_INPUT',None,None,0,None,None,[])
        self.inputs_s+=time.perf_counter()-started
        if self.faulted:return Result('NUMERIC',None,None,0,None,None,[])
        prepared=self._prepared;self._prepared=None
        cache_started=time.perf_counter();cached=self._cached_success(model,position,axis,q0,config)
        self.pose_cache_s+=time.perf_counter()-cache_started
        if cached is not None:
            # Preserve the PS FP64 cache decision. A speculative zero-iteration
            # row may be consumed only when it leaves the authority seed exact;
            # otherwise every downstream seed must be recomputed.
            if (self._prefetched
                    and self._same(self._prefetched[0],position,axis,q0,self._input_key)
                    and int(self._prefetched[0][3]['status']) == 0
                    and int(self._prefetched[0][3]['iterations']) == 0
                    and np.array_equal(self._prefetched[0][3]['q'].astype(float),q0)):
                self._prefetched.pop(0)
            else:
                self._prefetched=[]
            return cached
        try:
            if not self._prefetched or not self._same(self._prefetched[0],position,axis,q0,self._input_key):
                self._prefetched=[]
                candidates=((np.asarray(position),np.asarray(axis),0),)
                total=config['max_iterations']
                if prepared and prepared[0] and np.array_equal(prepared[0][0][0],position) and np.array_equal(prepared[0][0][1],axis):
                    candidates,total=prepared
                total=min(total,len(candidates)*int(config['max_iterations']))
                if self._work_budget is not None:
                    remaining=self._work_budget-self._work_used
                    if remaining<=0:raise FloatingPointError('speculative IK work budget exhausted')
                    total=min(total,remaining)
                ctx,_=contract.context(model,q0,config,mode,total_budget=total)
                inputs=np.zeros(len(candidates),dtype=contract.IK_INPUT)
                positions = np.asarray([p for p,a,identifier in candidates], dtype=float)
                axes = np.asarray([a for p,a,identifier in candidates], dtype=float)
                if (positions.shape != (len(candidates), 3) or axes.shape != positions.shape
                        or not np.isfinite(positions).all() or not np.isfinite(axes).all()
                        or np.any(np.abs(np.linalg.norm(axes, axis=1)-1) > 1e-8)):
                    raise ValueError('invalid queued target')
                with np.errstate(over='raise',invalid='raise'):
                    inputs['position'] = positions
                    inputs['axis'] = axes
                inputs['id'] = [identifier for p,a,identifier in candidates]
                header,output=self._execute(ctx,contract.IK_CHAIN,inputs,cancel)
                if header['status']==2 or (cancel and cancel()):return Result('ABORT',None,list(q0),0,None,None,[])
                if header['status'] not in (0,1,7) or not len(output):raise FloatingPointError('planner batch failed: '+contract.BATCH_STATUS[header['status']])
                seed=np.asarray(q0).copy()
                for (p,a,_),row in zip(candidates,output):
                    self._prefetched.append((p,a,seed,row.copy(),self._input_key))
                    seed=row['q'].astype(float)
            _,_,_,row,_=self._prefetched.pop(0)
            validated=time.perf_counter()
            r=self._result(model,position,axis,config,int(row['status']),row['q'].astype(float),int(row['iterations']),cancel)
            if r.position_error_m is not None and (abs(float(row['position_error'])-r.position_error_m)>2e-6
                    or abs(float(row['tilt_error'])-r.tilt_error_rad)>2e-5):
                raise FloatingPointError('planner IK residual disagrees with independent PS FK')
            self.validate_s+=time.perf_counter()-validated;self.calls+=1
            if r.status!='OK':self._prefetched=[]
            return r
        except (ValueError,FloatingPointError,OSError,RuntimeError,OverflowError) as exc:
            self.faulted=True;self._prefetched=[];self.failed_calls+=1;self.last_error=str(exc)
            return Result('NUMERIC',None,None,0,None,None,[])

    def fk_rows(self,model,qs,config,cancel=None):
        """Exercise hardware in shadow mode, returning independent PS FK only."""
        if self.faulted:raise FloatingPointError('planner session faulted')
        qs=np.asarray(qs,dtype=np.float64)
        if qs.ndim!=2 or qs.shape[1]!=5 or not np.isfinite(qs).all():raise ValueError('invalid FK rows')
        if len(qs)==0:return np.empty((0,3)),np.empty((0,3))
        if not self.validate_model(model):raise ValueError('planner FK model mismatch')
        tips=[];axes=[]
        for offset in range(0,len(qs),contract.MAX_FK):
            if cancel and cancel():raise InterruptedError('ABORT')
            q=qs[offset:offset+contract.MAX_FK]
            reference=model.pose_many(q)
            expected_tip=reference[:,:3,3];expected_axis=reference[:,:3,:3]@model.tool_axis
            ctx,_=contract.context(model,q[0],config)
            inputs=np.zeros(len(q),dtype=contract.FK_INPUT);inputs['q']=q
            inputs['id']=np.arange(offset,offset+len(q),dtype=np.uint32)
            header,output=self._execute(ctx,contract.FK_ROWS,inputs,cancel)
            if header['status']==2 or (cancel and cancel()):raise InterruptedError('ABORT')
            if header['status']!=0:
                self.faulted=True
                raise FloatingPointError('planner FK shadow batch failed')
            self.fk_max_position_difference=max(self.fk_max_position_difference,float(np.linalg.norm(output['tip']-expected_tip,axis=1).max()))
            self.fk_max_axis_difference=max(self.fk_max_axis_difference,float(np.linalg.norm(output['axis']-expected_axis,axis=1).max()))
            self.fk_rows_checked+=len(q);tips.append(expected_tip);axes.append(expected_axis)
        return np.vstack(tips),np.vstack(axes)

    def metrics(self):
        return dict(calls=self.calls,evaluations=self.evaluations,total_s=self.total_s,write_s=self.write_s,
            wait_s=self.wait_s,read_s=self.read_s,validate_s=self.validate_s,inputs_s=self.inputs_s,
            pose_cache_s=self.pose_cache_s,input_words=self.input_words,output_words=self.output_words,
            cached_successes=self.cached_successes,input_cache_hits=getattr(self,'input_cache_hits',0),
            prepare_calls=self.prepare_calls,prepare_s=self.prepare_s,
            input_cache_misses=getattr(self,'input_cache_misses',0),batch_calls=self.batch_calls,
            kernel=contract.TOP,abi=contract.ABI,faulted=self.faulted,failed_calls=self.failed_calls,
            last_error=self.last_error,transport='host_cpp' if isinstance(self.transport,NativePlannerTransport) else 'm_axi_DDR',fk_mode='shadow_only',
            ddr_phase_timing_available=isinstance(self.transport,DDRTransport),
            fk_rows_checked=self.fk_rows_checked,fk_max_position_difference_m=self.fk_max_position_difference,
            fk_max_axis_difference=self.fk_max_axis_difference,
            pl_load_policy=getattr(self,'load_policy','native_test'),artifact_hashes=getattr(self,'artifact_hashes',{}))


class NativePlannerAccel(PlannerAccel):
    name='HOST_CPP_planner_accel_v2'
    def __init__(self,library):super().__init__(NativePlannerTransport(library))


class PynqPlannerAccel(PlannerAccel):
    def __init__(self,bitfile=None,ip_name=contract.TOP+'_0',load_policy='attach',platform_manifest=None,
                 platform_ready=None,mmio=None,registers=None,allocator=None,timeout_s=10.,
                 lease=None,lease_directory=None):
        if load_policy not in ('attach','download'):raise ValueError('invalid planner load policy')
        self.load_policy=load_policy
        owns_lease=lease is None
        try:
            if mmio is None:
                registers,self.artifact_hashes=contract.validate_overlay_files(bitfile,ip_name)
                required=contract.validate_registers(registers,True)
                from pynq import MMIO
                if load_policy=='attach':
                    import platform
                    from platform_runtime import READY,validate_attached
                    base,size=validate_attached(bitfile,ip_name,self.artifact_hashes,platform_manifest,
                        platform_ready or READY,kernel_release=platform.release())
                    if lease is None:lease=acquire_planner_lease(base,lease_directory)
                    lease.assert_owned(base)
                    if allocator is None:
                        # PYNQ 2.7 can use a process-local PL metadata server.
                        # The boot loader's default_memory does not survive as
                        # a reliable allocation target in this new process.
                        from pynq import Overlay
                        self.overlay=Overlay(str(bitfile),download=False)
                    mmio=MMIO(base,size)
                else:
                    if Path('/run/so101-platform/ready.json').exists() or list(Path('/sys/class/drm').glob('card*-*')):
                        raise RuntimeError('display owns PL; planner must attach to the sealed platform')
                    from pynq import Overlay
                    self.overlay=Overlay(str(bitfile),download=False)
                    description=self.overlay.ip_dict.get(ip_name,{})
                    contract.validate_ip(description,required)
                    base=description.get('phys_addr')
                    if not isinstance(base,int):raise ValueError('planner physical IP base missing')
                    if lease is None:lease=acquire_planner_lease(base,lease_directory)
                    lease.assert_owned(base)
                    self.overlay.download();mmio=getattr(self.overlay,ip_name).mmio
            else:
                base=getattr(mmio,'base_addr',None)
                if not isinstance(base,int):raise ValueError('planner MMIO physical base address required')
                if lease is None:lease=acquire_planner_lease(base,lease_directory)
                lease.assert_owned(base)
            if allocator is None and hasattr(self,'overlay'):
                from pynq import allocate
                memories=[m for m in self.overlay.mem_dict.values() if m.get('base_address')==0]
                if len(memories)!=1:
                    raise ValueError('planner requires one explicit PS DDR memory in the sealed HWH')
                memory=self.overlay.device.get_memory(memories[0])
                def allocator(**kwargs):
                    return allocate(target=memory,**kwargs)
            super().__init__(DDRTransport(mmio,registers,allocator,timeout_s,lease,owns_lease))
        except BaseException:
            if owns_lease and lease is not None and not lease.pending:lease.close()
            raise
