"""One lazy, exclusively leased PL session per long-running application."""
import os
import threading
import time

class PlanningSession:
    def __init__(self):
        self.core=None;self.reason=None;self.opened=False;self.closed=False
        self.pid=os.getpid();self.lock=threading.Lock();self.attach_s=0.

    def _check(self):
        if self.pid!=os.getpid():raise RuntimeError('Planning session cannot be inherited across fork')
        if self.closed:raise RuntimeError('Planning session is closed')

    def prepare(self):
        with self.lock:
            self._check()
            if not self.opened:
                from .accel_runtime import open_accelerator
                start=time.perf_counter();self.core,self.reason=open_accelerator()
                self.attach_s=time.perf_counter()-start;self.opened=True
            return self.core,self.reason

    def plan(self,paths,config,q_start=None,cancel=lambda:False,progress=None):
        from .accel_runtime import ensure_event_loop
        ensure_event_loop()  # each GUI plan runs in a new worker thread; PYNQ needs a loop there too
        self.prepare()
        from .planner import _plan
        with self.lock:
            self._check()
            core=self.core
            if core is not None and getattr(core.transport,'faulted',False):
                core=None;self.reason='PL session faulted; CPU batches active until maintenance'
            result=_plan(paths,config,q_start,cancel,progress,core)
            result['metrics']['pl_session_attach_s']=self.attach_s
            if self.reason:result['metrics']['ik_accel_unavailable_reason']=self.reason
            return result

    def plan_cpu(self,paths,config,q_start=None,cancel=lambda:False,progress=None):
        """Explicit short-job path: native C++ IK, no PL attach or DMA allocation.

        Shares the same validation and lock as the full planner. The caller must
        still prepare/check the SDK segments and verify the live start state.
        """
        from .planner import _plan
        with self.lock:
            self._check()
            result=_plan(paths,config,q_start,cancel,progress,None)
            result['metrics']['backend_selection']='explicit_cpu'
            result['metrics']['pl_session_attach_s']=0.
            return result

    def close(self):
        with self.lock:
            if self.pid!=os.getpid():raise RuntimeError('Cannot close an inherited planning session')
            if self.closed:return
            # PLChain/DDRTransport retain live DMA through the existing guardian.
            if self.core is not None:self.core.close()
            self.closed=True;self.core=None
