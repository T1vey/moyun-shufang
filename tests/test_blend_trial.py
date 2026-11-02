"""smooth 4 trial (2026-10-29): one switch in tcb705/blend.py, and TRIAL = False restores the old values."""
import types
import unittest
from pathlib import Path

from tcb705 import blend


def load(trial):
    src = Path(blend.__file__).read_text(encoding='utf-8').replace('TRIAL = True', 'TRIAL = %s' % trial, 1)
    mod = types.ModuleType('blend_copy'); exec(compile(src, blend.__file__, 'exec'), mod.__dict__)
    return mod


class BlendTrialTests(unittest.TestCase):
    def test_trial_blends_every_feature_at_4(self):
        b = load(True)
        for d in (b.PERFORMANCE_BLEND, b.PAGE_BLEND, b.HANDWRITING_BLEND):
            self.assertEqual(d['smooth'], 4); self.assertTrue(d['draw_only'])
        self.assertEqual(b.LINEART_SMOOTH, 4); self.assertEqual(b.QUEUE_DEPTH, 4)
        self.assertEqual(b.HANDWRITING_BLEND['corner_deg'], 20.0)

    def test_switching_off_restores_the_values_before_the_trial(self):
        b = load(False)
        self.assertEqual(b.PERFORMANCE_BLEND, dict(smooth=3, corner_deg=45.0, draw_only=True))
        self.assertEqual(b.HANDWRITING_BLEND, dict(smooth=3, corner_deg=20.0, draw_only=True))
        self.assertIsNone(b.PAGE_BLEND); self.assertIsNone(b.LINEART_SMOOTH)

    def test_features_read_the_switch(self):
        from tcb705 import workbench
        from handwriting import executor
        self.assertIs(workbench.PERFORMANCE_BLEND, blend.PERFORMANCE_BLEND)
        self.assertIs(executor.BLEND, blend.HANDWRITING_BLEND)
        self.assertEqual(workbench.PAGE_BLEND, blend.PAGE_BLEND)


if __name__ == '__main__':
    unittest.main()
