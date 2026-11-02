"""Independent lag/bias plant and read-only manual pen calibration acceptance."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import planning
from feedback_control import JointFeedbackController,PenPhaseCoordinator
from pen_calibration import calibrate_pen
from motion import Executor,angles_from_counts,counts_from_angles
from protocol import DemoPort
from smooth_motion import joint_move
from workbench import Workbench
from vision import preset


def machine():
    m=json.loads((ROOT/'config/machine.example.json').read_text(encoding='utf-8'))
    for j in m['joints']:j.update(zero_count=2048,min_count=100,max_count=3900)
    m['checks']=dict(limits=True,kinematics=True,single_joint=True)
    _,paper,_=planning.nominal();m['paper']=paper
    m['execution']=dict(buffered_audit=False,settle_timeout_s=.5)
    return m


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.m=machine();self.nominal={i:2048 for i in range(1,6)}
    def test_independent_first_order_bias_plant_converges(self):
        c=JointFeedbackController(self.m,.05)
        x=np.full(5,2048.);goal=x.copy();bias=np.array([0,24,-18,8,0.])
        errors=[]
        for k in range(200):
            x += (goal-bias-x)*(1-math.exp(-.05/.12))
            if k%2==0:c.observe(self.nominal,{i+1:int(round(x[i])) for i in range(5)},k*.05)
            target,_=c.target(self.nominal,k*.05)
            goal=np.array(list(target.values()))
            errors.append(abs(x-2048))
        self.assertLess(np.max(errors[-20:]),3.)
        self.assertGreater(c.summary()['max_correction_counts'][2],20.)
    def test_stuck_joint_is_bounded_and_never_raises(self):
        c=JointFeedbackController(self.m,.05)
        measured=dict(self.nominal);measured[4]-=300
        targets=[]
        for k in range(500):
            c.observe(self.nominal,measured,k*.05)
            t,_=c.target(self.nominal,k*.05);targets.append(t[4])
        self.assertLessEqual(max(targets)-2048,32)
        self.assertTrue(all(abs(b-a)<=2 for a,b in zip(targets,targets[1:])))
        self.assertLessEqual(abs(c.integral[3]),32.)
        self.assertGreater(c.saturated_samples,0)
    def test_recorded_large_bias_can_be_corrected_with_bounded_64_count_profile(self):
        c=JointFeedbackController(self.m,.05,dict(max_correction_counts=64.,max_correction_rate_counts_s=80.,filter_s=.08))
        x=np.full(5,2048.);goal=x.copy();bias=np.array([0,48,-46,8,0.])
        for k in range(300):
            x+=(goal-bias-x)*(1-math.exp(-.05/.18))
            if k%2==0:c.observe(self.nominal,{i+1:int(round(x[i])) for i in range(5)},k*.05)
            target,_=c.target(self.nominal,k*.05);goal=np.array(list(target.values()))
        self.assertLess(np.max(abs(x-2048)),3.)
        self.assertLessEqual(max(c.summary()['max_correction_counts'].values()),64.)
    def test_missing_feedback_decays_and_does_not_integrate_unobserved_time(self):
        c=JointFeedbackController(self.m,.05);measured={i:2010 for i in self.nominal}
        for k in range(20):c.observe(self.nominal,measured,k*.05);c.target(self.nominal,k*.05)
        before=c.integral.copy()
        for k in range(20,100):target,_=c.target(self.nominal,k*.05)
        self.assertEqual(target,self.nominal)
        c.observe(self.nominal,measured,5.)
        np.testing.assert_allclose(c.integral,before)
    def test_count_bounds_clip_correction_without_aborting(self):
        c=JointFeedbackController(self.m,.05)
        nominal={i:3899 for i in self.nominal};measured={i:3800 for i in self.nominal}
        for k in range(30):c.observe(nominal,measured,k*.05);target,_=c.target(nominal,k*.05)
        self.assertEqual(set(target.values()),{3900});self.assertGreater(c.count_clips,0)
    def test_disabled_controller_preserves_reference(self):
        c=JointFeedbackController(self.m,.05,{'enabled':False})
        c.observe(self.nominal,{i:0 for i in self.nominal},0.)
        self.assertEqual(c.target(self.nominal,1.)[0],self.nominal)


class PenCalibrationTests(unittest.TestCase):
    def test_vertical_pose_corrects_arbitrary_installed_axis_not_fixed_id4(self):
        m=machine();counts={1:1988,2:1689,3:2476,4:3066,5:1912}
        old=copy.deepcopy(m)
        updated,detail=calibrate_pen(m,counts,'axis')
        model=planning.Model(updated['model']);q=angles_from_counts(updated,counts)
        np.testing.assert_allclose(model.pose(q)[:3,:3]@model.tool_axis,[0,0,-1],atol=1e-12)
        self.assertEqual(m,old);self.assertEqual(updated['joints'],old['joints'])
        self.assertEqual(updated['model']['tool_translation_m'],old['model']['tool_translation_m'])
        self.assertNotEqual(updated['model']['tool_axis_local'],old['model']['tool_axis_local'])
        self.assertNotIn('fixed_id4',detail)
    def test_contact_height_preserves_plane_xy_and_lift(self):
        m=machine();m['paper']['draw_height_offset_m']=.005
        counts=counts_from_angles(m,planning.nominal()[2]);origin=np.array(m['paper']['origin_m'])
        updated,detail=calibrate_pen(m,counts,'contact_height')
        target=planning.Model(m['model']).pose(angles_from_counts(m,counts))[:3,3]
        n=np.array(m['paper']['normal']);new=np.array(updated['paper']['origin_m'])
        self.assertAlmostEqual(float((target-new)@n),0.,places=12)
        np.testing.assert_allclose(np.cross(new-origin,n),0.,atol=1e-12)
        self.assertEqual(updated['paper']['draw_height_offset_m'],0.)
        self.assertEqual(updated['trajectory'],m['trajectory'])
    def test_pc_reader_emits_only_ping_and_read_packets(self):
        import pc_pen_calibration
        p=DemoPort();p.open=lambda:None
        p.close=lambda:None
        with patch('serial.Serial',return_value=p),patch('pc_pen_calibration.time.sleep',lambda _:None):
            result=pc_pen_calibration.read_pose('COM7',machine())
        self.assertEqual(len(result['counts']),5)
        self.assertEqual(set(packet[4] for packet in p.writes),{1,2})
        self.assertFalse(any(packet[2]==254 for packet in p.writes))
    def test_calibration_worker_reads_without_torque_or_motion_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            from app import State
            p=DemoPort()
            state=State(Path(temp),allow_real=True,real_factory=lambda *_:p)
            w=Workbench(state,allow_motion=True);w.configure(machine())
            job=w.start('calibrate_pen',dict(mode='real',kind='axis',port='/dev/ttyACM0',baudrate=1000000,
                                            confirmed=True,pose_confirmed=True))
            w.worker.join(3)
            self.assertEqual(w.jobs[job['id']]['status'],'DONE')
            self.assertTrue(all(packet[4] in (1,2) for packet in p.writes))
            self.assertIn('pen_axis_calibration',w.machine['model'])
    def test_pc_encoder_plan_uses_no_board_serial_and_keeps_real_provenance(self):
        from app import State
        with tempfile.TemporaryDirectory() as temp:
            def forbidden(*args):raise AssertionError('PC planning must not open a board motor port')
            state=State(Path(temp),allow_real=True,real_factory=forbidden)
            w=Workbench(state,allow_motion=True);m=machine();w.configure(m)
            paths=preset('line',Path(temp)/'input',10,10)
            image=w.start('strokes',dict(paths=paths));w.worker.join(3)
            self.assertEqual(w.jobs[image['id']]['status'],'DONE')
            counts=counts_from_angles(m,planning.nominal()[2])
            job=w.start('plan',dict(mode='real',image_job=image['id'],port='/dev/ttyACM0',baudrate=1000000,
                confirmed=True,start_counts={str(k):v for k,v in counts.items()},counts_source='PC_encoder_COM7'))
            w.worker.join(5)
            self.assertEqual(w.jobs[job['id']]['status'],'DONE',w.jobs[job['id']].get('detail'))
            self.assertEqual(w.jobs[job['id']]['result']['metrics']['start_counts_source'],'PC_encoder_COM7')
            np.testing.assert_allclose(w.plans[job['id']]['q0'],angles_from_counts(m,counts))


class FeedbackPreviewTests(unittest.TestCase):
    def test_preview_projects_measured_positions_and_never_fills_missing_ink(self):
        from drawing_prediction import feedback_preview
        paths=dict(units='mm',width_mm=10,height_mm=10,paths=[[[0,0],[5,0],[10,0]]])
        data=dict(paths=paths,machine=machine(),drawing={'plane_origin_m':[0,0,0]})
        trace=dict(points=[dict(phase='DRAW',stroke=0,source_segment_id=[0,0],model_tip_m=[-.004,-.005,0],elapsed_s=.1,tip_error_m=.001,pen_axis_error_deg=2),
            dict(phase='DRAW',stroke=0,source_segment_id=[0,0],model_tip_m=[0.,-.005,0],elapsed_s=.2,tip_error_m=.001,pen_axis_error_deg=2)])
        preview=feedback_preview(data,trace)
        self.assertEqual(preview['mode'],'feedback')
        np.testing.assert_allclose(preview['rows'][0]['predicted_points_mm'],[[1,0],[5,0]])
        self.assertIsNone(preview['rows'][1]['predicted_points_mm'])
        self.assertEqual(preview['unrepresented_segments'],1)


class PhaseTests(unittest.TestCase):
    def test_refinement_is_finite_and_skips_mid_draw(self):
        curve=SimpleNamespace(period=.05,duration=2.,stops=[.5,1.,1.5,2.])
        def sample(t):
            return dict(phase='LOWER' if t<=.5 else ('DRAW' if t<=1. else ('LIFT' if t<=1.5 else 'TRAVEL')),stroke=0)
        curve.sample=sample;c=PenPhaseCoordinator(curve)
        target={1:2000};bad={1:1900}
        self.assertFalse(c.refine(.3,target,bad,True,.05))
        self.assertEqual(sum(c.refine(.5,target,bad,False,.05) for _ in range(20)),6)
        self.assertFalse(c.refine(1.,target,bad,False,.05))
        self.assertEqual(sum(c.refine(1.5,target,bad,True,.05) for _ in range(20)),6)
        self.assertAlmostEqual(c.elapsed_s,.6)
        self.assertEqual(c.expired,2)
    def test_good_encoder_pose_advances_without_added_delay(self):
        curve=SimpleNamespace(period=.05,duration=1.,stops=[.5,1.],
            sample=lambda t:dict(phase='LOWER' if t<=.5 else 'DRAW',stroke=0))
        c=PenPhaseCoordinator(curve);counts={1:2000}
        self.assertFalse(c.refine(.5,counts,counts,True,.05));self.assertEqual(c.elapsed_s,0.)


class LagPort(DemoPort):
    """First-order position response with a static load bias, not teleporting."""
    def __init__(self,clock):
        super().__init__();self.clock=clock;self.last=clock[0]
        self.x={i:float(v) for i,v in self.positions.items()}
        self.bias={1:0,2:24,3:-18,4:8,5:0}
        self.goal={i:v+self.bias.get(i,0) for i,v in self.x.items()}
    def write(self,packet):
        dt=self.clock[0]-self.last;self.last=self.clock[0]
        alpha=1-math.exp(-dt/.12)
        for sid in self.x:self.x[sid]+=(self.goal[sid]-self.bias.get(sid,0)-self.x[sid])*alpha
        self.positions={i:int(round(v)) for i,v in self.x.items()}
        result=super().write(packet)
        if packet[4]==0x83 and packet[5] in (41,42):
            self.goal.update(self.positions)
            self.positions={i:int(round(v)) for i,v in self.x.items()}
        return result


class SchedulerPlantTests(unittest.TestCase):
    def run_move(self,enabled):
        clock=[0.];p=LagPort(clock);m=machine();m['execution']['feedback_control']={'enabled':enabled}
        current={i:p.positions[i] for i in range(1,6)};end=dict(current);end[2]+=100;end[3]-=80
        with patch('smooth_motion.time.monotonic',lambda:clock[0]),patch('smooth_motion.time.sleep',lambda t:clock.__setitem__(0,clock[0]+t)):
            result=joint_move(Executor(p,m),current,end,minimum_duration=8.)
        return result
    def test_feedback_reduces_bias_while_fixed_rate_and_no_abort(self):
        before,after=self.run_move(False),self.run_move(True)
        residual=lambda r:max(abs(r['last_measured_counts'][sid]-r['target_counts'][sid]) for sid in r['target_counts'])
        self.assertLess(residual(after),residual(before)*.5)
        self.assertTrue(after['execution_finished']);self.assertEqual(after['timing']['progress_changes'],0)
        self.assertEqual(after['timing']['trajectory_frames_sent'],before['timing']['trajectory_frames_sent'])
        self.assertLess(after['timing']['elapsed_s'],before['timing']['elapsed_s']+.55)


if __name__=='__main__':unittest.main()
