"""Pen-up transfers must still lift and dwell when strokes almost touch."""
import copy,math,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import planning
from motion import Executor,counts_from_angles,angles_from_counts
from smooth_motion import MotionCurve,align_start
from test_feedback_drawing import machine
from protocol import DemoPort


class SlowPort(DemoPort):
    """Independent unloaded first-order servo response with 350 ms lag."""
    def __init__(self,clock,counts):
        super().__init__();self.clock=clock;self.last=clock[0]
        self.positions.update(counts);self.x={i:float(v) for i,v in self.positions.items()};self.goal=dict(self.x)
    def write(self,packet):
        dt=self.clock[0]-self.last;self.last=self.clock[0];alpha=1-math.exp(-dt/.35)
        for sid in self.x:self.x[sid]+=(self.goal[sid]-self.x[sid])*alpha
        self.positions={i:int(round(v)) for i,v in self.x.items()}
        result=super().write(packet)
        if packet[4]==0x83 and packet[5] in (41,42):
            self.goal.update(self.positions);self.positions={i:int(round(v)) for i,v in self.x.items()}
        return result


class PenTransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=machine();cls.m['trajectory']['lift_m']=.020
        cls.counts=counts_from_angles(cls.m,planning.nominal()[2])
        cls.paths=dict(units='mm',width_mm=100,height_mm=100,paths=[[[48,50],[50,50]],[[50.15,50],[52,50]]])
        cls.tmp=tempfile.TemporaryDirectory()
        cls.result,cls.spec,cls.cfg=planning.build(cls.paths,Path(cls.tmp.name),cls.m,cls.counts,motion_mode='speed_priority')
        if cls.result.status!='OK':raise AssertionError((cls.result.status,cls.result.metrics))
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_nearby_strokes_have_complete_lift_and_fixed_pauses_in_saved_curve(self):
        r=self.result;curve=MotionCurve(r,self.m)
        pauses=[x for x in curve.rows if x.get('endpoint_pause')]
        self.assertEqual(sum(x['phase']=='DRAW' for x in pauses),0)
        self.assertEqual(sum(x['phase']=='LIFT' and x['stroke']>=0 for x in pauses),2)
        for row in pauses:
            if row['phase']=='LIFT':self.assertGreaterEqual(row['duration_s'],.8-1e-10)
            self.assertNotEqual(row['phase'],'DRAW')
            self.assertTrue(np.all(np.asarray(row['coeffs'])[1:]==0))
        phases=[(x['phase'],x['stroke']) for x in curve.rows]
        first_travel=next(i for i,x in enumerate(phases) if x==('TRAVEL',1))
        self.assertEqual(phases[first_travel-1],('LIFT',0))
        self.assertTrue(curve.rows[first_travel-1]['endpoint_pause'])
        self.assertEqual(r.metrics['duration_s'],len(r.commands)*curve.period)
    def test_slow_servos_are_clear_of_paper_before_close_stroke_travel(self):
        m=copy.deepcopy(self.m);m['execution']['feedback_control']={'enabled':False}
        clock=[0.];port=SlowPort(clock,self.counts)
        with patch('smooth_motion.time.monotonic',lambda:clock[0]),patch('smooth_motion.time.sleep',lambda dt:clock.__setitem__(0,clock[0]+dt)):
            result=Executor(port,m).execute(self.result,self.spec['q0'])
        travel=[p for p in result['_tracking_trace'] if p['phase']=='TRAVEL' and p['stroke']==1]
        self.assertTrue(travel)
        origin=np.asarray(self.spec['plane_origin_m']);normal=np.asarray(m['paper']['normal'])
        clearance=[(np.asarray(p['model_tip_m'])-origin)@normal for p in travel]
        self.assertGreater(min(clearance),.015)
        self.assertTrue(result['execution_finished'])
    def test_find_position_and_home_from_paper_lift_first_and_never_draw(self):
        current=dict(self.counts);end=dict(current);end[1]+=30
        result,_,_=planning.build_pen_up_transfer(self.m,current,end)
        self.assertEqual(result.status,'OK',result.metrics)
        curve=MotionCurve(result,self.m);self.assertEqual(curve.rows[0]['phase'],'LIFT')
        self.assertFalse(any(c['pen_down'] for c in result.commands))
        origin=np.asarray(self.m['paper']['origin_m']);normal=np.asarray(self.m['paper']['normal'])
        for c in result.commands:
            if c['phase']=='TRAVEL':
                tip=curve.model.pose(c['q_rad'])[:3,3]
                self.assertGreaterEqual((tip-origin)@normal,.019)
        last=curve.model.pose(result.commands[-1]['q_rad'])[:3,3]
        self.assertGreaterEqual((last-origin)@normal,.019)
    def test_changed_start_joins_with_pen_up_and_preserves_original_drawing(self):
        base=MotionCurve(self.result,self.m);current=dict(self.counts);current[1]+=15
        joined,detail=align_start(base,current);self.assertTrue(detail['applied'])
        self.assertEqual(joined.prefix.rows[0]['phase'],'LIFT')
        cut=detail['replaced_approach_s'];self.assertGreater(cut,0)
        np.testing.assert_allclose(joined.sample(detail['duration_s'])['q_rad'],base.sample(cut)['q_rad'],atol=1e-9)
        for t in (cut+base.period,(cut+base.duration)/2,base.duration):
            np.testing.assert_allclose(joined.sample(detail['duration_s']+t-cut)['q_rad'],base.sample(t)['q_rad'],atol=1e-9)
        tip=base.model.pose(joined.sample(detail['duration_s'])['q_rad'])[:3,3]
        self.assertGreater((tip-np.asarray(self.spec['plane_origin_m']))@np.asarray(self.m['paper']['normal']),.019)


if __name__=='__main__':unittest.main()
