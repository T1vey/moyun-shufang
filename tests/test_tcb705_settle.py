"""Bounded read-only settling after a completed trajectory, with fake feedback."""
import unittest

from tcb705.config import demo_config
from tcb705.web_control import ControllerError, settle_pose
from tcb705 import web_executor as W


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t
    def sleep(self, seconds): self.t += seconds


class Feedback:
    def __init__(self, clock, height, unstable_until=0.0):
        self.clock = clock; self.height = height; self.unstable_until = unstable_until
        self.reads = 0; self.stops = []; self.restores = 0
        self.alarm_at = float('inf'); self.failure = None; self.read_delay = 0.0

    def run_key(self, value): self.stops.append(value)
    def restore(self, manual=True): self.restores += 1; return [('power_manual', True, '')] if manual else []
    def pose(self):
        self.reads += 1; self.clock.sleep(self.read_delay)
        if self.failure: raise self.failure
        offset = (0.1 if self.reads % 2 else -0.1) if self.clock() < self.unstable_until else 0.0
        return [0.0, 0.0, self.height + offset, 180.0, 0.0, 180.0]
    def state(self):
        return {'_phc_ctrlkey': '100', 'g_state_': '1', 'g_servo_statero_': '1',
                '_phc_alarm_': '1' if self.clock() >= self.alarm_at else '0'}
    def active_alarms(self): return []


class RestoreSettlingTests(unittest.TestCase):
    def fixture(self, unstable_until=0.0, clearance=70.0):
        cfg = demo_config(); clock = Clock()
        ctrl = Feedback(clock, cfg['paper']['origin_m'][2]*1000 + clearance, unstable_until)
        return cfg, ctrl, clock

    def restore(self, fixture):
        cfg, ctrl, clock = fixture; events = []
        ref, steps = W.restore_safe(ctrl, cfg, clock=clock, sleep=clock.sleep,
                                   settle_timeout=W.COMPLETED_RESTORE_SETTLE_S,
                                   note=lambda kind, **kw: events.append(dict(event=kind, **kw)))
        return ref, steps, events

    def test_late_stability_passes_same_tolerance_without_repeating_stop(self):
        f = self.fixture(unstable_until=9.0)
        ref, _, events = self.restore(f)
        self.assertIsNotNone(ref); self.assertEqual(f[1].restores, 1)
        self.assertEqual(f[1].stops, [False])
        self.assertGreater(f[2](), 6); self.assertLess(f[2](), 20)
        final = [e for e in events if e['event'] == 'RESTORE_SETTLE_SAMPLE'][-1]
        self.assertTrue(final['settled']); self.assertEqual(final['tolerance_mm'], .05)
        self.assertEqual(len(final['xyz_samples_mm']), 5)

    def test_already_stable_does_not_wait_for_the_deadline(self):
        f = self.fixture(); ref, _, _ = self.restore(f)
        self.assertIsNotNone(ref); self.assertLess(f[2](), 2)

    def test_persistent_motion_times_out_and_never_restores(self):
        f = self.fixture(unstable_until=float('inf'))
        ref, steps, events = self.restore(f)
        self.assertIsNone(ref); self.assertEqual(f[1].restores, 0)
        self.assertEqual(f[1].stops, [False]); self.assertAlmostEqual(f[2](), 20)
        self.assertIn('静止确认超时', steps[0][2])
        self.assertTrue(events[-1]['timed_out'])
        self.assertGreater(events[-1]['window_max_mm'], .05)

    def test_low_stable_feedback_does_not_allow_mode_switch(self):
        f = self.fixture(clearance=59.0); ref, steps, _ = self.restore(f)
        self.assertIsNone(ref); self.assertIn('MODE_SWITCH_CLEARANCE', steps[0][2])
        self.assertEqual(f[1].restores, 0)

    def test_new_alarm_during_wait_prevents_restoration(self):
        f = self.fixture(unstable_until=9.0); f[1].alarm_at = 2.0
        ref, steps, _ = self.restore(f)
        self.assertIsNone(ref); self.assertEqual(f[1].restores, 0)
        self.assertIn('RESTORE_STATE_UNSAFE', steps[0][2]); self.assertLess(f[2](), 3)

    def test_lost_feedback_is_not_retried(self):
        f = self.fixture(); f[1].failure = OSError('feedback lost')
        ref, steps, _ = self.restore(f)
        self.assertIsNone(ref); self.assertEqual(f[1].restores, 0)
        self.assertEqual(f[1].reads, 1); self.assertIn('feedback lost', steps[0][2])

    def test_nonfinite_feedback_is_not_accepted_as_stable(self):
        f = self.fixture(); f[1].height = float('nan')
        ref, steps, _ = self.restore(f)
        self.assertIsNone(ref); self.assertEqual(f[1].restores, 0)
        self.assertIn('位置反馈无效', steps[0][2])

    def test_default_wait_for_failure_cleanup_remains_six_seconds(self):
        cfg, ctrl, clock = self.fixture(unstable_until=float('inf'))
        ref, _ = W.restore_safe(ctrl, cfg, clock=clock, sleep=clock.sleep)
        self.assertIsNone(ref); self.assertAlmostEqual(clock(), 6)
        self.assertEqual(ctrl.restores, 0)

    def test_slow_reads_count_toward_timeout_even_if_last_sample_is_stable(self):
        _, ctrl, clock = self.fixture(); ctrl.read_delay = 1.1
        samples = []
        with self.assertRaisesRegex(ControllerError, '静止确认超时'):
            settle_pose(ctrl, timeout=6, clock=clock, sleep=clock.sleep, observe=samples.append)
        self.assertEqual(ctrl.reads, 5)
        self.assertTrue(samples[-1]['timed_out']); self.assertFalse(samples[-1]['settled'])
        self.assertEqual(samples[-1]['read_s'], 1.1)

    def test_slow_health_reply_cannot_restore_after_deadline(self):
        f = self.fixture(); original_state = f[1].state
        def state():
            if f[1].reads >= 5: f[2].sleep(20)
            return original_state()
        f[1].state = state
        ref, steps, events = self.restore(f)
        self.assertIsNone(ref); self.assertEqual(f[1].restores, 0)
        self.assertIn('静止确认超时', steps[0][2])
        self.assertTrue(events[-1]['timed_out']); self.assertFalse(events[-1]['settled'])


if __name__ == '__main__': unittest.main()
