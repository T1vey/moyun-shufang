"""Controlled calligraphy homing with real planned brush nodes and fake SDK hardware."""
import copy
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_tcb705_web import Clock, FakeController
from test_tcb705_sdk import FakeSdk
from calligraphy.presets import BRUSH, binding, task
from tcb705 import web_executor as W
from tcb705.artifact import freeze
from tcb705.config import demo_config
from tcb705.model import Model
from tcb705.planner import plan
from tcb705.sdk_motion import SdkMotion


class BrushHomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c = demo_config()
        c['calibration_verified'] = c['sdk_mapping_verified'] = True
        c['planning']['final_lift_m'] = .06
        model = Model(c); seed = np.array(c['q_start_rad'])
        target = model.fk(seed); target[2, 3] = c['paper']['origin_m'][2] + .08
        solved = model.solve(target, seed, seed)
        if not solved['ok']:
            raise RuntimeError('Cannot construct the high offline test home')
        c['q_start_rad'] = solved['q'].tolist()
        c['execution']['web_program'] = dict(enabled=True, mode='joint', ik_role='execution',
            home=dict(enabled=True, joint_degrees=model.to_sdk(solved['q']), speed_pct=10))
        c['execution']['sdk'] = dict(enabled=True, queue_depth=1)
        c['calligraphy'] = dict(BRUSH, max_press_mm=.3, speed_pct=5, verified=True,
                               calibration_binding=binding(c))
        # Two tools (2026-10-26): the brush is mounted and touches at the paper height here.
        c['calligraphy']['contact_z_mm'] = c['paper']['origin_m'][2] * 1000
        c['mounted_tool'] = 'brush'
        result = plan(task('heng', 20, c), c)
        cls.config = c; cls.frozen = freeze(result, 'real'); cls.nodes = cls.frozen[1]
        cls.mm, _ = W.controller_points(c, cls.nodes)
        cls.prepared = W.prepare_joint(c, cls.nodes)

    def fixture(self):
        c = copy.deepcopy(self.config); clock = Clock()
        positions = {tuple(round(v, 4) for v in q): self.mm[i].tolist()
                     for i, q in enumerate(self.nodes['sdk_degrees'])}
        ctrl = FakeController(clock, self.mm[0].tolist(), self.nodes['sdk_degrees'][0], positions=positions)
        sdk = FakeSdk(ctrl, clock, positions)
        motion = SdkMotion(sdk, ctrl, c, sleep=clock.sleep)
        return c, ctrl, clock, sdk, motion

    def run_motion(self, fixture, events, **kwargs):
        c, ctrl, clock, sdk, motion = fixture
        return W.execute(None, c, controller=ctrl, clock=clock, sleep=clock.sleep,
                         frozen=self.frozen, prepared=self.prepared, motion=motion,
                         progress=events.append, **kwargs)

    @staticmethod
    def after_draw(events, clock):
        start = next((e['t'] for e in events if e['event'] == 'CHUNK_START'), None)
        return start is not None and clock() >= start + .5

    def test_start_and_finish_home_with_ordered_sdk_moves(self):
        f = self.fixture(); events = []; result = self.run_motion(f, events)
        kinds = [e['event'] for e in events]
        self.assertEqual(result['status'], 'DONE')
        self.assertLess(kinds.index('HOME_DONE'), kinds.index('CHUNK_START'))
        self.assertLess(kinds.index('CHUNK_DONE'), kinds.index('RETURN_HOME_DONE'))
        self.assertEqual([m[0] for m in f[3].moves[:3]], ['L', 'L', 'J'])
        self.assertEqual([m[0] for m in f[3].moves[-3:]], ['L', 'L', 'J'])
        self.assertLess(math.dist(f[1].p[:3], self.mm[0]), .6)

    def test_completed_home_can_settle_after_six_seconds_without_replaying_motion(self):
        baseline = self.fixture(); self.run_motion(baseline, [])
        f = self.fixture(); events = []; original_pose = f[1].pose; reads = [0]
        def pose():
            result = original_pose()
            returned = next((e['t'] for e in events if e['event'] == 'RETURN_HOME_DONE'), None)
            if returned is not None and f[2]() - returned < 9.0:
                reads[0] += 1
                result[2] += .1 if reads[0] % 2 else -.1
            return result
        f[1].pose = pose
        result = self.run_motion(f, events)
        self.assertEqual(result['status'], 'DONE'); self.assertFalse(result['restore_deferred'])
        self.assertEqual(f[3].moves, baseline[3].moves)
        sample = [e for e in events if e['event'] == 'RESTORE_SETTLE_SAMPLE'][-1]
        self.assertTrue(sample['settled']); self.assertGreater(sample['elapsed_s'], 6)
        self.assertLess(sample['elapsed_s'], 20)

    def test_segment_wait_reduced_by_one_third_and_feedback_refills_without_sleep(self):
        f = self.fixture(); events = []; trace = []; waits = []
        c, ctrl, clock, sdk, motion = f
        def drawing():
            return any(e['event'] == 'CHUNK_START' for e in events) and not any(
                e['event'] == 'CHUNK_DONE' for e in events)
        original_sleep, original_pose, original_pump = clock.sleep, ctrl.pose, motion.pump
        def sleep(dt):
            waits.append((drawing(), dt)); trace.append('sleep'); original_sleep(dt)
        def pose():
            if drawing(): trace.append('pose')
            return original_pose()
        def pump():
            if drawing(): trace.append('pump')
            return original_pump()
        clock.sleep = sleep; ctrl.pose = pose; motion.pump = pump
        self.assertEqual(self.run_motion(f, events)['status'], 'DONE')
        cadence = next(e for e in events if e['event'] == 'BRUSH_CADENCE')
        self.assertAlmostEqual(cadence['segment_wait_s'], .02 * 2 / 3)
        self.assertTrue(all(abs(dt - .02 * 2 / 3) < 1e-12 for inside, dt in waits if inside))
        self.assertIn((False, .02), waits)  # Homing retains its existing cadence.
        self.assertIn(['pump', 'pose', 'pump', 'sleep'], [trace[i:i+4] for i in range(len(trace)-3)])

    def test_stop_during_feedback_prevents_immediate_refill(self):
        f = self.fixture(); events = []; stopped = [False]; draw_pumps = []
        ctrl, motion = f[1], f[4]; pose, pump = ctrl.pose, motion.pump
        def drawing(): return any(e['event'] == 'CHUNK_START' for e in events)
        def read():
            result = pose()
            if drawing(): stopped[0] = True
            return result
        def refill():
            if drawing(): draw_pumps.append(stopped[0])
            return pump()
        ctrl.pose = read; motion.pump = refill
        with self.assertRaises(W.CancelledByUser):
            self.run_motion(f, events, cancel=lambda: stopped[0], recovery_cancel=lambda: True)
        self.assertEqual(draw_pumps, [False])
        self.assertGreaterEqual(f[3].stops, 1)

    def test_bad_feedback_prevents_immediate_refill(self):
        f = self.fixture(); events = []; draw_pumps = []
        ctrl, motion = f[1], f[4]; pose, pump = ctrl.pose, motion.pump
        def drawing(): return any(e['event'] == 'CHUNK_START' for e in events)
        def read():
            result = list(pose())
            if drawing(): result[2] = float(self.mm[:, 2].min()) - 20
            return result
        def refill():
            if drawing(): draw_pumps.append(True)
            return pump()
        ctrl.pose = read; motion.pump = refill
        with self.assertRaisesRegex(W.ExecutionError, '低于允许下限'):
            self.run_motion(f, events)
        self.assertEqual(draw_pumps, [True])
        self.assertFalse(any(e['event'] == 'HOME_AFTER_STOP_START' for e in events))

    def test_user_stop_returns_home_without_second_mode_switch(self):
        f = self.fixture(); events = []
        with self.assertRaises(W.CancelledByUser):
            self.run_motion(f, events, cancel=lambda: self.after_draw(events, f[2]))
        kinds = [e['event'] for e in events]
        self.assertIn('HOME_AFTER_STOP_DONE', kinds)
        self.assertEqual(f[1].calls.count('power_auto'), 1)
        self.assertLess(math.dist(f[1].p[:3], self.mm[0]), .6)
        home = f[3].moves[-3:]
        self.assertEqual([m[0] for m in home], ['L', 'L', 'J'])
        start = next(e['start'] for e in events if e['event'] == 'HOME_AFTER_STOP_START')
        self.assertEqual(home[0][1][:2], start[:2])
        self.assertGreaterEqual(home[0][1][2], start[2])

    def test_second_stop_aborts_return_and_never_retries(self):
        f = self.fixture(); events = []
        with self.assertRaisesRegex(W.CancelledByUser, '归位未完成'):
            self.run_motion(f, events, cancel=lambda: self.after_draw(events, f[2]),
                            recovery_cancel=lambda: any(e['event'] == 'HOME_AFTER_STOP_START' for e in events))
        kinds = [e['event'] for e in events]
        self.assertEqual(kinds.count('HOME_AFTER_STOP_START'), 1)
        self.assertNotIn('HOME_AFTER_STOP_DONE', kinds)
        self.assertIn('HOME_AFTER_STOP_FAILED', kinds)
        self.assertGreaterEqual(f[3].stops, 2)

    def test_unconfirmed_second_stop_never_reports_cancelled(self):
        for failure in ('failed', 'empty', 'exception'):
            with self.subTest(failure=failure):
                f = self.fixture(); events = []; stop = f[4].stop; count = [0]
                def failed_second_stop():
                    count[0] += 1
                    if count[0] == 1:
                        return stop()
                    if failure == 'exception':
                        raise OSError('no stop reply')
                    if failure == 'empty':
                        return []
                    return [('sdk_clear_route', False, 'no reply'), ('run_key_200', True, '')]
                f[4].stop = failed_second_stop
                with self.assertRaisesRegex(W.ExecutionError, '归位停止未确认') as raised:
                    self.run_motion(f, events, cancel=lambda: self.after_draw(events, f[2]),
                        recovery_cancel=lambda: any(e['event'] == 'HOME_AFTER_STOP_START' for e in events))
                self.assertNotIsInstance(raised.exception, W.CancelledByUser)
                failed = next(e for e in events if e['event'] == 'HOME_AFTER_STOP_FAILED')
                self.assertIs(failed['cancelled_again'], False)
                self.assertIs(failed['stop_confirmed'], False)
                self.assertIn('归位停止未确认', failed['detail'])
                self.assertFalse(any(e['event'] == 'HOME_AFTER_STOP_DONE' for e in events))
                self.assertEqual(count[0], 2)

    def test_motion_fault_does_not_trigger_return(self):
        f = self.fixture(); events = []; original = f[4].pump
        def pump():
            if any(e['event'] == 'CHUNK_START' for e in events):
                raise RuntimeError('SDK_REFUSED: test fault')
            return original()
        f[4].pump = pump
        with self.assertRaisesRegex(W.ExecutionError, 'SDK_REFUSED'):
            self.run_motion(f, events)
        self.assertFalse(any(e['event'] == 'HOME_AFTER_STOP_START' for e in events))
        self.assertGreaterEqual(f[3].stops, 1)

    def test_unknown_or_faulted_stop_state_blocks_return(self):
        for mode in ('unknown', 'alarm', 'servo_off', 'manual', 'stop_failed'):
            with self.subTest(mode=mode):
                f = self.fixture(); events = []; state = f[1].state
                def read_state():
                    if not f[3].stops:
                        return state()
                    if mode == 'unknown':
                        raise OSError('lost state')
                    s = state()
                    if mode == 'alarm': s['_phc_alarm_'] = '1'
                    if mode == 'servo_off': s['g_servo_statero_'] = '0'
                    if mode == 'manual': s['_phc_ctrlkey'] = '200'
                    return s
                f[1].state = read_state
                if mode == 'stop_failed':
                    stop = f[4].stop
                    def failed_stop():
                        return stop() + [('injected_stop_failure', False, 'failed')]
                    f[4].stop = failed_stop
                with self.assertRaisesRegex(W.ExecutionError, 'HOME_AFTER_STOP_FAILED'):
                    self.run_motion(f, events, cancel=lambda: self.after_draw(events, f[2]))
                self.assertFalse(any(e['event'] == 'HOME_AFTER_STOP_START' for e in events))
                self.assertTrue(any(e['event'] == 'HOME_AFTER_STOP_FAILED' for e in events))

    def test_brush_requires_enabled_existing_home_before_motion(self):
        f = self.fixture(); f[0]['execution']['web_program']['home']['enabled'] = False
        with self.assertRaisesRegex(W.ExecutionError, 'BRUSH_HOME_REQUIRED'):
            self.run_motion(f, [])
        self.assertEqual(f[1].calls, [])

    def test_strict_home_joint_read_failure_is_bounded(self):
        f = self.fixture(); c, ctrl, clock, sdk, motion = f; ctrl.mode = 'auto'
        ctrl.joints = lambda n: (_ for _ in ()).throw(OSError('lost joints'))
        with self.assertRaisesRegex(W.ExecutionError, 'HOME_JOINT_FEEDBACK'):
            W.go_home(ctrl, c, W.settings(c), lambda *a, **k: None, lambda: False,
                      clock, clock.sleep, 'TEST_HOME', motion, strict=True)
        self.assertLess(clock(), 1)
        motion.stop()

    def test_strict_home_rejects_alarm_during_return(self):
        f = self.fixture(); c, ctrl, clock, sdk, motion = f; ctrl.mode = 'auto'
        state = ctrl.state
        def failing_state():
            st = state()
            if sdk.moves: st['g_state_'] = '0'
            return st
        ctrl.state = failing_state
        with self.assertRaisesRegex(W.ExecutionError, 'HOME_CONTROLLER_HALTED'):
            W.go_home(ctrl, c, W.settings(c), lambda *a, **k: None, lambda: False,
                      clock, clock.sleep, 'TEST_HOME', motion, strict=True)
        self.assertEqual(len(sdk.moves), 1)
        motion.stop()

    def test_strict_home_rejects_feedback_loss_or_departure(self):
        for failure in ('pose', 'bounds'):
            with self.subTest(failure=failure):
                c, ctrl, clock, sdk, motion = self.fixture(); ctrl.mode = 'auto'
                ctrl.p[2] -= 10  # first rise is still executing when the feedback fails
                pose = ctrl.pose
                def faulty_pose():
                    if sdk.moves and failure == 'pose': raise OSError('lost pose')
                    p = pose()
                    if sdk.moves and failure == 'bounds': p[2] -= 12.0
                    return p
                ctrl.pose = faulty_pose
                with self.assertRaisesRegex(W.ExecutionError, 'HOME_FEEDBACK_INVALID|HOME_BOUNDS'):
                    W.go_home(ctrl, c, W.settings(c), lambda *a, **k: None, lambda: False,
                              clock, clock.sleep, 'TEST_HOME', motion, strict=True)
                self.assertLess(clock(), 1)

    def test_strict_home_no_progress_cannot_wait_forever(self):
        c, ctrl, clock, sdk, motion = self.fixture(); ctrl.mode = 'auto'
        ctrl.p[0] += 5; ctrl.speed = 0
        with self.assertRaisesRegex(W.ExecutionError, 'HOME_STALLED'):
            W.go_home(ctrl, c, W.settings(c), lambda *a, **k: None, lambda: False,
                      clock, clock.sleep, 'TEST_HOME', motion, strict=True)
        self.assertLess(clock(), W.settings(c)['no_progress_s'] + 1)
        motion.stop()

    def test_low_auto_start_homes_without_switching_mode(self):
        f = self.fixture(); events = []; f[1].mode = 'auto'
        f[1].p[2] = f[0]['paper']['origin_m'][2] * 1000 - .2
        result = self.run_motion(f, events)
        self.assertEqual(result['status'], 'DONE')
        kinds = [e['event'] for e in events]
        self.assertIn('HOME_KEEP_AUTO', kinds)
        self.assertLess(kinds.index('HOME_DONE'), kinds.index('CHUNK_START'))
        self.assertNotIn('power_auto', f[1].calls)

    def test_low_manual_start_never_switches_or_moves(self):
        f = self.fixture(); events = []; f[1].mode = 'manual'
        f[1].p[2] = f[0]['paper']['origin_m'][2] * 1000
        with self.assertRaisesRegex(W.ExecutionError, 'MODE_SWITCH_CLEARANCE'):
            self.run_motion(f, events)
        self.assertNotIn('power_auto', f[1].calls)
        self.assertEqual(f[3].moves, [])


class AlarmFeedbackTests(unittest.TestCase):
    def test_strict_alarm_read_distinguishes_empty_and_unknown(self):
        from tcb705.web_control import Controller, ControllerError
        ctrl = object.__new__(Controller)
        for response in ({}, {'data': None}, {'data': {}}, {'data': [None]},
                         {'data': [{}]}, {'data': [{'history': False}]}, {'data': [{'history': 'unknown'}]}):
            with self.subTest(response=response):
                ctrl.request = lambda path: response
                with self.assertRaises(ControllerError): ctrl.strict_active_alarms()
        ctrl.request = lambda path: {'data': []}
        self.assertEqual(ctrl.strict_active_alarms(), [])
        ctrl.request = lambda path: {'data': [{'history': '1'}, {'history': 0, 'number': 7}]}
        self.assertEqual([v['number'] for v in ctrl.strict_active_alarms()], [7])


if __name__ == '__main__':
    unittest.main()
