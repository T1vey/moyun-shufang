"""1013-style 64-target prefixes, authoritative seeds and bounded geometry batches."""
import numpy as np
import time

class PlanningCancelled(ValueError):
    """A cancelled batch must never fall through to native CPU planning."""

def _check_cancel(cancel):
    if cancel():raise PlanningCancelled('CANCELLED: 规划取消')

def _same(a,b):
    # np.array_equal without its per-call wrapping; called once per IK target.
    return a.shape==b.shape and bool((a==b).all())

class ChainDispatcher:
    def __init__(self,model,accelerator=None,cancel=lambda:False):
        self.model=model;self.accelerator=accelerator;self.cancel=cancel
        self.hardware=accelerator
        self.rows=[];self.seed=None;self.target=None
        self.batches=0;self.cpu_batches=0;self.accepted=0;self.invalidations=0;self.fallbacks=0
        self.errors=0
        self.cpu_s=0.;self.pl_s=0.
        self.initial=(getattr(getattr(accelerator,'transport',None),'starts',0),getattr(accelerator,'accepted',0),getattr(accelerator,'refused',0))
        self.reason='not configured' if accelerator is None else None
    def invalidate(self):
        if self.rows:self.invalidations+=1
        self.rows=[];self.seed=None
    def next(self,targets,seed):
        if self.cancel():
            self.invalidate()
            raise PlanningCancelled('CANCELLED: 规划取消')
        if self.rows and (not _same(np.asarray(seed),self.seed) or not _same(targets[0],self.target)):
            self.invalidate()
        if not self.rows:
            chunk=np.ascontiguousarray(targets[:64])
            if self.accelerator is not None:
                started=time.perf_counter()
                try:self.rows=self.accelerator.solve_chain(self.model,chunk,seed,self.cancel)
                except PlanningCancelled:
                    self.invalidate()
                    raise
                except Exception as exc:
                    _check_cancel(self.cancel)
                    self.reason=str(exc);self.accelerator=None;self.fallbacks+=1;self.errors+=1
                finally:self.pl_s+=time.perf_counter()-started
            if not self.rows:
                _check_cancel(self.cancel)
                if self.accelerator is not None:
                    self.fallbacks+=1;self.reason='PL returned no legal candidate; native CPU batch used'
                self.cpu_batches+=1
                started=time.perf_counter()
                self.rows=self.model.solve_chain(chunk,seed)
                self.cpu_s+=time.perf_counter()-started
            self.targets=chunk;self.offset=0;self.batches+=1
        if self.cancel():
            self.invalidate()
            raise PlanningCancelled('CANCELLED: 规划取消')
        row=self.rows.pop(0);self.offset+=1;self.seed=row['q'].copy()
        if self.rows:self.target=self.targets[self.offset].copy()
        self.accepted+=1
        return row
    def metrics(self):
        return dict(ik_batches=self.batches,ik_cpu_batches=self.cpu_batches,ik_batch_limit=64,ik_prefix_invalidations=self.invalidations,
            ik_cpu_batch_s=self.cpu_s,ik_pl_batch_s=self.pl_s,
            pl_batch_starts=getattr(getattr(self.hardware,'transport',None),'starts',0)-self.initial[0],
            pl_rows_cpu_verified=0,pl_rows_cpu_rejected=0,
            pl_rows_joint_checked=getattr(self.hardware,'accepted',0)-self.initial[1],pl_rows_joint_rejected=getattr(self.hardware,'refused',0)-self.initial[2],
            pl_runtime_fk_verification=False,
            pl_last_rejection=getattr(self.hardware,'last_rejection',None) if getattr(self.hardware,'refused',0)>self.initial[2] else None,
            ik_accel_fallbacks=self.fallbacks,ik_accel_errors=self.errors,ik_accel_unavailable_reason=self.reason,
            ik_backend='ZYNQ_PL_7R_BATCH' if getattr(self.hardware,'accepted',0)>self.initial[1] else 'ZYNQ_CPU_NATIVE_7R_BATCH')

class PLChain:
    def __init__(self,transport):
        self.transport=transport;self.generation=0
        self.accepted=0;self.refused=0
        self.last_rejection=None
    def close(self):
        if hasattr(self.transport,'close') and not getattr(self.transport,'inflight',False):self.transport.close()
    def solve_chain(self,model,targets,seed,cancel):
        from . import accel_contract as c
        _check_cancel(cancel)
        local=targets if model.base_identity else np.matmul(model.base_inverse,targets)
        if not np.allclose(local[:,:3,:3],local[0,:3,:3],rtol=0,atol=1e-14):raise ValueError('one orientation required per chain')
        ctx=c.context(model,seed,local[0,:3,:3]);inputs=np.zeros(len(local),dtype=c.IK_INPUT)
        inputs['position']=local[:,:3,3];inputs['id']=np.arange(len(local))
        self.generation=self.generation%0xffffffff+1
        h,rows=self.transport.execute(ctx,c.IK_CHAIN,inputs,1,self.generation,cancel)
        if h['status'] not in (0,1,2):raise ValueError('FPGA rejected seven-axis batch: '+str(h['status']))
        # The cancellation header is authoritative even if the callback was a
        # transient request. Returning [] here would silently launch CPU IK.
        if h['status']==2:raise PlanningCancelled('CANCELLED: FPGA 规划取消')
        _check_cancel(cancel)
        if not len(rows):raise ValueError('FPGA returned an empty non-cancelled batch')
        # Runtime pose re-evaluation was explicitly removed. Keep the contract,
        # finite joints, original limits and continuity before accepting a row.
        # PARTIAL includes the first failed row; only its successful prefix is
        # usable. Never broadcast a short completion over the full target batch.
        q=np.array(rows['q'],dtype=np.float64)
        steps=np.max(np.abs(np.diff(np.vstack((np.asarray(seed),q)),axis=0)),axis=1)
        good=((rows['status']==0)&np.isfinite(q).all(axis=1)
              &np.all(q>=model.lower,axis=1)&np.all(q<=model.upper,axis=1)
              &(steps<=model.config['ik']['step_limit_rad']))
        _check_cancel(cancel)
        count=len(rows) if good.all() else int(np.argmin(good))
        stats=rows['stats']
        result=[dict(ok=True,status=0,q=q[i].copy(),iterations=int(stats[i,2]),
                     position_error_m=None,orientation_error_rad=None,geometry_verified=False) for i in range(count)]
        self.accepted+=count
        if count<len(rows):
            i=count;self.refused+=1
            residual_evaluated=not (h.get('capabilities',0)&c.CAP_RESIDUAL_NOT_EVALUATED)
            self.last_rejection=dict(row=i,status=int(rows['status'][i]),iterations=int(stats[i,2]),
                position_error_m=None,orientation_error_rad=None,geometry_verified=False,
                joint_step_rad=float(steps[i]) if np.isfinite(steps[i]) else None,
                pl_position_error_m=float(stats[i,0]) if residual_evaluated and np.isfinite(stats[i,0]) else None,
                pl_orientation_error_rad=float(stats[i,1]) if residual_evaluated and np.isfinite(stats[i,1]) else None)
        return result
