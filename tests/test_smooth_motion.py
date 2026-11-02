"""Independent numerical and virtual-serial acceptance of the gentle profile."""
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
from r1b.retiming import (quintic_full,derivative_bounds_many,minimum_jerk_nodes,
                         rest_move,legal_segments,stop_blocks)
from r1b.continuous import evaluate
from motion import Executor,counts_from_angles,angles_from_counts,sync_position_profile
from protocol import DemoPort,exchange,ProbeError
from smooth_motion import MotionCurve,Progress,ServoSettings,joint_move,BufferedAudit,align_start,SerialMotionScheduler
from vision import preset
from workbench import StoredPlan,Workbench


def machine():
    m=json.loads((ROOT/'config/machine.example.json').read_text(encoding='utf-8'))
    _,paper,_=planning.nominal();m['paper']=paper
    for j in m['joints']:j.update(zero_count=2048,min_count=100,max_count=3900)
    m['execution']={'buffered_audit':False,'settle_timeout_s':.3}
    m['trajectory']={'command_period_s':.05,'min_segment_s':.015,'max_cartesian_step_m':.002,
                     'lift_m':.012,'max_velocity_rad_s':.15,'max_acceleration_rad_s2':.5}
    return m


class SmoothMathTests(unittest.TestCase):
    def test_full_quintic_matches_all_six_endpoint_conditions(self):
        rng=np.random.default_rng(934)
        for _ in range(30):
            q0,q1,v0,v1,a0,a1=rng.normal(size=(6,5));h=rng.uniform(.05,3.)
            c=quintic_full(q0,q1,v0,v1,a0,a1,h)
            for u,wanted in ((0,(q0,v0,a0)),(1,(q1,v1,a1))):
                for actual,expected in zip(evaluate(c,u,h),wanted):
                    np.testing.assert_allclose(actual,expected,atol=1e-10,rtol=1e-10)

    def test_analytic_bounds_contain_dense_velocity_acceleration_and_jerk(self):
        rng=np.random.default_rng(79)
        c=rng.normal(size=(20,6,5));times=rng.uniform(.05,3,20)
        bounds=derivative_bounds_many(c,times)
        u=np.linspace(0,1,3001)[:,None]
        for i in range(20):
            _,v,a=evaluate(c[i],u,times[i])
            j=(6*c[i,3]+24*c[i,4]*u+60*c[i,5]*u*u)/times[i]**3
            for measured,bound in zip((v,a,j),bounds):
                self.assertTrue(np.all(np.abs(measured).max(axis=0)<=bound[i]*(1+1e-10)))
            # Exact quadratic extrema, not a sparse sample claim.
            np.testing.assert_allclose(np.abs(j).max(axis=0),bounds[2][i],rtol=2e-5,atol=1e-7)

    def test_banded_solution_matches_independent_dense_jerk_integral(self):
        q=np.outer([0,.12,.25,.45,.6,.72],[1,.8,.6,.4,.2])
        times=np.array([.4,.8,.6,.7,.5]);n=len(times);size=2*(n-1)
        # Independent basis built by evaluating the public endpoint polynomial;
        # no band matrix/indexing shared with the implementation.
        basis=[];base=[];gram=1./(np.arange(3)[:,None]+np.arange(3)[None,:]+1)
        for i,h in enumerate(times):
            zeros=np.zeros(5)
            c=quintic_full(q[i],q[i+1],zeros,zeros,zeros,zeros,h)
            base.append(np.array([6,24,60])[:,None]*c[3:])
            columns=[]
            for k in range(size):
                v=np.zeros((n+1,5));a=np.zeros_like(v)
                (v if k%2==0 else a)[k//2+1]=1.
                p=quintic_full(q[i],q[i+1],v[i],v[i+1],a[i],a[i+1],h)
                columns.append((np.array([6,24,60])[:,None]*(p[3:]-c[3:]))[:,0])
            basis.append(np.array(columns).T)
        hessian=sum(b.T@gram@b/h**5 for b,h in zip(basis,times))
        rhs=-sum(b.T@gram@c/h**5 for b,c,h in zip(basis,base,times))
        reference=np.linalg.solve(hessian,rhs)
        v,a=minimum_jerk_nodes(q,times)
        actual=np.empty_like(reference);actual[0::2]=v[1:-1];actual[1::2]=a[1:-1]
        np.testing.assert_allclose(actual,reference,rtol=3e-10,atol=1e-10)
        self.assertGreater(np.abs(a[1:-1]).max(),.01)

    def test_reversing_component_stops_velocity_without_forcing_acceleration_zero(self):
        q=np.outer([0,.2,0,-.2],[1,.8,.6,.4,.2]);v,a=minimum_jerk_nodes(q,np.ones(3))
        np.testing.assert_allclose(v[1],0,atol=1e-12)
        self.assertGreater(np.linalg.norm(a[1]),.01)
        np.testing.assert_allclose(v[[0,-1]],0);np.testing.assert_allclose(a[[0,-1]],0)

    def test_bad_times_and_cancelled_solve_are_explicit(self):
        for t in ([1,float('nan')],[1,0],[1,-1],[]):
            with self.assertRaisesRegex(ValueError,'DERIVATIVE_SOLVER_FAILURE'):
                minimum_jerk_nodes(np.zeros((len(t)+1,5)),np.array(t))
        with self.assertRaisesRegex(ValueError,'ABORT'):
            minimum_jerk_nodes(np.outer([0,1,2],np.ones(5)),np.ones(2),lambda:True)

    def test_rest_move_bounds_all_joints_and_keeps_endpoints(self):
        cfg={'max_velocity_rad_s':.12,'max_acceleration_rad_s2':.3,'max_jerk_rad_s3':20,'command_period_s':.05}
        q0=np.zeros(5);q1=np.array([.2,-.3,.1,.04,-.08]);c,h=rest_move(q0,q1,cfg)
        for bound,limit in zip(derivative_bounds_many(c[None],np.array([h])),(.12,.3,20)):
            self.assertTrue(np.all(bound<=limit*(1+1e-10)))
        self.assertAlmostEqual(h/.05,round(h/.05))
        np.testing.assert_allclose(evaluate(c,1,h)[0],q1,atol=1e-14)
        self.assertTrue(legal_segments(c[None],np.array([[-.4,.4]]*5)).all())

    def test_sharp_corner_and_pen_phase_boundaries_require_rest(self):
        targets=[dict(position=p,phase=phase,stroke=0) for p,phase in
                 (([0,0,0],'START'),([1,0,0],'DRAW'),([2,0,0],'DRAW'),([2,1,0],'DRAW'),([2,1,1],'LIFT'))]
        blocks,reasons=stop_blocks(targets,{})
        self.assertNotIn(1,reasons)
        self.assertIn(2,reasons);self.assertIn(3,reasons)


class GentlePlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.folder=Path(cls.tmp.name)
        cls.m=machine()
        _,_,q0=planning.nominal();cls.counts=counts_from_angles(cls.m,q0)
        cls.plans={}
        for name in ('line','circle','square'):
            result,spec,cfg=planning.build(preset(name,cls.folder/(name+'in'),10,10),cls.folder/name,
                                          cls.m,cls.counts,motion_mode='gentle')
            if result.status!='OK':raise AssertionError((name,result.status,result.metrics))
            cls.plans[name]=(result,spec,cfg)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_all_phases_have_fixed_period_valid_contract_and_c2(self):
        for r,s,cfg in self.plans.values():
            curve=MotionCurve(r,self.m)
            np.testing.assert_allclose(np.diff([0]+[c['t_s'] for c in r.commands]),.05,atol=1e-12)
            self.assertLess(r.metrics['max_knot_velocity_jump_rad_s'],1e-7)
            self.assertLess(r.metrics['max_knot_acceleration_jump_rad_s2'],1e-7)
            self.assertLessEqual(r.metrics['peak_jerk_rad_s3'],20)
            self.assertEqual(r.metrics['avoidable_stop_knots'],0)
            self.assertLessEqual(r.metrics['max_draw_path_error_m'],cfg['tracking_error_m'])
            self.assertLess(r.metrics['quantization']['max_source_path_error_m'],.001)
            self.assertEqual(r.metrics['retime_passes']<=4,True)
            self.assertLessEqual(r.metrics['geometry_batch_limit'],1024)

    def test_provenance_and_rest_samples_cover_closed_circle_once(self):
        r,_,_=self.plans['circle'];curve=MotionCurve(r,self.m)
        for stamp in curve.stops:
            sample=curve.sample(stamp)
            self.assertLess(max(abs(v) for v in sample['velocity_rad_s']),1e-8)
            self.assertLess(max(abs(v) for v in sample['acceleration_rad_s2']),1e-8)
        provenance=[tuple(c['source_segment_id']) for c in r.commands if c['pen_down']]
        compressed=[v for i,v in enumerate(provenance) if i==0 or v!=provenance[i-1]]
        self.assertEqual(len(compressed),len(set(compressed)))

    def test_progress_retiming_obeys_chain_rule_and_visits_every_rest_boundary(self):
        curve=MotionCurve(self.plans['line'][0],self.m);p=Progress(curve)
        self.assertTrue(p.target(.5));visited=[]
        for k in range(2500):
            old=p.position;p.advance(.05);sample=curve.sample(p.position)
            v,a,j=[np.array(sample[key]) for key in ('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3')]
            actual=(v*p.rate,a*p.rate**2+v*p.first,
                    j*p.rate**3+3*a*p.rate*p.first+v*p.second)
            for values,limit in zip(actual,curve.limits):self.assertTrue(np.all(np.abs(values)<=limit*(1+1e-8)))
            self.assertGreaterEqual(p.position,old)
            if any(abs(p.position-stop)<1e-8 for stop in curve.stops):visited.append(p.position)
            if k==45:p.target(1.)
            if p.position>=curve.duration-1e-9:break
        self.assertAlmostEqual(p.position,curve.duration)
        for stop in curve.stops:self.assertTrue(any(abs(s-stop)<1e-8 for s in visited))

    def test_tampered_saved_polynomial_or_metadata_rejected_before_port_write(self):
        for mutation in ('coefficient','period','commands','phase','missing'):
            r=copy.deepcopy(self.plans['line'][0]);p=DemoPort()
            if mutation=='coefficient':r.trajectory_segments[0]['coeffs'][2][0]+=.3
            if mutation=='period':r.execution_contract['command_period_s']=.06
            if mutation=='commands':r.commands[0]['q_rad'][0]+=.01
            if mutation=='phase':r.commands[0]['pen_down']=True
            if mutation=='missing':r.trajectory_segments=None
            with self.assertRaises(ValueError):Executor(p,self.m).execute(r,self.plans['line'][1]['q0'])
            self.assertFalse(p.writes)

    def test_prepared_curve_is_owned_and_calibration_bound(self):
        result,spec,_ = copy.deepcopy(self.plans['line'])
        curve = MotionCurve(result,self.m)
        old_phase = curve.rows[0]['phase']
        result.trajectory_segments[0]['phase'] = 'DRAW'
        result.execution_contract['servo_profile']['speed_codes'] = 1
        self.assertEqual(curve.rows[0]['phase'],old_phase)
        wrong = copy.deepcopy(self.m);wrong['joints'][0]['zero_count'] += 1
        port = DemoPort()
        with self.assertRaises(ValueError): Executor(port,wrong).execute_curve(curve,spec['q0'])
        self.assertFalse(port.writes)
        current = counts_from_angles(self.m,curve.q0)
        port.positions.update(current)
        with patch('smooth_motion.validate_plan',side_effect=AssertionError('duplicate validation')), patch.object(SerialMotionScheduler,'run',return_value={}):
            Executor(port,self.m).execute_curve(curve,spec['q0'])

    def test_encoder_drift_is_accepted_and_entry_does_not_change_drawing(self):
        r,s,_=self.plans['line'];base=MotionCurve(r,self.m)
        original_commands=copy.deepcopy(r.commands)
        expected=counts_from_angles(self.m,base.q0)
        unchanged,detail=align_start(base,expected)
        self.assertIs(unchanged,base);self.assertFalse(detail['applied'])
        for drift in (3,12,45,90,400):
            current=dict(expected);current[1]+=drift
            joined,detail=align_start(base,current)
            self.assertTrue(detail['applied']);self.assertEqual(detail['delta_counts'][1],drift)
            np.testing.assert_allclose(joined.sample(0)['q_rad'],angles_from_counts(self.m,current),atol=1e-12)
            boundary=joined.sample(detail['duration_s'])
            cut=detail['replaced_approach_s']
            np.testing.assert_allclose(boundary['q_rad'],base.sample(cut)['q_rad'],atol=1e-10)
            self.assertFalse(boundary['pen_down'])
            self.assertLess(max(abs(v) for v in boundary['velocity_rad_s']),1e-9)
            self.assertLess(max(abs(v) for v in boundary['acceleration_rad_s2']),1e-9)
            self.assertTrue(np.all(joined.peaks<=joined.limits*(1+1e-8)))
            for stamp in (cut+base.period,(cut+base.duration)/2,base.duration):
                a,b=base.sample(stamp),joined.sample(detail['duration_s']+stamp-cut)
                np.testing.assert_allclose(a['q_rad'],b['q_rad'],atol=1e-10)
                self.assertEqual((a['phase'],a['stroke'],a['pen_down']),(b['phase'],b['stroke'],b['pen_down']))
                self.assertEqual(a['source_segment_id'],b['source_segment_id'])
            p=DemoPort();p.positions.update(current)
            with patch.object(SerialMotionScheduler,'run',return_value={'frames':1}) as run:
                outcome=Executor(p,self.m).execute(r,s['q0'])
            self.assertEqual(outcome['start_alignment']['delta_counts'][1],drift)
            run.assert_called_once_with(current)
        self.assertEqual(r.commands,original_commands)

    def test_history_persists_executable_curve_and_reload_keeps_preview(self):
        with tempfile.TemporaryDirectory() as t:
            state=SimpleNamespace(directory=Path(t)/'session',record=lambda *args:None)
            state.directory.mkdir();w=Workbench(state)
            r,s,_=self.plans['line']
            stored=dict(result=r,q0=s['q0'],mode='real',machine=self.m,digest='test',paths={},drawing=s)
            self.assertTrue(w._save_plan('test',stored))
            w2=Workbench(state);restored=w2.plans['test']['result']
            curve=MotionCurve(restored,self.m)
            self.assertAlmostEqual(curve.duration,r.metrics['duration_s'])
            self.assertFalse(w2.list_plans()['plans'][0]['needs_replan'])

    def test_solver_failure_uses_bounded_fallback_preserving_geometry(self):
        from r1b import smooth
        with patch.object(smooth,'minimum_jerk_nodes',side_effect=ValueError('DERIVATIVE_SOLVER_FAILURE')):
            r,_,cfg=planning.build(preset('line',self.folder/'fallbackin',10,10),self.folder/'fallback',
                                  self.m,self.counts,motion_mode='gentle')
        self.assertEqual(r.status,'OK');self.assertGreater(r.metrics['fallback_blocks'],0)
        self.assertLessEqual(r.metrics['peak_jerk_rad_s3'],20)
        self.assertLessEqual(r.metrics['max_draw_path_error_m'],cfg['tracking_error_m'])

    def test_prediction_uses_original_segment_ids_for_fixed_grid_plan(self):
        from drawing_prediction import command_preview
        r,s,_=self.plans['circle']
        paths=preset('circle',self.folder/'preview_input',10,10)
        data=dict(vars(r),paths=paths,drawing=s,machine=self.m,mode='real')
        preview=command_preview(data)
        self.assertEqual(preview['unrepresented_segments'],0)
        self.assertEqual(preview['motion_algorithm_version'],'motion-smooth-v1')
        for row in preview['rows']:
            self.assertGreaterEqual(row['command_last'],row['command_first'])

    def test_home_height_ik_uses_current_calibrated_model_and_paper(self):
        m=copy.deepcopy(self.m);m['model']['tool_translation_m']=[.01,.02,.03]
        m['paper']['home_height_offset_m']=.003
        device=DemoPort();calls=[]
        ex=SimpleNamespace(move_pen_up_to=lambda *a,**kw:dict(task_complete=True))
        with tempfile.TemporaryDirectory() as t:
            state=SimpleNamespace(directory=Path(t)/'session',record=lambda *a:None)
            state.directory.mkdir();w=Workbench(state)
            def height(model,paper,q,offset,backend=None):
                calls.append((model,paper,offset));return np.asarray(q)
            with patch('planning.home_pose',height):w._home_move(device,m,ex)
        self.assertTrue(calls)
        for model,paper,_ in calls:
            np.testing.assert_array_equal(model.tool,[.01,.02,.03])
            self.assertEqual(paper,m['paper'])


class VirtualSerialTests(unittest.TestCase):
    def setUp(self):
        self.clock=[0.];self.m=machine();self.p=DemoPort();self.events=[];self.emitted=[]
        self.current={i:self.p.positions[i] for i in range(1,6)}
        self.end=dict(self.current);self.end[2]+=20
        original=self.p.write
        def write(packet):
            self.clock[0]+=.0002
            if packet[4]==0x83:self.emitted.append((self.clock[0],bytes(packet)))
            return original(packet)
        self.p.write=write
        self.addCleanup(patch.stopall)
        patch('smooth_motion.time.monotonic',lambda:self.clock[0]).start()
        patch('smooth_motion.time.sleep',lambda dt:self.clock.__setitem__(0,self.clock[0]+dt)).start()

    def run_move(self,**kw):
        ex=Executor(self.p,self.m,audit=lambda *v:self.events.append(v),**kw)
        return joint_move(ex,self.current,self.end,minimum_duration=1.)

    def test_single_owner_writes_no_catchup_and_downsamples_feedback(self):
        r=self.run_move();self.assertTrue(r['task_complete']);self.assertEqual(r['frames'],20)
        self.assertEqual(self.p.positions[2],self.end[2]);self.assertEqual(self.p.positions[6],2150)
        intervals=np.diff([t for t,_ in self.emitted]);self.assertTrue(np.all(intervals>=.05-1e-10))
        self.assertLess(intervals.max(),.055)
        position_requests=[p for p in self.p.writes if p[4]==2 and p[5]==56]
        self.assertLess(len(position_requests),5*20)
        self.assertEqual(r['servo_parameter_status'],'existing_acceleration_preserved_unverified')
        self.assertTrue(all(packet[5]==42 for _,packet in self.emitted))
        self.assertTrue(all(packet[-3:-1]==bytes([200,0]) for _,packet in self.emitted))

    def test_normal_write_latency_is_not_added_to_every_command_period(self):
        original=self.p.write
        def slow_write(packet):
            if packet[4]==0x83:self.clock[0]+=.01
            return original(packet)
        self.p.write=slow_write
        r=self.run_move()
        self.assertTrue(r['task_complete']);self.assertEqual(r['frames'],20)
        self.assertLess(r['timing']['elapsed_s'],1.1)
        self.assertAlmostEqual(r['timing']['actual_interval_p50_s'],.05,places=8)

    def test_cancel_holds_last_pose_and_keeps_torque(self):
        with self.assertRaisesRegex(RuntimeError,'STOPPED'):
            self.run_move(cancelled=lambda:self.clock[0]>.35)
        self.assertLess(len(self.emitted),20)
        self.assertTrue(all(v==1 for v in self.p.torques.values()))
        self.assertTrue(all(p[5]!=40 for _,p in self.emitted))

    def test_missing_feedback_does_not_abort_or_claim_settled(self):
        original=self.p.write
        def write(packet):
            result=original(packet)
            if packet[4]==2 and packet[5]==56:self.p.buffer.clear()
            return result
        self.p.write=write
        r=self.run_move()
        self.assertEqual(r['frames'],20)
        self.assertFalse(r['task_complete']);self.assertTrue(r['quality_warning'])
        self.assertGreater(r['timing']['feedback_failures'],0)

    def test_transient_write_failure_retries_same_point_then_finishes(self):
        original=self.p.write;attempts=[0];failed=[];accepted=[]
        def write(packet):
            if packet[4]==0x83:
                attempts[0]+=1
                if attempts[0] in (4,5):failed.append(bytes(packet));raise OSError('Write timeout')
                accepted.append(bytes(packet))
            return original(packet)
        self.p.write=write
        r=self.run_move()
        self.assertTrue(r['task_complete']);self.assertEqual(r['frames'],20)
        self.assertEqual(r['timing']['write_failures'],2)
        self.assertEqual(failed[0],failed[1]);self.assertEqual(failed[0],accepted[3])
        self.assertEqual(len(accepted),20)

    def test_late_cycle_continues_without_catchup_burst(self):
        original_sleep=__import__('time').sleep;stalled=[False]
        def sleep(dt):
            original_sleep(dt)
            if self.clock[0]>.22 and not stalled[0]:self.clock[0]+=.14;stalled[0]=True
        with patch('smooth_motion.time.sleep',sleep):
            r=self.run_move()
        self.assertEqual(r['frames'],20);self.assertTrue(r['task_complete'])
        self.assertGreater(r['timing']['missed_deadlines'],0)
        self.assertTrue(np.all(np.diff([t for t,_ in self.emitted])>=.05-1e-10))

    def test_following_error_above_40_records_and_continues_even_strict(self):
        original=SerialMotionScheduler._read_positions
        def lagged(scheduler,deadline):
            fresh=original(scheduler,deadline)
            if fresh:scheduler.feedback[2]+=100
            return fresh
        self.m['execution']['guard_policy']='strict'
        with patch.object(SerialMotionScheduler,'_read_positions',lagged):
            r=self.run_move()
        self.assertTrue(r['execution_finished']);self.assertFalse(r['task_complete'])
        self.assertGreaterEqual(r['timing']['max_following_error_counts'],100)
        self.assertEqual(r['timing']['progress_changes'],0)
        self.assertEqual(r['frames'],20)

    def test_persistent_write_problem_keeps_retrying_until_manual_stop(self):
        original=self.p.write
        def unavailable(packet):
            if packet[4]==0x83:raise OSError('Write timeout')
            return original(packet)
        self.p.write=unavailable
        with self.assertRaisesRegex(RuntimeError,'STOPPED'):
            self.run_move(cancelled=lambda:self.clock[0]>.4)
        self.assertTrue(any(e[0]=='WRITE_RETRY' for e in self.events))
        self.assertFalse(any(e[0]=='MOTION_SMOOTH_DONE' for e in self.events))

    def test_verified_acceleration_codes_are_explicit_and_read_back(self):
        self.m['execution']['servo_profile']=dict(units_verified=True,speed_codes=100,acceleration_codes=30,
            speed_unit_rad_s=.01,acceleration_unit_rad_s2=.1,
            verified_registers=dict(firmware={'major':2,'minor':54},velocity_unit=1,maximum_acceleration=254,
                                    acceleration_multiplier=1))
        r=self.run_move()
        self.assertTrue(r['task_complete'])
        self.assertTrue(all(self.p.accelerations[i]==30 for i in self.current))
        self.assertTrue(all(packet[5:7]==bytes([41,7]) for _,packet in self.emitted))

    def test_unverified_or_underpowered_profile_rejected_without_serial_io(self):
        contract=dict(servo_profile={'acceleration_codes':30},joint_max_velocity_rad_s=[.12]*5,
                      joint_max_acceleration_rad_s2=[.3]*5)
        with self.assertRaisesRegex(ValueError,'尚未验证'):ServoSettings(self.m,contract)
        contract['servo_profile'].update(units_verified=True,speed_codes=1,speed_unit_rad_s=.001,
                                        acceleration_unit_rad_s2=.001)
        with self.assertRaises(ValueError):ServoSettings(self.m,contract)
        self.assertFalse(self.p.writes)

    def test_exchange_deadline_and_nan_rejected_before_packet(self):
        for kwargs in ({'deadline':-1},{'deadline':float('nan')},{'timeout':float('inf')}):
            with self.assertRaises((ValueError,ProbeError)):exchange(self.p,1,'position',**kwargs)
        self.assertFalse(self.p.writes)

    def test_wrong_firmware_signature_prevents_any_motion_profile_write(self):
        self.m['execution']['servo_profile']=dict(units_verified=True,speed_codes=100,acceleration_codes=30,
            speed_unit_rad_s=.01,acceleration_unit_rad_s2=.1,
            verified_registers=dict(firmware={'major':9,'minor':99},velocity_unit=1,maximum_acceleration=254,
                                    acceleration_multiplier=1))
        with self.assertRaisesRegex(ValueError,'固件或单位'):self.run_move()
        # Failure hold must preserve existing parameters; see scheduler guard.
        self.assertFalse(any(packet[5]==41 for _,packet in self.emitted))

    def test_profile_packet_roundtrip_preserves_other_registers_and_gripper(self):
        original_torque=self.p.torques.copy();gripper=self.p.positions[6]
        sync_position_profile(self.p,self.end,{i:80 for i in self.end},{i:25 for i in self.end})
        for sid in self.end:
            self.assertEqual(exchange(self.p,sid,'acceleration'),25)
            self.assertEqual(exchange(self.p,sid,'goal_speed'),80)
            self.assertEqual(exchange(self.p,sid,'position_speed')['position_count'],self.end[sid])
        self.assertEqual(self.p.positions[6],gripper);self.assertEqual(self.p.torques,original_torque)

    def test_home_plane_prediction_is_recorded_without_refusing_move(self):
        ex=Executor(self.p,self.m,audit=lambda *v:self.events.append(v))
        r=joint_move(ex,self.current,self.end,minimum_duration=1.,minimum_clearance_m=10.)
        self.assertTrue(r['task_complete']);self.assertTrue(self.emitted)
        self.assertTrue(any(e[0]=='HOME_PLANE_OFF' for e in self.events))


class AuditTests(unittest.TestCase):
    def test_async_sink_failure_is_recorded_without_aborting_motion(self):
        def failed(*args):raise OSError('disk full')
        audit=BufferedAudit(failed)
        audit('FRAME',{});audit.queue.join()
        self.assertFalse(audit.check());audit.close()
        self.assertIn('disk full',str(audit.error))
        self.assertFalse(audit.worker.is_alive())

    def test_full_log_queue_drops_record_without_aborting_motion(self):
        import threading
        started=threading.Event();release=threading.Event()
        def blocked(*args):started.set();release.wait(2.)
        audit=BufferedAudit(blocked)
        try:
            audit('FIRST',{});self.assertTrue(started.wait(1.))
            for i in range(256):audit('FRAME',{'index':i})
            audit('EXTRA',{});self.assertEqual(audit.dropped,1)
        finally:
            release.set();audit.close()


if __name__=='__main__':unittest.main()
