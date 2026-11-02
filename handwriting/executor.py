"""One SDK connection per handwriting session; only the owner thread performs IO."""
import time
import json
from urllib.error import HTTPError
import numpy as np
from tcb705.model import Model, pose_error
from tcb705.config import digest
from tcb705.artifact import nodes_hash
from tcb705.sdk_motion import open_client, SdkMotion, sdk_enabled
from tcb705.web_control import Controller, ControllerError, settle_pose, dist3
from tcb705.web_executor import (settings, home_enabled, go_home, require_home_ready,
    require_mode_switch_clearance, build, Tracker, preparation_key, mapping_required, stop_motion)
from calligraphy.presets import profile
from .planner import StrokePlan

# Live handwriting motion (2026-10-27): queue several SDK moves so the controller can
# blend through gentle vertices inside a stroke; corners sharper than CORNER_DEG,
# pen up/down, stops and stroke ends remain exact stops.  Pages/poems are unchanged.
QUEUE_DEPTH = 4
# 2026-10-29: the value lives in tcb705/blend.py (smooth 4 trial, switchable back with blend.TRIAL).
from tcb705.blend import HANDWRITING_BLEND as BLEND   # air moves exact: a blended approach cut 23.75 mm (10-28)

class BoundaryChanged(RuntimeError):
    def __init__(self,q):
        super().__init__('起始反馈已变化，重新衔接后续笔画');self.q=q

class HandwritingController(Controller):
    """Refresh expired read access once; never replay power or motion requests."""
    def request(self,path,data=None,timeout=None,check=True):
        try:return super().request(path,data,timeout,check)
        except HTTPError as first:
            error=first
            if first.code==401 and data is None and path.split('?')[0] in ('/api/var/byname','/api/log/alarm'):
                first.close();self.login()
                try:return super().request(path,data,timeout,check)
                except HTTPError as second:error=second
            message=''
            try:
                doc=json.loads(error.read(4096).decode('utf-8','replace'))
                if isinstance(doc,dict):
                    message=next((str(doc[k])[:160] for k in ('message','msg','error','desc') if isinstance(doc.get(k),str)),'')
            except Exception:pass
            finally:error.close()
            raise ControllerError('HTTP %s %s %s%s'%(error.code,'GET' if data is None else 'POST',
                path.split('?')[0],(': '+message) if message else '')) from error

class RobotSession:
    def __init__(self,config):
        self.config=config;self.model=Model(config);self.s=settings(config)
        self.ctrl=None;self.sdk=None;self.motion=None;self.last_health=0.
        self.stop_detail=''
    def health(self):
        s=self.sdk.state()
        if not s['link'] or s['move'] not in (0,1) or s['paused'] or self.sdk.alarms():
            raise RuntimeError('控制器断线、暂停或报警，手写已停止')
    def read_q(self):
        q=self.model.from_sdk([float(v) for v in self.sdk.call('JOINTS')])
        if not self.model.legal(q):raise RuntimeError('七轴位置反馈无效或超限')
        return q
    def prepare(self,cancel,note):
        c=self.config
        if not sdk_enabled(c) or not self.s['enabled'] or self.s['mode']!='joint':
            raise ValueError('手写需要已配置的 SDK joint 执行接口')
        if not c['calibration_verified'] or (mapping_required(c) and not c['sdk_mapping_verified']):
            raise ValueError('请先完成纸面与七轴映射标定')
        profile(c,require_verified=True)
        if not home_enabled(c):raise ValueError('手写需要已标定的归位点')
        note('CONNECT')
        # Match the proven drawing path: establish the SDK first, then obtain
        # fresh Web credentials for the enable/readback sequence.
        self.sdk,_=open_client(c)
        note('WAIT_FEEDBACK')
        self.wait_feedback(cancel)
        self.ctrl=HandwritingController(c['controller'],c['robot_id'],timeout=4.)
        note('AUTHENTICATE')
        self.ctrl.login()
        if self.ctrl.axis_count()!=7:raise ValueError('机械臂不是七轴')
        st=self.ctrl.state();alarms=self.ctrl.strict_active_alarms();start=self.ctrl.pose()
        if alarms or st.get('_phc_alarm_') not in ('0','') or st.get('g_state_')!='1':
            raise RuntimeError('机械臂有报警或急停，无法准备')
        self.motion=SdkMotion(self.sdk,self.ctrl,c,queue_depth=QUEUE_DEPTH);self.motion.__enter__()
        if cancel():raise ValueError('CANCELLED')
        if st.get('_phc_ctrlkey')!='100' or st.get('g_servo_statero_') not in ('1','true','True'):
            require_mode_switch_clearance(c,start)
            note('ENABLE_REQUEST')
            self.ctrl.power('auto')
            note('ENABLE_WAIT')
            self.wait_enabled(cancel)
            # Only session entry may switch modes; never between strokes.
            settled=settle_pose(self.ctrl)
            if dist3(start,settled)>self.s['max_power_on_shift_mm']:
                raise RuntimeError('使能时姿态偏移过大')
        require_home_ready(self.ctrl)
        self.motion.set_speed(self.s['draw_speed_pct'])
        note('HOME')
        return self.home(cancel,note)
    def wait_feedback(self,cancel,timeout=6.):
        """SDK link-up precedes its first cyclic robot-state/joint packet."""
        deadline=time.monotonic()+timeout;last='尚未收到七轴反馈'
        while True:
            if cancel():raise ValueError('CANCELLED')
            try:
                state=self.sdk.state()
                if state['link'] and state['move'] in (0,1):
                    q=self.read_q()
                    if state['move']!=0 or state['paused']:raise RuntimeError('控制器正在运动或暂停，请先停止现有任务')
                    return q
                last='SDK 状态尚未就绪（move=%s）'%state['move']
            except RuntimeError as exc:
                # A protocol timeout cannot be safely retried on the untagged
                # line protocol; only a fresh cyclic state may be awaited.
                if 'SDK_TIMEOUT' in str(exc) or 'SERVER_EXITED' in str(exc):raise
                if '正在运动或暂停' in str(exc):raise
                last=str(exc)
            if time.monotonic()>=deadline:raise RuntimeError('SDK_FEEDBACK_NOT_READY: '+last)
            time.sleep(.05)
    def wait_enabled(self,cancel,timeout=8.):
        deadline=time.monotonic()+timeout
        while True:
            if cancel():raise ValueError('CANCELLED')
            state=self.ctrl.state()
            if state.get('_phc_alarm_') not in ('0','') or state.get('g_state_')!='1':
                raise RuntimeError('使能期间控制器报警或急停')
            if state.get('_phc_ctrlkey')=='100' and state.get('g_servo_statero_') in ('1','true','True'):return
            if time.monotonic()>=deadline:raise RuntimeError('ENABLE_TIMEOUT: 控制器未进入已使能的自动模式')
            time.sleep(.1)
    def home(self,cancel,note):
        # The existing strict home sequence lifts vertically before traversing.
        self.s['draw_speed_pct']=self.motion.speed_pct or self.s['draw_speed_pct']
        go_home(self.ctrl,self.config,self.s,lambda kind,**kw:note(kind),cancel,
                time.monotonic,time.sleep,'HANDWRITING_HOME',self.motion,strict=True)
        self.health();return self.read_q()
    def execute(self,plan,cancel,note):
        if (not isinstance(plan,StrokePlan) or plan.config_digest!=digest(self.config) or
                plan.fingerprint!=nodes_hash(plan.nodes) or
                plan.prepared.key!=preparation_key(self.config,plan.nodes,self.model)):
            raise ValueError('手写规划内容或配置已变化')
        q=self.read_q();actual=self.model.fk(q);expected=self.model.fk(plan.q_start)
        if (np.max(np.abs(q-plan.q_start))>np.deg2rad(.15) or
                pose_error(expected,actual)[0]>.0003):
            raise BoundaryChanged(q)
        self.health()
        mm,chunks=build(self.config,plan.nodes,self.s,joint_keep=plan.prepared.keep,brush_blend=BLEND)
        z_floor=float(mm[:,2].min())-self.s['below_paper_mm'];last_node=0
        for chunk in chunks:
            end_index=chunk['node_index'][-1]
            tracker=Tracker([actual[:3,3].__mul__(1000).tolist()]+mm[last_node+1:end_index+1].tolist())
            if cancel():raise ValueError('CANCELLED')
            if not self.motion.start(chunk['content'],cancel):raise ValueError('CANCELLED')
            start=time.monotonic();last_move=start;near_since=None;previous=q
            health_at=start;last_pose=actual
            while True:
                if cancel():raise ValueError('CANCELLED')
                self.motion.pump()
                q=self.read_q();actual=self.model.fk(q);now=time.monotonic()
                xyz=actual[:3,3]*1000;deviation=tracker.update(xyz)
                if xyz[2]<z_floor or deviation>self.s['path_deviation_mm']:
                    raise RuntimeError('机械臂反馈偏离手写轨迹，已请求停止')
                target=actual.copy();target[:3,:3]=self.config['tool_rotation']
                if pose_error(target,actual)[1]>max(.035,self.config['planning']['orientation_tolerance_rad']*2):
                    raise RuntimeError('反馈笔轴偏离竖直姿态')
                if np.max(np.abs(q-previous))>1e-5:last_move=now
                previous=q
                if now-health_at>.5:self.health();health_at=now
                final_q=self.model.from_sdk(plan.nodes['sdk_degrees'][end_index])
                near=(np.linalg.norm(xyz-mm[end_index])<.35 and
                      np.max(np.abs(q-final_q))<np.deg2rad(.2))
                if near and self.motion.idle() and self.sdk.state()['move']==0:
                    if near_since is None:near_since=now
                    if now-near_since>=.08:break
                else:near_since=None
                if now-last_move>self.s['no_progress_s']:raise RuntimeError('机械臂反馈长时间无进展')
                if now-start>120+float(tracker.s[-1]):raise RuntimeError('手写执行超时')
                time.sleep(.008)
            self.motion.finish();last_node=end_index
        # Retire completed callbacks so a long session has bounded memory.
        with self.sdk.cond:
            for seq in self.motion.sent:self.sdk.done.pop(seq,None)
        return q
    def soft_stop(self):
        """The user's stop: decelerate to standstill before clearing (faults use stop())."""
        return self.stop(soft=True)
    def stop(self,soft=False):
        if self.motion is None:return True
        try:
            results=stop_motion(self.motion,soft)
            # A long-lived Web login can expire. STOP is idempotent; refresh
            # only for stop/read confirmation, never replay a movement request.
            web=[r for r in results if not r[0].startswith('sdk_')]
            if not web or any(r[1] is not True for r in web):
                self.ctrl.login();web=self.ctrl.stop()
            if not web or any(r[1] is not True for r in web):
                raise RuntimeError('控制器清队列未确认: '+str(web))
            # An acknowledgement alone is not proof of physical standstill.
            settle_pose(self.ctrl,n=3,interval=.10,timeout=3.)
            sdk_clear=any(r[0]=='sdk_clear_route' and r[1] is True for r in results)
            sdk_stopped=False
            if sdk_clear:
                try:sdk_stopped=self.sdk.state()['move']==0
                except Exception:pass
            if sdk_stopped:
                self.stop_detail='SDK 与控制器清队列成功，位置稳定';return True
            if self.ctrl.state().get('g_servo_statero_') in ('0','false','False'):
                self.stop_detail='控制器已清队列、伺服关闭且位置稳定';return True
            raise RuntimeError('SDK 尚未确认停止，保持机械臂占用')
        except Exception as exc:
            self.stop_detail=str(exc)[:350];return False
    def close(self):
        # Keep the controller's stable mode. Switching to manual while hovering
        # low caused a measured drop in the old implementation.
        if self.motion:self.motion.__exit__(None,None,None)
        if self.sdk:self.sdk.close()

class SimulationSession:
    """Explicit offline mode, never opens the SDK or changes a real controller."""
    def __init__(self,config):self.config=config;self.model=Model(config);self.q=None
    def prepare(self,cancel,note):return self.home(cancel,note)
    def home(self,cancel,note):
        self.q=self.model.from_sdk(settings(self.config)['home']['joint_degrees']);return self.q.copy()
    def execute(self,plan,cancel,note):
        if cancel():raise ValueError('CANCELLED')
        self.q=plan.q_end.copy();return self.q.copy()
    def health(self):pass
    def stop(self):return True
    def close(self):pass
