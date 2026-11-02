"""No-motor acceptance of planned lift monitoring and measured feedforward."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import planning
from motion import Executor, angles_from_counts, counts_from_angles
from planned_execution import PlannedFeedforward, PlannedLiftMonitor
from protocol import DemoPort, ProbeError, exchange, servo_snapshot
import smooth_motion
from smooth_motion import ServoSettings, SerialMotionScheduler, MotionCurve, align_start


def machine():
    m = json.loads((ROOT/'config/machine.example.json').read_text(encoding='utf-8'))
    _, paper, _ = planning.nominal()
    m['paper'] = paper
    for joint in m['joints']:
        joint.update(zero_count=2048, min_count=100, max_count=3900)
    m['trajectory'] = dict(lift_m=.006)
    m['execution'] = dict(buffered_audit=False, vertical_pen_lift=True,
                          position_feedback_period_s=.1, feedback_stale_s=.25,lift_endpoint_policy='stop')
    return m


class LinearModel:
    """Independent model for scheduler tests, not a physical robot claim."""
    tool_axis = np.array([0., 0., -1.])
    limits = np.array([[-2.8, 2.8]]*5)

    def legal(self, q):
        q = np.asarray(q)
        return q.shape == (5,) and np.isfinite(q).all() and (abs(q) <= 2.8).all()

    def pose(self, q):
        result = np.eye(4)
        result[:3, 3] = np.asarray(q)[:3]
        c, s = math.cos(q[3]), math.sin(q[3])
        result[:3, :3] = [[c, 0, s], [0, 1, 0], [-s, 0, c]]
        return result


class TestCurve:
    def __init__(self, m, profile=None):
        self.machine, self.model = m, LinearModel()
        self.period, self.duration = .02, .24
        self.q0 = np.array([0., 0., 0., .1, 0.])
        self.stops = [.02, .12, .14, .24]
        self.limits = np.array([[.9]*5, [4.]*5, [200.]*5])
        self.peaks = self.limits*.1
        self.contract = dict(motion_mode='sugar_fast', pen_lift_policy='planned_vertical_v2',
                             servo_profile=profile or {}, joint_max_velocity_rad_s=[.9]*5,
                             joint_max_acceleration_rad_s2=[4.]*5)
        self.rows = [dict(phase='LIFT')]
        self.settings = ServoSettings(m, self.contract)

    def next_stop(self, stamp):
        return next((stop for stop in self.stops if stop > stamp+1e-9), self.duration)

    def sample(self, stamp):
        stamp = max(0., min(float(stamp), self.duration))
        if stamp <= .02+1e-10:
            phase, stroke, height, block = 'DRAW', 0, 0., 0
        elif stamp <= .12+1e-10:
            phase, stroke, height, block = 'LIFT', 0, .006*(stamp-.02)/.1, 1
        elif stamp <= .14+1e-10:
            phase, stroke, height, block = 'TRAVEL', 1, .006, 2
        else:
            phase, stroke, height, block = 'LIFT', 1, .006+.006*(stamp-.14)/.1, 3
        q = [0., 0., height, .1, 0.]
        return dict(t_s=stamp, q_rad=q, phase=phase, stroke=stroke, pen_down=phase=='DRAW',
                    motion_block_id=block, tip_reference_m=q[:3], tip_target_m=q[:3],
                    axis_target=[0., 0., -1.], source_segment_id=None, path_segment_index=block,
                    segment_start_m=[0., 0., height], segment_end_m=[0., 0., height])


def verified_profile():
    return dict(units_verified=True, speed_codes=200, acceleration_codes=60,
                speed_unit_rad_s=.01, acceleration_unit_rad_s2=.1,
                frame_speed_enabled=True, frame_speed_min_code=20,
                verified_registers=dict(firmware=dict(major=2, minor=54), velocity_unit=1,
                                        maximum_acceleration=254, acceleration_multiplier=1))


def documented_profile():
    from new_scheme_config import documented_position_stream
    signature=dict(model=777,mode=0,firmware=dict(major=3,minor=15),phase=12,
                   velocity_unit=50,maximum_speed=65,acceleration=0,acceleration_multiplier=0)
    return documented_position_stream(machine(),{sid:signature for sid in range(1,6)})['execution']['servo_profile']


class FrameProfileTests(unittest.TestCase):
    def test_documented_stream_covers_plan_without_faking_dynamic_calibration(self):
        profile=documented_profile();settings=TestCurve(machine(),profile).settings
        self.assertFalse(profile['units_verified'])
        self.assertFalse(settings.frame_speed_enabled)
        self.assertTrue(settings.documented_stream)
        self.assertIsNone(settings.accelerations)
        p=DemoPort();values={sid:2048 for sid in range(1,6)}
        settings.write(p,values)
        self.assertEqual(p.writes[-1][5],42)
        self.assertEqual([p.speeds[sid] for sid in values],[700]*5)
        self.assertEqual([p.accelerations[sid] for sid in values],[50]*5)
        for bad in (100,800):
            invalid=copy.deepcopy(profile);invalid['speed_codes']=bad
            with self.assertRaises(ValueError):TestCurve(machine(),invalid)

    def test_documented_stream_rejects_wrong_speed_units(self):
        profile=documented_profile()
        profile['verified_registers']['3']['phase']=8
        with self.assertRaisesRegex(ValueError,'mapping'):
            TestCurve(machine(),profile)

    def test_delta_converted_using_measured_radian_units_and_same_packet(self):
        m = machine(); settings = TestCurve(m, verified_profile()).settings
        before = {sid: 2048 for sid in range(1, 6)}
        after = dict(before); after[2] += 8; after[3] += 12; after[4] -= 12
        p = DemoPort(); settings.write(p, after, before, .02)
        self.assertEqual(len(p.writes), 1)
        self.assertEqual(p.writes[0][5:7], bytes([41, 7]))
        wanted = math.ceil(12*2*math.pi/4096/.02*1.15/.01)
        self.assertEqual(p.speeds[3], wanted)
        self.assertEqual(p.speeds[4], wanted)
        self.assertEqual(p.accelerations[2], p.accelerations[3])
        self.assertEqual(p.accelerations[3], p.accelerations[4])
        self.assertEqual(p.speeds[1], 20)
        self.assertEqual(p.positions[6], 2150)

    def test_unverified_falls_back_without_acceleration_write_or_can_reject(self):
        m = machine(); profile = dict(frame_speed_enabled=True, units_verified=False,
                                      unverified_policy='preserve_static')
        settings = TestCurve(m, profile).settings
        p = DemoPort(); values = {sid: 2048 for sid in range(1, 6)}
        settings.write(p, values, values, .02)
        self.assertEqual(p.writes[0][5], 42)
        self.assertIn('disabled_units_unverified', settings.status)
        profile['unverified_policy'] = 'reject'
        with self.assertRaisesRegex(ValueError, '尚未实测'):
            TestCurve(m, profile)

    def test_speed_overflow_is_not_silently_clipped(self):
        settings = TestCurve(machine(), verified_profile()).settings
        before = {sid: 2048 for sid in range(1, 6)}
        after = dict(before); after[3] += 100
        p = DemoPort()
        with self.assertRaisesRegex(ValueError, '超过已验证上限'):
            settings.write(p, after, before, .02)
        self.assertFalse(p.writes)


class CompensationTests(unittest.TestCase):
    def setUp(self):
        self.m = machine(); self.model = LinearModel()

    def bias_config(self):
        return dict(enabled=True, calibrated=True, measurement_id='fixture-measurement',
                    samples=[dict(tip_m=[x, y, 0.], counts={str(sid): 3. if sid == 3 else 0. for sid in range(1, 6)})
                             for x, y in ((0,0),(-.05,-.05),(-.05,.05),(.05,-.05),(.05,.05))])

    def test_disabled_is_identity_and_uncalibrated_is_refused(self):
        c = TestCurve(self.m); ff = PlannedFeedforward(self.m, self.model)
        cmd = c.sample(.08); actual, _ = ff.target(c, cmd)
        self.assertEqual(actual, counts_from_angles(self.m, cmd['q_rad']))
        self.m['execution']['load_bias_counts'] = dict(enabled=True, calibrated=False)
        with self.assertRaisesRegex(ValueError, '尚未实测'):
            PlannedFeedforward(self.m, self.model)

    def test_five_point_interpolation_keeps_exact_samples(self):
        self.m['execution']['load_bias_counts'] = self.bias_config()
        ff = PlannedFeedforward(self.m, self.model)
        np.testing.assert_allclose(ff.load_bias([0., 0., .1]), [0, 0, 3, 0, 0])
        np.testing.assert_allclose(ff.load_bias([.013, .025, .1]), [0, 0, 3, 0, 0])
        c = TestCurve(self.m); cmd = c.sample(.08)
        values, _ = ff.target(c, cmd)
        self.assertEqual(values[3]-counts_from_angles(self.m, cmd['q_rad'])[3], 3)

    def test_limit_is_rejected_not_clipped(self):
        self.m['execution']['load_bias_counts'] = self.bias_config()
        self.m['joints'][2]['max_count'] = 2052
        ff = PlannedFeedforward(self.m, self.model); c = TestCurve(self.m)
        with self.assertRaisesRegex(ValueError, '计数限位'):
            ff.validate_curve(c)

    def test_delay_never_anticipates_next_motion_block(self):
        self.m['execution']['joint_delay_s'] = dict(enabled=True, calibrated=True,
            measurement_id='ramp-measurement', seconds={str(sid): .04 if sid==3 else 0. for sid in range(1,6)})
        ff = PlannedFeedforward(self.m, self.model); c = TestCurve(self.m)
        at_end, _ = ff.target(c, c.sample(.12))
        self.assertEqual(at_end, counts_from_angles(self.m, c.sample(.12)['q_rad']))
        before_end, _ = ff.target(c, c.sample(.10))
        self.assertEqual(before_end[3], at_end[3])

    def test_invalid_or_nan_calibration_is_rejected(self):
        self.m['execution']['load_bias_counts'] = self.bias_config()
        self.m['execution']['load_bias_counts']['samples'][0]['counts']['3'] = float('nan')
        with self.assertRaises(ValueError): PlannedFeedforward(self.m, self.model)


class PlannedSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.m = machine(); self.p = DemoPort(); self.events = []; self.clock = [0.]
        self.current = {sid: 2048 for sid in range(1, 6)}
        self.p.positions.update(self.current)
        original = self.p.write
        def write(packet):
            self.clock[0] += .00002
            return original(packet)
        self.p.write = write
        self.addCleanup(patch.stopall)
        patch('smooth_motion.time.monotonic', lambda: self.clock[0]).start()
        patch('smooth_motion.time.sleep', lambda dt: self.clock.__setitem__(0, self.clock[0]+dt)).start()

    def scheduler(self, profile=None):
        return SerialMotionScheduler(Executor(self.p, self.m, audit=lambda *e: self.events.append(e)),
                                     TestCurve(self.m, profile))

    def test_two_lifts_have_no_pi_no_refinement_or_final_settle_wait(self):
        scheduler = self.scheduler()
        self.assertFalse(scheduler.release.enabled)
        self.assertFalse(scheduler.controller.enabled)
        self.assertFalse(scheduler.normal_control.enabled)
        self.assertEqual(scheduler.feedback_period, .1)
        outcome = scheduler.run(self.current)
        self.assertEqual(outcome['frames'], 12)
        self.assertEqual(outcome['timing']['refinement_frames_sent'], 0)
        self.assertEqual(outcome['timing']['settle_frames_sent'], 0)
        self.assertEqual(outcome['lift_completion']['endpoint_checks'], 2)
        self.assertLess(outcome['timing']['elapsed_s'], .29)
        # Five-degree model tilt is recorded and never starts a convergence wait.
        self.assertGreater(outcome['lift_completion']['endpoints'][0]['axis_error_rad'], .05)
        self.assertTrue(outcome['task_complete'])

    def test_lift_endpoint_waits_one_control_tick_before_reading(self):
        scheduler=self.scheduler();original=scheduler._read_positions;sample_times=[]
        def observe(deadline):
            if scheduler.last_command and scheduler.last_command['phase']=='LIFT':
                sample_times.append((scheduler.last_command['t_s'],self.clock[0],scheduler.last_sent))
            return original(deadline)
        with patch.object(scheduler,'_read_positions',observe):
            scheduler.run(self.current)
        for endpoint in (.12,.24):
            samples=[row for row in sample_times if abs(row[0]-endpoint)<1e-8]
            self.assertTrue(any(stamp-sent>=.02-1e-9 for _,stamp,sent in samples))

    def test_changed_documented_signature_stops_before_new_speed_is_written(self):
        profile=documented_profile();scheduler=self.scheduler(profile)
        snapshot=copy.deepcopy(profile['verified_registers'])
        snapshot={int(k):v for k,v in snapshot.items()};snapshot[3]['phase']=8
        with patch('smooth_motion.servo_snapshot',return_value=snapshot):
            with self.assertRaisesRegex(ValueError,'寄存器已变化'):
                scheduler.run(self.current)
        self.assertTrue(all(speed==100 for speed in self.p.speeds.values()))

    def test_documented_profile_is_read_back_and_preserves_acceleration(self):
        profile=documented_profile();scheduler=self.scheduler(profile)
        self.p.accelerations.update({sid:0 for sid in range(1,6)})
        snapshot={int(k):v for k,v in profile['verified_registers'].items()}
        with patch('smooth_motion.servo_snapshot',return_value=snapshot):
            result=scheduler.run(self.current)
        self.assertTrue(result['task_complete'])
        self.assertTrue(all(self.p.speeds[sid]==700 for sid in range(1,6)))
        self.assertFalse(any(p[4]==0x83 and p[5]==41 for p in self.p.writes))

    def test_stuck_lift_faults_before_any_following_travel(self):
        original = self.p.write
        def stuck(packet):
            old = self.p.positions[3]; result = original(packet)
            if packet[4] == 0x83: self.p.positions[3] = old
            return result
        self.p.write = stuck
        scheduler = self.scheduler()
        with self.assertRaisesRegex(RuntimeError, '不足 2 mm'):
            scheduler.run(self.current)
        self.assertFalse(any(e[0]=='FRAME_SMOOTH' and e[1]['phase']=='TRAVEL' for e in self.events))
        self.assertLess(self.clock[0], .2)

    def test_warning_policy_continues_all_frames_on_low_lift_and_marks_quality(self):
        self.m['execution']['lift_endpoint_policy']='warn_continue'
        original=self.p.write
        def stuck(packet):
            old=self.p.positions[3];answer=original(packet)
            if packet[4]==0x83:self.p.positions[3]=old
            return answer
        self.p.write=stuck
        result=self.scheduler().run(self.current)
        self.assertTrue(result['execution_finished'])
        self.assertFalse(result['task_complete'])
        self.assertTrue(result['quality_warning'])
        self.assertEqual(result['quality_guard_policy'],'warn_continue')
        self.assertEqual(result['frames'],12)
        self.assertTrue(any(e=='FRAME_SMOOTH' and d['phase']=='TRAVEL' for e,d in self.events))
        self.assertEqual(result['lift_completion']['unconfirmed_endpoints'],2)
        self.assertFalse(result['tracking']['tracking_qualified'])

    def test_missing_endpoint_sample_recovers_before_quality_warning(self):
        self.m['execution']['lift_endpoint_policy']='warn_continue'
        scheduler=self.scheduler();original=scheduler._read_positions;missed=[False]
        def read(deadline):
            last=scheduler.last_command
            if last and abs(last['t_s']-.12)<1e-8 and not missed[0]:
                missed[0]=True;return False
            return original(deadline)
        with patch.object(scheduler,'_read_positions',read):result=scheduler.run(self.current)
        self.assertTrue(missed[0]);self.assertTrue(result['execution_finished'])
        self.assertEqual(result['lift_completion']['unconfirmed_endpoints'],0)
        self.assertEqual(result['timing']['feedback_recovery_attempts'],1)
        self.assertEqual(result['timing']['feedback_recovery_successes'],1)

    def test_missing_lift_start_sample_recovers_before_quality_warning(self):
        self.m['execution']['lift_endpoint_policy']='warn_continue'
        scheduler=self.scheduler();original=scheduler._read_positions;missed=[False]
        def read(deadline):
            last=scheduler.last_command
            if last and last['phase']=='DRAW' and not missed[0]:
                missed[0]=True;return False
            return original(deadline)
        with patch.object(scheduler,'_read_positions',read):result=scheduler.run(self.current)
        self.assertTrue(missed[0]);self.assertTrue(result['execution_finished'])
        self.assertEqual(result['lift_completion']['unconfirmed_endpoints'],0)
        self.assertEqual(result['timing']['feedback_recovery_attempts'],1)
        self.assertEqual(result['timing']['feedback_recovery_successes'],1)

    def test_warning_policy_keeps_user_stop(self):
        self.m['execution']['lift_endpoint_policy']='warn_continue'
        scheduler=self.scheduler();scheduler.executor.cancelled=lambda:self.clock[0]>.08
        with self.assertRaisesRegex(RuntimeError,'STOPPED'):scheduler.run(self.current)

    def test_default_policy_is_warning_only(self):
        self.m['execution'].pop('lift_endpoint_policy')
        self.assertTrue(self.scheduler().planned_lift.warn_only)

    def test_usb_round_trips_exceeding_old_six_ms_budget_still_complete(self):
        original=self.p.read
        def usb_read(n):
            self.clock[0]+=.0015  # two reads per joint: five joints take 15ms
            return original(n)
        self.p.read=usb_read
        scheduler=self.scheduler()
        self.assertEqual(scheduler.feedback_budget,.04)
        self.assertEqual(scheduler.stale_limit,.25)
        result=scheduler.run(self.current)
        self.assertTrue(result['task_complete'])
        self.assertEqual(result['timing']['feedback_failures'],0)
        endpoint_ticks=result['lift_completion']['endpoint_checks']*scheduler.period
        self.assertLess(result['timing']['elapsed_s'],2*TestCurve(self.m).duration+endpoint_ticks)
        frames=[d for e,d in self.events if e=='FRAME_SMOOTH']
        starts=[d['write_begin_mono_s'] for d in frames]
        self.assertTrue(all(b-a>=.02-1e-8 for a,b in zip(starts,starts[1:])))

    def test_failed_snapshot_never_refreshes_age_or_publishes_partial_joints(self):
        scheduler=self.scheduler();scheduler.feedback=dict(self.current);scheduler.measured=0.
        original=self.p.read
        def too_slow(n):
            self.clock[0]+=.012
            return original(n)
        self.p.read=too_slow
        self.assertFalse(scheduler._read_positions(self.clock[0]+scheduler.feedback_budget))
        self.assertEqual(scheduler.feedback,self.current)
        self.assertEqual(scheduler.measured,0.)
        detail=next(d for e,d in self.events if e=='FEEDBACK_MISSED')
        self.assertLess(len(detail['completed_ids']),5)
        self.assertGreaterEqual(detail['elapsed_s'],.04)

    def test_repeated_fifty_ms_usb_jitter_recovers_without_skipping_targets(self):
        scheduler=self.scheduler();original=smooth_motion.exchange_deadline
        retry_writes=[];recovered_writes=[];recovered_ids=[]
        def jitter(port,sid,command,deadline):
            value=original(port,sid,command,deadline)
            if command=='position_speed' and sid==1:
                self.clock[0]+=.05
            return value
        original_audit=scheduler.audit.sink
        def audit(event,detail):
            target_writes=sum(packet[4]==0x83 for packet in self.p.writes)
            if event=='FEEDBACK_RETRY':retry_writes.append(target_writes)
            if event=='FEEDBACK_RECOVERED':
                recovered_writes.append(target_writes)
                recovered_ids.append(sorted(detail['complete_ids']))
            original_audit(event,detail)
        scheduler.audit.sink=audit
        with patch('smooth_motion.exchange_deadline',jitter):
            result=scheduler.run(self.current)
        self.assertEqual(scheduler.feedback_budget,.04)
        self.assertEqual(scheduler.feedback_recovery_budget,.1)
        self.assertEqual(scheduler.stale_limit,.25)
        self.assertTrue(result['task_complete'])
        self.assertEqual(result['frames'],12)
        self.assertGreater(result['timing']['feedback_recovery_attempts'],2)
        self.assertEqual(result['timing']['feedback_recovery_attempts'],
                         result['timing']['feedback_recovery_successes'])
        self.assertEqual(retry_writes,recovered_writes)
        self.assertEqual(recovered_ids,[[1,2,3,4,5]]*len(retry_writes))
        misses=[row for event,row in self.events if event=='FEEDBACK_MISSED']
        self.assertEqual(misses[0]['completed_ids'],[1])
        frames=[detail for event,detail in self.events if event=='FRAME_SMOOTH']
        self.assertEqual([round(row['nominal_time_s'],2) for row in frames],
                         [round(k*.02,2) for k in range(1,13)])
        starts=[row['write_begin_mono_s'] for row in frames]
        self.assertTrue(all(b-a>=.02-1e-8 for a,b in zip(starts,starts[1:])))
        self.assertLess(max(row['feedback_age_s'] for event,row in self.events
                            if event=='FEEDBACK_RETRY'),.25)

    def test_retry_partial_groups_never_publish_or_refresh_feedback(self):
        scheduler=self.scheduler();scheduler.feedback=dict(self.current);scheduler.measured=0.
        original=smooth_motion.exchange_deadline
        self.p.positions.update({sid:2050 for sid in self.current})
        def partial(port,sid,command,deadline):
            self.clock[0]+=.005
            if sid==5:raise ProbeError('TIMEOUT','last joint missing')
            return original(port,sid,command,deadline)
        with patch('smooth_motion.exchange_deadline',partial):
            self.assertFalse(scheduler._read_feedback(self.clock[0]+.04))
        self.assertEqual(scheduler.measured,0.)
        self.assertEqual(scheduler.feedback,self.current)
        self.assertEqual(scheduler.timing['feedback_recovery_attempts'],1)
        self.assertEqual(scheduler.timing['feedback_recovery_successes'],0)
        misses=[row for event,row in self.events if event=='FEEDBACK_MISSED']
        self.assertEqual([row['completed_ids'] for row in misses],[[1,2,3,4]]*2)
        self.assertFalse(any(event=='FEEDBACK_RECOVERED' for event,_ in self.events))

    def test_complete_but_late_group_never_refreshes_feedback(self):
        scheduler=self.scheduler();scheduler.feedback=dict(self.current);scheduler.measured=0.
        original=smooth_motion.exchange_deadline
        def late(port,sid,command,deadline):
            value=original(port,sid,command,deadline)
            if sid==5:self.clock[0]=deadline+.001
            return value
        with patch('smooth_motion.exchange_deadline',late):
            self.assertFalse(scheduler._read_positions(.04))
        self.assertEqual(scheduler.measured,0.)
        self.assertEqual(scheduler.feedback,self.current)
        miss=next(row for event,row in self.events if event=='FEEDBACK_MISSED')
        self.assertTrue(miss['complete_but_late'])
        self.assertEqual(miss['completed_ids'],[1,2,3,4,5])
        self.assertIsNone(miss['failed_id'])

    def test_recovery_deadline_cannot_extend_last_full_sample_stale_bound(self):
        scheduler=self.scheduler();scheduler.feedback=dict(self.current);scheduler.measured=0.
        self.clock[0]=.20;deadlines=[]
        def missing(deadline):
            deadlines.append(deadline);self.clock[0]=deadline
            return False
        with patch.object(scheduler,'_read_positions',missing):
            self.assertFalse(scheduler._read_feedback(self.clock[0]+.04))
        np.testing.assert_allclose(deadlines,[.24,.25],atol=1e-12)
        self.assertEqual(scheduler.measured,0.)
        self.assertAlmostEqual(self.clock[0],.25)
        self.assertEqual(scheduler.timing['feedback_recovery_successes'],0)

    def test_manual_cancel_during_recovery_still_stops_before_target_write(self):
        scheduler=self.scheduler();scheduler.feedback=dict(self.current);scheduler.measured=0.
        original=smooth_motion.exchange_deadline;cancelled=[False];calls=[]
        scheduler.executor.cancelled=lambda:cancelled[0]
        def delayed(port,sid,command,deadline):
            calls.append(sid)
            if len(calls)==1:
                self.clock[0]=deadline
                raise ProbeError('TIMEOUT','transient first attempt')
            value=original(port,sid,command,deadline)
            cancelled[0]=True
            return value
        with patch('smooth_motion.exchange_deadline',delayed):
            with self.assertRaisesRegex(RuntimeError,'STOPPED'):
                scheduler._read_feedback(.04)
        self.assertEqual(calls,[1,1])
        self.assertEqual(scheduler.measured,0.)
        self.assertEqual(scheduler.timing['feedback_recovery_successes'],0)
        self.assertFalse(any(packet[4]==0x83 for packet in self.p.writes))

    def test_persistent_feedback_loss_still_stops_within_stale_bound(self):
        self.m['execution']['lift_endpoint_policy']='warn_continue'
        scheduler=self.scheduler();curve=scheduler.curve
        original=curve.sample
        curve.duration=.8;curve.stops=[.8]
        def draw(stamp):
            command=original(0.)
            command.update(t_s=stamp,phase='DRAW',pen_down=True)
            return command
        curve.sample=draw
        def missing(deadline):
            self.clock[0]=max(self.clock[0],deadline)
            return False
        with patch.object(scheduler,'_read_positions',missing):
            with self.assertRaisesRegex(RuntimeError,'反馈已失效'):
                scheduler.run(self.current)
        self.assertLess(scheduler.timing['frames_sent'],20)
        self.assertLessEqual(scheduler.timing['feedback_recovery_attempts'],2)
        self.assertEqual(scheduler.timing['feedback_recovery_successes'],0)
        self.assertLessEqual(self.clock[0],.25+.04+.02+.005)

    def test_missing_endpoint_read_faults_instead_of_waiting(self):
        scheduler = self.scheduler()
        original = scheduler._read_positions
        def missing(deadline):
            if self.clock[0] >= .115: return False
            return original(deadline)
        with patch.object(scheduler, '_read_positions', missing):
            with self.assertRaisesRegex(RuntimeError, '结束位置反馈中断'):
                scheduler.run(self.current)
        self.assertLess(self.clock[0], .2)

    def test_write_outage_has_bounded_retries(self):
        scheduler = self.scheduler(); original = self.p.write
        def missing(packet):
            if packet[4] == 0x83: raise OSError('wire disconnected')
            return original(packet)
        self.p.write = missing
        with self.assertRaisesRegex(RuntimeError, '持续写入失败'):
            scheduler.run(self.current)
        self.assertLess(self.clock[0], .3)

    def test_verified_register_read_failure_never_writes_acceleration(self):
        scheduler = self.scheduler(verified_profile())
        with patch('smooth_motion.servo_snapshot', return_value={}):
            with self.assertRaisesRegex(ValueError, '未完整回读'):
                scheduler.run(self.current)
        self.assertFalse(any(p[4] == 0x83 and p[5] == 41 for p in self.p.writes))

    def test_stale_reused_sample_cannot_complete_lift(self):
        monitor = PlannedLiftMonitor(self.m, LinearModel())
        monitor.begin(self.current, .1, 0)
        end = dict(self.current); end[3] += 5
        with self.assertRaisesRegex(RuntimeError, '新的完整采样'):
            monitor.finish(end, .1, TestCurve(self.m).sample(.12))


class RealPlanVirtualExecutionTests(unittest.TestCase):
    def test_measured_start_alignment_joins_and_executes_v2_prefix(self):
        snapshot = ROOT/'reports/vertical_lift_20261012/machine.before.json'
        if not snapshot.exists(): self.skipTest('historical calibration fixture unavailable')
        m = json.loads(snapshot.read_text(encoding='utf-8'))
        m['execution'].update(vertical_pen_lift=True, buffered_audit=False)
        current = {int(k): v for k, v in m['model']['pen_axis_calibration']['measured_counts'].items()}
        paths = dict(width_mm=10, height_mm=10, paths=[[[4,5],[6,5]], [[4,6],[6,6]]])
        with tempfile.TemporaryDirectory() as folder:
            result, _, _ = planning.build(paths, folder, machine=m, counts=current,
                                          motion_mode='sugar_fast', persist=False)
        self.assertEqual(result.status, 'OK', result.metrics.get('detail'))
        base = MotionCurve(result, m)
        current[1] += 3
        curve, detail = align_start(base, current)
        self.assertTrue(detail['applied'])
        self.assertEqual(curve.prefix.contract['pen_lift_policy'], 'planned_vertical_v2')
        p = DemoPort(); p.positions.update(current)
        clock = [0.]; original = p.write
        def write(packet):
            clock[0] += .00002
            return original(packet)
        p.write = write
        with patch('smooth_motion.time.monotonic', lambda: clock[0]), \
                patch('smooth_motion.time.sleep', lambda dt: clock.__setitem__(0,clock[0]+dt)):
            outcome = SerialMotionScheduler(Executor(p, m), curve).run(current)
        self.assertEqual(outcome['frames'], round(curve.duration/.02))
        self.assertTrue(outcome['task_complete'])
        self.assertEqual(outcome['timing']['refinement_frames_sent'], 0)
        self.assertEqual(sum(e['stroke'] >= 0 for e in outcome['lift_completion']['endpoints']), 2)

    def test_real_quintics_execute_two_strokes_without_old_feedback_release(self):
        m = machine()
        m['execution']['buffered_audit'] = False
        model, paper, q0 = planning.nominal()
        m['model'], m['paper'] = model.config, paper
        current = counts_from_angles(m, q0)
        paths = dict(width_mm=10, height_mm=10, paths=[[[4,5],[6,5]], [[4,6],[6,6]]])
        with tempfile.TemporaryDirectory() as folder:
            result, spec, cfg = planning.build(paths, folder, machine=m, counts=current,
                                               motion_mode='sugar_fast', persist=False)
        self.assertEqual(result.status, 'OK', result.metrics.get('detail'))
        curve = MotionCurve(result, m)
        self.assertEqual(curve.period, .02)
        p = DemoPort(); p.positions.update(current)
        clock = [0.]; original = p.write
        def write(packet):
            clock[0] += .00002
            return original(packet)
        p.write = write
        events = []
        with patch('smooth_motion.time.monotonic', lambda: clock[0]), \
                patch('smooth_motion.time.sleep', lambda dt: clock.__setitem__(0,clock[0]+dt)):
            outcome = SerialMotionScheduler(Executor(p, m, audit=lambda *e: events.append(e)), curve).run(current)
        self.assertEqual(outcome['frames'], len(result.commands))
        self.assertEqual(outcome['lift_completion']['endpoint_checks'], 2)
        self.assertEqual(outcome['timing']['refinement_frames_sent'], 0)
        self.assertEqual(outcome['timing']['settle_frames_sent'], 0)
        self.assertFalse(outcome['measured_release']['enabled'])
        self.assertTrue(outcome['task_complete'])
        self.assertLess(outcome['timing']['elapsed_s'], curve.duration+.2)


if __name__ == '__main__':
    unittest.main()
