"""复位: standalone return to the calibrated home pose (fake controller and pipeline, no hardware)."""
import copy
import math
import tempfile
import unittest

from tcb705 import web_executor as W
from tests import test_tcb705_web as web
from tests.test_text_calligraphy import FakePipeline
from user_gui.workflow import Workflow


class ReturnHomeTests(unittest.TestCase):
    setUpClass = web.WebExecutorTests.__dict__['setUpClass']
    tearDownClass = web.WebExecutorTests.__dict__['tearDownClass']
    fake = web.WebExecutorTests.fake
    home_fake = web.WebExecutorTests.home_fake

    def run_home(self, cfg, ctrl, clock, **kw):
        return W.return_home(cfg, controller=ctrl, clock=clock, sleep=clock.sleep, **kw)

    def test_goes_home_and_restores(self):
        cfg, ctrl, clock = self.home_fake()
        result = self.run_home(cfg, ctrl, clock)
        self.assertEqual(result['status'], 'DONE'); self.assertEqual(result['kind'], 'home')
        self.assertIn('HOME_DONE', [e['event'] for e in result['log']])
        self.assertLess(math.dist(ctrl.p[:3], self.mm[0]), 0.6)
        self.assertEqual(ctrl.calls[:2], ['login', 'power_auto'])
        self.assertEqual(ctrl.calls[-1], 'restore'); self.assertNotIn('stop', ctrl.calls)
        first = ctrl.programs[0]['programs'][0]['codeBlock'][0]
        self.assertGreaterEqual(first['code']['endp'][2], self.mm[0][2] - 6.0 - 1e-3)   # first move only rises

    def test_back_to_back_runs_stay_in_auto(self):
        # end_mode 'auto' (2026-10-28): the next run starts in auto and must not switch again.
        cfg, ctrl, clock = self.home_fake()
        first = web.WebExecutorTests.run_exec(self, cfg, ctrl, clock)
        self.assertEqual(first['status'], 'DONE'); self.assertEqual(ctrl.mode, 'auto')
        for run in (lambda: web.WebExecutorTests.run_exec(self, cfg, ctrl, clock),
                    lambda: self.run_home(cfg, ctrl, clock)):
            ctrl.calls.clear()
            self.assertEqual(run()['status'], 'DONE')
            self.assertNotIn('power_auto', ctrl.calls); self.assertNotIn('power_manual', ctrl.calls)
            self.assertEqual(ctrl.mode, 'auto')

    def test_alarm_refuses_before_power(self):
        cfg, ctrl, clock = self.home_fake()
        ctrl.active_alarms = lambda: ['E-STOP']
        with self.assertRaisesRegex(W.ExecutionError, '报警或急停'):
            self.run_home(cfg, ctrl, clock)
        self.assertNotIn('power_auto', ctrl.calls)

    def test_low_pen_in_manual_is_refused_when_strict(self):
        cfg, ctrl, clock = self.home_fake(offset=(0.0, 0.0, -40.0))
        with self.assertRaisesRegex(W.ExecutionError, 'LOW_START'):
            self.run_home(cfg, ctrl, clock, force=False)
        self.assertNotIn('power_auto', ctrl.calls)

    def test_forced_home_lifts_a_low_pen_in_manual(self):
        # 强制复位 (2026-10-29): no LOW_START refusal and no paper calibration needed.
        cfg, ctrl, clock = self.home_fake(offset=(0.0, 0.0, -40.0))
        cfg = dict(cfg, calibration_verified=False)
        result = self.run_home(cfg, ctrl, clock)
        events = [e['event'] for e in result['log']]
        self.assertEqual(result['status'], 'DONE')
        self.assertIn('HOME_FORCE_LOW', events); self.assertIn('HOME_DONE', events)
        self.assertIn('power_auto', ctrl.calls)
        self.assertLess(math.dist(ctrl.p[:3], self.mm[0]), 0.6)
        first = ctrl.programs[0]['programs'][0]['codeBlock'][0]['code']['endp']
        self.assertGreaterEqual(first[2], self.mm[0][2] - 6.0 - 1e-3)   # first move only rises

    def test_low_pen_already_in_auto_is_lifted(self):
        cfg, ctrl, clock = self.home_fake(offset=(0.0, 0.0, -40.0))
        ctrl.mode = 'auto'
        result = self.run_home(cfg, ctrl, clock)
        events = [e['event'] for e in result['log']]
        self.assertIn('HOME_KEEP_AUTO', events); self.assertIn('HOME_DONE', events)
        self.assertNotIn('power_auto', ctrl.calls)

    def test_stop_while_homing(self):
        cfg, ctrl, clock = self.home_fake(offset=(60.0, -40.0, 20.0))
        seen = []
        def cancel():
            return any(e.get('event') == 'HOME_START' for e in seen) and ctrl.running and clock() > ctrl.t0 + 0.5
        with self.assertRaises(W.CancelledByUser):
            self.run_home(cfg, ctrl, clock, cancel=cancel, progress=seen.append)
        self.assertIn('stop', ctrl.calls); self.assertEqual(ctrl.calls[-1], 'restore')

    def test_needs_a_calibrated_home(self):
        cfg, ctrl, clock = self.fake('joint')
        with self.assertRaisesRegex(W.ExecutionError, 'HOME_NOT_CONFIGURED'):
            self.run_home(cfg, ctrl, clock)
        self.assertEqual(ctrl.calls, [])


class HomePipeline(FakePipeline):
    def return_home(self, cancelled, progress=None):
        self.calls.append(('home',))
        return dict(result=dict(status='DONE', simulation=False))


class HomeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.p = HomePipeline(); self.w = Workflow(self.p, self.tmp.name)

    def test_confirmed_reset_completes(self):
        with self.assertRaises(ValueError):
            self.w.home_arm('home_request1', None)
        self.assertEqual(self.p.calls, [])
        s = self.w.home_arm('home_request2', True)
        self.assertEqual(s['module'], 'home')
        self.w.worker.join(10)
        self.assertEqual(self.p.calls, [('home',)])
        self.assertEqual(self.w.state['phase'], 'completed'); self.assertEqual(self.w.state['message'], '机械臂已复位')

    def test_forced_reset_ignores_a_stuck_state(self):
        # 强制复位 (2026-10-29): a picture waiting to start or an unclear motion state no longer blocks it.
        self.w._set(phase='error', motion_uncertain=True, can_cancel=True)
        self.w._occupied = True
        self.w.home_arm('home_request3', True)
        self.w.worker.join(10)
        self.assertEqual(self.p.calls, [('home',)])
        self.assertEqual(self.w.state['phase'], 'completed'); self.assertFalse(self.w.state['motion_uncertain'])

    def test_reset_refused_while_the_board_moves(self):
        self.p.busy = lambda: True
        with self.assertRaisesRegex(RuntimeError, '停止'):
            self.w.home_arm('home_request4', True)
        self.assertEqual(self.p.calls, [])


if __name__ == '__main__':
    unittest.main()
