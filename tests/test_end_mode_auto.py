"""Jobs end in auto mode by default: the auto->manual switch shook the arm at home (2026-10-28)."""
import copy
import unittest

from tcb705.config import demo_config
from tcb705 import web_executor as W
from tcb705.web_control import Controller


class Ctrl:
    def __init__(self, z):
        self.z = z; self.calls = []
    def run_key(self, running): self.calls.append(('run_key', running))
    def pose(self): return [0.0, 0.0, self.z, 180.0, 0.0, 180.0]
    def restore(self, manual=True):
        self.calls.append(('restore', manual)); return []


class EndModeTests(unittest.TestCase):
    def high(self, cfg):
        return Ctrl(cfg['paper']['origin_m'][2] * 1000 + 70.0)

    def test_default_keeps_auto(self):
        cfg = demo_config(); ctrl = self.high(cfg)
        ref, _ = W.restore_safe(ctrl, cfg, clock=lambda: 0.0, sleep=lambda s: None)
        self.assertIsNotNone(ref)
        self.assertIn(('restore', False), ctrl.calls)
        self.assertEqual(W.settings(cfg)['end_mode'], 'auto')

    def test_manual_still_available(self):
        cfg = demo_config(); cfg['execution'].setdefault('web_program', {})['end_mode'] = 'manual'
        ctrl = self.high(cfg)
        W.restore_safe(ctrl, cfg, clock=lambda: 0.0, sleep=lambda s: None)
        self.assertIn(('restore', True), ctrl.calls)

    def test_bad_value_rejected(self):
        cfg = copy.deepcopy(demo_config()); cfg['execution'].setdefault('web_program', {})['end_mode'] = 'off'
        with self.assertRaises(ValueError):
            W.settings(cfg)

    def test_controller_restore_skips_power_manual(self):
        sent = []
        c = Controller.__new__(Controller)
        c.run_key = lambda running: sent.append('run_key')
        c.request = lambda path, data, timeout=None: sent.append(path)
        c.power = lambda mode: sent.append('power_' + mode)
        self.assertEqual([n for n, ok, _ in c.restore(manual=False)], ['run_key_200', 'mold_ArmVision_Draw'])
        self.assertNotIn('power_manual', sent)
        sent.clear(); c.restore()
        self.assertEqual(sent[-1], 'power_manual')


if __name__ == '__main__':
    unittest.main()
