"""Dual-template geometry and persistent queue tests; no controller or PL IO."""
import copy
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from calligraphy.presets import BRUSH,binding,validate_task
from calligraphy.library import STROKES
from handwriting.templates import CENTERLINES
from handwriting.recognizer import recognize,points,resample,normalized,dtw,dtw_python
from handwriting.placement import task
from handwriting.planner import compile_stroke,StrokePlan
from handwriting.session import HandwritingSession
from handwriting.executor import BoundaryChanged
from tcb705.config import load,digest
from tcb705.model import Model,ROOT

def config():
    c=load(ROOT/'robots/tcb705/profile.armvision_joint.json')
    c['execution']['sdk']={'enabled':True}
    c['calligraphy']=dict(BRUSH,max_press_mm=4.,verified=True,calibration_binding=binding(c))
    return c

class RecognitionTests(unittest.TestCase):
    def test_independent_templates_and_held_out_shapes(self):
        self.assertEqual(set(CENTERLINES),set(STROKES))
        cases=[('heng',[[.12,.3],[.3,.29],[.62,.31],[.86,.28]]),
               ('shu_chuilu',[[.48,.12],[.49,.35],[.51,.68],[.5,.9]]),
               ('heng_zhe',[[.13,.18],[.4,.17],[.78,.18],[.79,.47],[.77,.84]]),
               ('ti',[[.2,.8],[.45,.53],[.8,.22]]),('dian',[[.4,.4]])]
        for expected,raw in cases:self.assertEqual(recognize(raw)['module'],expected)
    def test_bad_input_and_direction(self):
        for raw in ([],[[float('nan'),.3]],[[True,.3]],[[1.1,.2]],[[.1,.2]]*2049):
            with self.assertRaises(ValueError):points(raw)
        self.assertNotEqual(recognize([[.2,.7],[.7,.2]])['module'],recognize([[.7,.2],[.2,.7]])['module'])
    def test_native_and_python_dtw_match(self):
        a=normalized(resample([[0,0],[.4,.1],[1,1]]));b=normalized(resample([[0,0],[.7,.2],[1,1]]))
        self.assertAlmostEqual(dtw(a,b),dtw_python(a,b),places=12)
    def test_position_size_and_flat_stroke_do_not_erase_brush(self):
        c=config();before=copy.deepcopy(c)
        raw=[[.2,.3],[.8,.3]]
        small=task('heng',raw,40,c);large=task('heng',raw,100,c)
        a=np.array(small['paths'][0]);b=np.array(large['paths'][0])
        self.assertGreater(np.ptp(a[:,1]),.2)
        np.testing.assert_allclose(np.ptp(b,axis=0),np.ptp(a,axis=0)*2.5,atol=3e-6)
        # Sampling density grows with XY size; depth amplitudes do not.
        self.assertAlmostEqual(max(small['calligraphy']['depth_mm'][0]),max(large['calligraphy']['depth_mm'][0]),places=6)
        validate_task(large,c);self.assertEqual(c,before)
        changed=copy.deepcopy(large);changed['paths'][0][2][0]+=.1
        with self.assertRaises(ValueError):validate_task(changed,c)
        for size in (39,101,float('nan')):
            with self.assertRaises(ValueError):task('heng',raw,size,c)

class PlannerTests(unittest.TestCase):
    def test_cpu_only_hover_chain_and_rounded_guards(self):
        c=config();before=copy.deepcopy(c);m=Model(c)
        q=m.from_sdk(c['execution']['web_program']['home']['joint_degrees'])
        raw=[[.2,.3],[.8,.3]];match=recognize(raw)
        with patch('tcb705.accel_runtime.open_accelerator',side_effect=AssertionError('PL accessed')):
            p=compile_stroke(match,raw,60,c,m,q,'ready',lambda:False)
            qnext=compile_stroke(recognize([[.5,.2],[.5,.8]]),[[.5,.2],[.5,.8]],60,c,m,p.q_end,p.fingerprint,lambda:False)
        self.assertEqual(p.metrics['pl_batch_starts'],0)
        self.assertEqual(p.config_digest,digest(c));self.assertEqual(c,before)
        self.assertEqual(qnext.predecessor,p.fingerprint)
        np.testing.assert_array_equal(qnext.q_start,p.q_end)
        self.assertAlmostEqual(p.nodes['positions_m'][-1][2],c['paper']['origin_m'][2]+c['planning']['lift_m'],places=7)
        self.assertIsNone(p.metrics['near_error_mm'])
        # 2026-10-27: knots are merged like brush pages (was ~1 block per 0.25 mm).
        keep=list(p.prepared.keep);count=len(p.nodes['positions_m'])
        self.assertEqual((keep[0],keep[-1]),(0,count-1))
        self.assertTrue(all(b>a for a,b in zip(keep,keep[1:])))
        self.assertLess(len(keep),count/4)
        self.assertEqual(p.metrics['blocks'],len(keep)-1)
        self.assertEqual(p.metrics['collision_probes'],0)

class FakeRobot:
    def __init__(self,c):
        self.model=object();self.prepares=0;self.homes=0;self.executed=[];self.stops=0
        self.q=np.zeros(7);self.hold=threading.Event();self.hold.set();self.boundary=False
    def prepare(self,cancel,note):self.prepares+=1;return self.home(cancel,note)
    def home(self,cancel,note):self.homes+=1;self.q=np.zeros(7);return self.q.copy()
    def execute(self,p,cancel,note):
        if self.boundary:self.boundary=False;raise BoundaryChanged(self.q+.01)
        while not self.hold.wait(.005):
            if cancel():raise ValueError('CANCELLED')
        if cancel():raise ValueError('CANCELLED')
        self.executed.append(p.fingerprint);self.q=p.q_end.copy();return self.q
    def health(self):pass
    def stop(self):self.stops+=1;return True
    def close(self):pass

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.w=SimpleNamespace(machine=config(),simulation=True,state=SimpleNamespace(lock=threading.Lock(),allow_real=False))
        self.bot=FakeRobot(self.w.machine);self.compiles=[];self.compile_hold=threading.Event();self.compile_hold.set()
        def compiler(match,raw,size,c,model,q,pred,cancel):
            while not self.compile_hold.wait(.005):
                if cancel():raise ValueError('CANCELLED')
            if cancel():raise ValueError('CANCELLED')
            fingerprint='p'+str(len(self.compiles));p=StrokePlan({},None,q.copy(),q+.1,digest(c),pred,fingerprint,{'planning_ms':1})
            self.compiles.append(p);return p
        self.session=HandwritingSession(self.w,lambda c:self.bot,compiler)
        self.s=self.session.open({'size_mm':60});self.sid=self.s['session_id'];self.wait(lambda:self.session.phase=='READY')
    def tearDown(self):
        self.compile_hold.set();self.bot.hold.set();self.session.shutdown()
    def data(self,**kw):return dict(session_id=self.sid,**kw)
    def submit(self,i):return self.session.submit(self.data(character=self.session.character,stroke_id='test_%03d'%i,points=[[.2,.3],[.8,.3]]))
    def wait(self,predicate):
        end=time.monotonic()+5
        while not predicate():
            if time.monotonic()>end:self.fail('Timeout: '+str(self.session.snapshot()))
            self.session.heartbeat(self.data());time.sleep(.005)
    def test_planning_overlaps_motion_and_no_per_stroke_home(self):
        self.bot.hold.clear();self.submit(1);self.wait(lambda:self.session.records[0]['status']=='WRITING')
        self.submit(2);self.wait(lambda:len(self.compiles)==2)
        self.assertEqual(self.bot.executed,[]);self.assertEqual(self.compiles[1].predecessor,self.compiles[0].fingerprint)
        np.testing.assert_array_equal(self.compiles[1].q_start,self.compiles[0].q_end)
        self.bot.hold.set();self.wait(lambda:len(self.bot.executed)==2)
        self.assertEqual((self.bot.prepares,self.bot.homes),(1,1))
    def test_duplicate_stop_cancel_and_no_replay(self):
        self.bot.hold.clear();self.submit(1);self.submit(1);self.submit(2)
        self.assertEqual(len(self.session.records),2)
        self.session.stop(self.data());self.wait(lambda:self.session.phase=='STOPPED')
        self.assertEqual(self.bot.executed,[])
        self.submit(1);self.assertEqual(len(self.session.records),2)
        with self.assertRaises(RuntimeError):self.submit(3)
        self.assertTrue(all(r['status']=='CANCELLED' for r in self.session.records))
    def test_next_drains_then_clears_and_applies_size(self):
        self.bot.hold.clear();self.submit(1);self.session.resize(self.data(size_mm=100))
        self.assertEqual(self.session.size,60)
        self.session.next_character(self.data())
        with self.assertRaises(RuntimeError):self.submit(2)
        self.assertEqual(self.session.character,1)
        self.bot.hold.set();self.wait(lambda:self.session.character==2)
        self.assertEqual(self.session.records,[]);self.assertEqual(self.session.size,100)
        self.assertEqual(self.bot.homes,2)
        with self.assertRaises(ValueError):self.session.submit(self.data(character=1,stroke_id='test_001',points=[[.2,.3],[.8,.3]]))
    def test_repeated_stop_keeps_next_character_available(self):
        self.session.stop(self.data());self.wait(lambda:self.session.phase=='STOPPED')
        for _ in range(3):self.session.stop(self.data())
        self.assertEqual(self.session.phase,'STOPPED')
        self.session.next_character(self.data())
        self.wait(lambda:self.session.phase=='READY' and self.session.character==2)
    def test_boundary_change_invalidates_descendants(self):
        self.bot.boundary=True;self.submit(1);self.submit(2)
        self.wait(lambda:len(self.bot.executed)==2)
        self.assertGreaterEqual(len(self.compiles),3)
        self.assertEqual(self.session.records[0]['replans'],1)
    def test_stop_during_planning_and_exclusive_lock(self):
        self.compile_hold.clear();self.submit(1);self.wait(lambda:self.session.records[0]['status']=='PLANNING')
        self.assertFalse(self.w.state.lock.acquire(blocking=False))
        self.session.stop(self.data());self.wait(lambda:self.session.stop_confirmed)
        self.compile_hold.set();self.session.shutdown()
        self.assertTrue(self.w.state.lock.acquire(blocking=False));self.w.state.lock.release()
        self.assertEqual(self.bot.executed,[])
    def test_idle_browser_loss_stops_and_does_not_resume(self):
        self.session.last_heartbeat=time.monotonic()-9
        time.sleep(.1)
        self.assertEqual(self.session.phase,'STOPPED')
        self.session.heartbeat(self.data());self.assertEqual(self.session.phase,'STOPPED')
    def test_browser_loss_during_motion_cancels_before_completion(self):
        self.bot.hold.clear();self.submit(1)
        self.wait(lambda:self.session.records[0]['status']=='WRITING')
        self.session.last_heartbeat=time.monotonic()-9
        time.sleep(.1)
        self.assertEqual(self.session.phase,'STOPPED')
        self.assertEqual(self.bot.executed,[])
    def test_queue_and_point_budgets(self):
        self.compile_hold.clear()
        for i in range(8):self.submit(i)
        with self.assertRaises(RuntimeError):self.submit(9)
        with self.assertRaises(ValueError):self.session.submit(self.data(character=1,stroke_id='bad_001',points=[[.2,.3]]*2049))
    def test_preparation_fault_retains_error_until_stop_confirmed(self):
        self.session.shutdown()
        def fail(cancel,note):
            note('WAIT_FEEDBACK');raise RuntimeError('joint feedback unavailable')
        self.bot.prepare=fail;self.bot.stop=lambda:False;self.bot.stop_detail='clear not confirmed'
        self.session=HandwritingSession(self.w,lambda c:self.bot)
        self.sid=self.session.open({'size_mm':60})['session_id']
        self.wait(lambda:self.session.phase=='FAULT')
        self.session.stop(self.data(),close=True)
        self.assertTrue(self.w.state.lock.locked())
        s=self.session.snapshot()
        self.assertEqual(s['stage'],'WAIT_FEEDBACK')
        self.assertEqual(s['last_error'],'joint feedback unavailable')
        self.assertIn('joint feedback unavailable',s['message'])
        self.bot.stop=lambda:True
        self.wait(lambda:self.session.phase=='CLOSED')
        self.assertFalse(self.w.state.lock.locked())

if __name__=='__main__':unittest.main()
