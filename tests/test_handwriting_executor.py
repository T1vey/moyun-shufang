"""Executor completion and rejection gates with fake transport; no hardware IO."""
import copy,threading,unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from test_handwriting import config
from handwriting.recognizer import recognize
from handwriting.planner import compile_stroke
from handwriting.executor import RobotSession,BoundaryChanged
from tcb705.model import Model

class Clock:
    def __init__(self):self.now=0
    def monotonic(self):self.now+=.01;return self.now
    def sleep(self,n):self.now+=n

class ExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=config();cls.m=Model(cls.c)
        q=cls.m.from_sdk(cls.c['execution']['web_program']['home']['joint_degrees'])
        raw=[[.2,.3],[.8,.3]]
        cls.p=compile_stroke(recognize(raw),raw,60,cls.c,cls.m,q,'home',lambda:False)
    def make(self,advance):
        bot=RobotSession(self.c);clock=Clock();bot.s['no_progress_s']=.4
        counter={'reads':0,'states':0,'finishes':0,'starts':0}
        rows=self.m.from_sdk_batch(self.p.nodes['sdk_degrees'])
        def read():
            i=counter['reads'];counter['reads']+=1
            return rows[min(i,len(rows)-1)].copy() if advance else self.p.q_start.copy()
        def state():
            counter['states']+=1
            return dict(link=True,paused=False,move=1 if counter['states']<4 else 0)
        bot.read_q=read
        bot.sdk=SimpleNamespace(state=state,alarms=lambda:[],cond=threading.Condition(),done={})
        bot.motion=SimpleNamespace(start=lambda *a:counter.update(starts=counter['starts']+1) or True,
            pump=lambda:None,idle=lambda:True,finish=lambda:counter.update(finishes=counter['finishes']+1),sent=[])
        return bot,clock,counter
    def test_callback_alone_does_not_mean_physical_completion(self):
        bot,clock,counter=self.make(False)
        with patch('handwriting.executor.time',clock):
            with self.assertRaisesRegex(RuntimeError,'无进展'):bot.execute(self.p,lambda:False,lambda *a:None)
        self.assertEqual(counter['finishes'],0)
    def test_waits_for_pose_and_idle_then_completes(self):
        bot,clock,counter=self.make(True)
        # Actual points follow the tested dense path. Path-progress tracking is
        # tested separately; focus this test on end feedback versus SDK callback.
        with patch('handwriting.executor.time',clock),patch('handwriting.executor.Tracker') as tracker:
            tracker.return_value.update.return_value=0
            tracker.return_value.s=np.array([0,200])
            q=bot.execute(self.p,lambda:False,lambda *a:None)
        np.testing.assert_allclose(q,self.p.q_end)
        self.assertGreaterEqual(counter['states'],4);self.assertEqual(counter['finishes'],1)
    def test_changed_boundary_replans_before_any_move(self):
        bot,_,counter=self.make(False);bot.read_q=lambda:self.p.q_start+.01
        with self.assertRaises(BoundaryChanged):bot.execute(self.p,lambda:False,lambda *a:None)
        self.assertEqual(counter['starts'],0)
    def test_mutated_target_rejected_before_any_move(self):
        bot,_,counter=self.make(False);p=copy.deepcopy(self.p);p.nodes['sdk_degrees'][1][0]+=.01
        with self.assertRaisesRegex(ValueError,'已变化'):bot.execute(p,lambda:False,lambda *a:None)
        self.assertEqual(counter['starts'],0)
    def test_stop_ack_without_standstill_is_not_confirmed(self):
        bot,_,_=self.make(False);bot.motion.stop=lambda:[('clear',True,'')];bot.ctrl=object()
        with patch('handwriting.executor.settle_pose',return_value=[0,0,0]):self.assertFalse(bot.stop())
    def test_feedback_waits_for_first_valid_joint_packet(self):
        bot=RobotSession(self.c);clock=Clock();states=iter([-1,-1,0,0]);reads=iter([RuntimeError('joint feedback unavailable'),np.zeros(7)])
        bot.sdk=SimpleNamespace(state=lambda:dict(link=True,move=next(states),paused=False))
        def read():
            value=next(reads)
            if isinstance(value,Exception):raise value
            return value
        bot.read_q=read
        with patch('handwriting.executor.time',clock):np.testing.assert_array_equal(bot.wait_feedback(lambda:False),np.zeros(7))
    def test_feedback_protocol_timeout_is_not_retried(self):
        bot=RobotSession(self.c);calls=[]
        def state():calls.append(1);raise RuntimeError('SDK_TIMEOUT')
        bot.sdk=SimpleNamespace(state=state)
        with self.assertRaisesRegex(RuntimeError,'SDK_TIMEOUT'):bot.wait_feedback(lambda:False)
        self.assertEqual(len(calls),1)
    def test_waits_for_servo_enable_confirmation(self):
        bot=RobotSession(self.c);clock=Clock();states=iter(['0','0','1'])
        bot.ctrl=SimpleNamespace(state=lambda:dict(_phc_alarm_='0',g_state_='1',_phc_ctrlkey='100',g_servo_statero_=next(states)))
        with patch('handwriting.executor.time',clock):bot.wait_enabled(lambda:False)
        self.assertGreaterEqual(clock.now,.2)
    def test_stop_refreshes_expired_web_login_and_checks_standstill(self):
        bot=RobotSession(self.c);events=[]
        bot.motion=SimpleNamespace(stop=lambda:[('sdk_clear_route',False,''),('clear',False,'expired')])
        bot.ctrl=SimpleNamespace(login=lambda:events.append('login'),stop=lambda:[('clear',True,''),('run_key',True,'')],state=lambda:{'g_servo_statero_':'0'})
        with patch('handwriting.executor.settle_pose',return_value=[0,0,0]) as settled:
            self.assertTrue(bot.stop());settled.assert_called_once()
        self.assertEqual(events,['login'])
    def test_sdk_ack_then_feedback_failure_needs_servo_off(self):
        bot=RobotSession(self.c)
        bot.motion=SimpleNamespace(stop=lambda:[('sdk_clear_route',True,''),('clear',True,''),('run_key',True,'')])
        def unavailable():raise RuntimeError('SDK_TIMEOUT')
        bot.sdk=SimpleNamespace(state=unavailable)
        bot.ctrl=SimpleNamespace(state=lambda:{'g_servo_statero_':'1'})
        with patch('handwriting.executor.settle_pose',return_value=[0,0,0]):
            self.assertFalse(bot.stop())
            bot.ctrl.state=lambda:{'g_servo_statero_':'0'}
            self.assertTrue(bot.stop())

if __name__=='__main__':unittest.main()
