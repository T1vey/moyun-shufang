"""Bounded ordered pipeline: one planning worker and one exclusive robot owner.

Requests only enqueue work. No HTTP handler waits for IK, homing or physical
completion. Generation changes discard speculative plans, never replay motion.
"""
import copy
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from .recognizer import points, recognize, resample, bank_arrays, native
from .planner import compile_stroke
from .executor import RobotSession, SimulationSession, BoundaryChanged

TERMINAL={'DONE','CANCELLED','FAILED'}
LOG=logging.getLogger(__name__)

class HandwritingSession:
    def __init__(self,workbench,adapter_factory=None,compiler=compile_stroke):
        self.workbench=workbench;self.factory=adapter_factory;self.compiler=compiler
        self.cv=threading.Condition(threading.RLock());self.cancel=threading.Event()
        self.phase='CLOSED';self.session_id=None;self.character=1;self.records=[];self.plans={}
        self.message='进入后自动准备';self.revision=0;self.generation=0;self.worker=None;self.planner=None
        self.size=60.;self.pending_size=60.;self.closing=False;self.next_requested=False
        self.stop_confirmed=False;self.last_heartbeat=0.;self.adapter=None;self.owns_lock=False
        self.tail_q=None;self.tail_tag=None;self.executed_tag=None
        self.last_error='';self.stage='';self.stop_detail=''
    def _changed(self):self.revision+=1;self.cv.notify_all()
    def _cancelled(self):
        # Also checked inside long prepare/home/execute operations, not just
        # between strokes. Browser loss must stop an in-flight stroke too.
        with self.cv:
            if time.monotonic()-self.last_heartbeat>8 and not self.cancel.is_set():
                self.message='手写界面连接中断，已停止并取消排队'
                self.cancel.set();self.phase='STOPPING';self._changed()
            return self.cancel.is_set()
    def snapshot(self,since=None):
        with self.cv:
            speed=self.workbench.machine['execution']['web_program']['draw_speed_pct']
            base=dict(session_id=self.session_id,phase=self.phase,character=self.character,
                size_mm=self.size,pending_size_mm=self.pending_size,speed_pct=speed,
                message=self.message,revision=self.revision,simulation=self.workbench.simulation,
                stop_confirmed=self.stop_confirmed,backend='CPU_NATIVE',
                next_requested=self.next_requested,max_pending=8)
            base.update(last_error=self.last_error,stage=self.stage,stop_detail=self.stop_detail)
            if since==self.revision:return dict(base,unchanged=True)
            base['strokes']=[{k:copy.deepcopy(v) for k,v in r.items() if k not in ('raw','payload_hash','received_at')}
                             for r in self.records]
            return base
    def _check(self,data):
        if data.get('session_id')!=self.session_id or not self.session_id:
            raise ValueError('手写会话已变化，请刷新界面')
    def open(self,data):
        from calligraphy.presets import number,profile
        size=number(data.get('size_mm',60),40,100,'整字大小')
        with self.cv:
            if self.phase!='CLOSED':return self.snapshot()
            if not self.workbench.simulation and not self.workbench.state.allow_real:
                raise ValueError('实机服务未开启 --allow-real')
            config=copy.deepcopy(self.workbench.machine)
            if size+4>min(config['paper']['width_mm'],config['paper']['height_mm']):
                raise ValueError('字号超出已标定纸面')
            if not self.workbench.simulation:profile(config,require_verified=True)
            if not self.workbench.state.lock.acquire(blocking=False):
                raise RuntimeError('另一项绘画或标定任务正在进行，请结束后进入手写')
            self.owns_lock=True;self.config=config;self.size=self.pending_size=size
            self.session_id=uuid.uuid4().hex;self.character=1;self.records=[];self.plans={}
            self.cancel.clear();self.closing=False;self.next_requested=False;self.stop_confirmed=False
            self.planner=None;self.adapter=None
            self.last_error='';self.stage='';self.stop_detail=''
            self.phase='PREPARING';self.message='正在连接、使能并归位';self.last_heartbeat=time.monotonic()
            self.generation+=1;self._changed()
            self.worker=threading.Thread(target=self._execute_loop,name='handwriting-execution',daemon=True)
            self.worker.start();return self.snapshot()
    def heartbeat(self,data):
        with self.cv:
            self._check(data);self.last_heartbeat=time.monotonic()
            return self.snapshot(data.get('revision'))
    def submit(self,data):
        raw=points(data.get('points')).tolist()
        rid=data.get('stroke_id')
        if not isinstance(rid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{6,64}',rid):raise ValueError('无效笔画编号')
        payload=hashlib.sha256(json.dumps(raw,separators=(',',':')).encode()).hexdigest()
        with self.cv:
            self._check(data)
            if data.get('character')!=self.character:raise ValueError('本字已结束，旧笔画不能重新下发')
            for r in self.records:
                if r['id']==rid:
                    if r['payload_hash']!=payload:raise ValueError('同一笔画编号对应不同内容')
                    return self.snapshot()
            if self.phase not in ('READY','WRITING') or self.cancel.is_set() or self.next_requested:
                raise RuntimeError('当前不能接收新笔画：'+self.message)
            if len(self.records)>=64:raise RuntimeError('本字最多 64 笔，请点击下一个字')
            if sum(r['status'] not in TERMINAL for r in self.records)>=8:
                raise RuntimeError('队列已有 8 笔，请等待机械臂书写')
            self.records.append(dict(id=rid,number=len(self.records)+1,status='ACCEPTED',raw=raw,
                points=resample(raw,min(len(raw),128)).tolist(),payload_hash=payload,
                received_at=time.monotonic(),replans=0))
            self.last_heartbeat=time.monotonic();self._changed();return self.snapshot()
    def resize(self,data):
        from calligraphy.presets import number
        size=number(data.get('size_mm'),40,100,'整字大小')
        with self.cv:
            self._check(data)
            if size+4>min(self.config['paper']['width_mm'],self.config['paper']['height_mm']):
                raise ValueError('字号超出已标定纸面')
            self.pending_size=size
            if not self.records:self.size=size
            self._changed();return self.snapshot()
    def next_character(self,data):
        with self.cv:
            self._check(data)
            if data.get('character',self.character)!=self.character:raise ValueError('此字已经结束')
            if self.phase not in ('READY','WRITING','DRAINING','STOPPED') or self.closing:
                raise RuntimeError('请先完成准备或处理故障')
            if self.planner is None:
                raise RuntimeError('准备未完成，请返回后重新进入手写模式')
            self.next_requested=True
            if self.phase!='STOPPED':self.phase='DRAINING'
            self.message='完成已接收笔画后归位，准备下一个字';self._changed();return self.snapshot()
    def stop(self,data=None,close=False):
        with self.cv:
            if data is not None:self._check(data)
            if self.phase=='CLOSED':return self.snapshot()
            self.closing=self.closing or close;self.cancel.set();self.next_requested=False
            if self.stop_confirmed:
                # Repeated taps are idempotent: do not turn a confirmed stop
                # back into STOPPING, which would disable the next-character action.
                self._changed();return self.snapshot()
            if self.phase!='FAULT':self.phase='STOPPING'
            self.message=(self.last_error+'；正在确认停止' if self.last_error else '正在停止，取消尚未执行的笔画')
            self._changed();return self.snapshot()
    def _note(self,stage):
        labels={'CONNECT':'正在连接控制器','WAIT_FEEDBACK':'等待七轴位置反馈',
                'AUTHENTICATE':'正在登录控制器','ENABLE_REQUEST':'正在请求使能',
                'ENABLE_WAIT':'等待伺服使能确认','HOME':'正在归位'}
        with self.cv:
            self.stage=stage
            if self.phase=='PREPARING' and not self.cancel.is_set():
                self.message=labels.get(stage,'正在准备：'+stage);self._changed()
    def _fault(self,error):
        with self.cv:
            self.last_error=str(error)[:300]
            LOG.error('HANDWRITING_FAULT stage=%s error=%s',self.stage,self.last_error)
            self.phase='FAULT';self.message=self.last_error;self.cancel.set();self.next_requested=False
            self._changed()
    def _stopped(self,confirmed,preparing=False):
        """Keep the original failure visible while retaining unconfirmed ownership."""
        self.stop_confirmed=confirmed
        self.stop_detail=getattr(self.adapter,'stop_detail','')
        if not confirmed:
            self.phase='FAULT'
            self.message=(self.last_error+'；' if self.last_error else '')+'停止未确认，仍占用机械臂；可返回查看其他模式'
        elif self.last_error:
            self.phase='FAULT';self.message=self.last_error+'；已停止，可返回后重新进入'
        else:
            self.phase='STOPPED'
            self.message='准备已停止，请返回后重新进入' if preparing else '已停止，笔迹保留；点击下一个字可重新准备'
    def _plan_loop(self):
        while True:
            with self.cv:
                if self.closing:return
                if self.cancel.is_set():self.cv.wait(.05);continue
                record=next((r for r in self.records if r['status']=='ACCEPTED'),None)
                if record is None:self.cv.wait(.05);continue
                record['status']='PLANNING';generation=self.generation
                q=self.tail_q.copy();predecessor=self.tail_tag;size=self.size
                self._changed()
            cancelled=lambda:self._cancelled() or self.generation!=generation or self.closing
            try:
                begin=time.perf_counter();match=recognize(record['raw'])
                recognition_ms=(time.perf_counter()-begin)*1000
                plan=self.compiler(match,record['raw'],size,self.config,self.adapter.model,q,predecessor,cancelled)
                with self.cv:
                    if cancelled():continue
                    record.update(status='READY',match=match,metrics=dict(plan.metrics,recognition_ms=round(recognition_ms,2)))
                    record['metrics']['ready_after_receipt_ms']=round((time.monotonic()-record['received_at'])*1000,2)
                    self.plans[record['id']]=plan;self.tail_q=plan.q_end.copy();self.tail_tag=plan.fingerprint
                    self._changed()
            except Exception as exc:
                with self.cv:
                    if cancelled():continue
                    record.update(status='FAILED',error=str(exc)[:300]);self._fault(exc)
    def _seed(self,q):
        self.tail_q=q.copy();self.tail_tag=hashlib.sha256(q.tobytes()).hexdigest();self.executed_tag=self.tail_tag
    def _execute_loop(self):
        try:
            factory=self.factory or (SimulationSession if self.workbench.simulation else RobotSession)
            self.adapter=factory(self.config);bank_arrays();native()
            q=self.adapter.prepare(self._cancelled,self._note)
            with self.cv:
                self._seed(q)
                if self.cancel.is_set():raise ValueError('准备已取消')
                self.planner=threading.Thread(target=self._plan_loop,name='handwriting-plan',daemon=True)
                self.phase='READY';self.message='悬停等待，在字框内写一笔即可';self._changed()
            self.planner.start();health_at=time.monotonic()
            while True:
                with self.cv:
                    if time.monotonic()-self.last_heartbeat>8 and not self.cancel.is_set():
                        self.message='手写界面连接中断，已停止并取消排队';self.cancel.set();self.phase='STOPPING'
                    cancelled=self.cancel.is_set()
                if cancelled:
                    if not self.stop_confirmed:
                        # User stop or lost screen: decelerated stop where the adapter supports it.
                        confirmed=getattr(self.adapter,'soft_stop',self.adapter.stop)()
                        with self.cv:
                            self.generation+=1;self.plans.clear()
                            for r in self.records:
                                if r['status'] not in TERMINAL:r['status']='CANCELLED'
                            self._stopped(confirmed)
                            self._changed()
                        if not confirmed:
                            # Bounded retry of STOP only; never retry a MOVE.
                            time.sleep(.5)
                    if self.closing and self.stop_confirmed:break
                    if self.next_requested and self.stop_confirmed and self.phase=='STOPPED':
                        with self.cv:self.cancel.clear();self.stop_confirmed=False
                    else:
                        with self.cv:self.cv.wait(.05)
                        continue
                with self.cv:
                    record=next((r for r in self.records if r['status'] not in TERMINAL),None)
                    reset=self.next_requested and record is None
                    if record is not None and record['status']=='READY':
                        plan=self.plans[record['id']]
                        if plan.predecessor!=self.executed_tag:raise RuntimeError('笔画队列起点链已变化')
                        record['status']='WRITING';self.phase='WRITING';self.message='正在书写第 %d 笔'%record['number'];self._changed()
                    else:plan=None
                if reset:
                    with self.cv:self.phase='HOMING';self.message='正在归位，准备下一个字';self._changed()
                    q=self.adapter.home(self._cancelled,lambda stage:None)
                    with self.cv:
                        if self.cancel.is_set():continue
                        self.generation+=1;self._seed(q);self.records=[];self.plans={};self.character+=1
                        self.size=self.pending_size;self.next_requested=False;self.phase='READY'
                        self.message='准备完成，请在空白纸面区域书写';self._changed()
                    continue
                if plan is None:
                    if time.monotonic()-health_at>1:
                        self.adapter.health();health_at=time.monotonic()
                    with self.cv:self.cv.wait(.03)
                    continue
                try:
                    with self.cv:record['metrics']['executor_start_after_receipt_ms']=round((time.monotonic()-record['received_at'])*1000,2)
                    self.adapter.execute(plan,self._cancelled,lambda stage:None)
                    with self.cv:
                        if self.cancel.is_set():continue
                        record['status']='DONE';self.plans.pop(record['id'],None);self.executed_tag=plan.fingerprint
                        self.phase='DRAINING' if self.next_requested else 'READY'
                        self.message='本笔完成，竖直抬笔悬停等待';self._changed()
                except BoundaryChanged as exc:
                    with self.cv:
                        record['replans']+=1
                        if record['replans']>2:raise RuntimeError('起始反馈持续变化，请检查机械臂是否停稳')
                        self.generation+=1;self._seed(exc.q);self.plans.clear()
                        for r in self.records:
                            if r['status'] not in TERMINAL:r['status']='ACCEPTED'
                        self.phase='READY';self.message='根据实际悬停姿态重新衔接后续笔画';self._changed()
                except Exception as exc:
                    if not self.cancel.is_set():
                        with self.cv:record.update(status='FAILED',error=str(exc)[:300])
                        self._fault(exc)
        except Exception as exc:
            if not self.cancel.is_set():self._fault(exc)
            # Preparation/idle failure still needs a live owner to receive close.
            while True:
                confirmed=self.stop_confirmed or (self.adapter.stop() if self.adapter else True)
                with self.cv:
                    before=(self.phase,self.message,self.stop_confirmed,self.stop_detail)
                    self._stopped(confirmed,preparing=True)
                    for r in self.records:
                        if r['status'] not in TERMINAL:r['status']='CANCELLED'
                    self.plans.clear()
                    if before!=(self.phase,self.message,self.stop_confirmed,self.stop_detail):self._changed()
                    if self.closing and confirmed:break
                    self.cv.wait(.5)
        finally:
            with self.cv:self.closing=True;self.cancel.set();self._changed()
            if self.planner:self.planner.join()
            try:
                if self.adapter:self.adapter.close()
            finally:
                with self.cv:
                    if self.owns_lock:self.workbench.state.lock.release();self.owns_lock=False
                    self.phase='CLOSED';self.message='手写会话已结束';self._changed()
    def shutdown(self):
        self.stop(close=True)
        if self.worker:self.worker.join()
