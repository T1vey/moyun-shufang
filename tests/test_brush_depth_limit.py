"""User-selected brush compression, isolated from contact geometry; no hardware calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from app import State
from calligraphy.presets import (
    BRUSH, MAX_PRESS_MM, STROKES, RADICALS, binding, profile, task, validate_task,
)
from tcb705.config import demo_config
from tcb705.model import ROOT, Model
from tcb705.planner import PHASE, plan
from tcb705.workbench import TCBWorkbench


class BrushDepthLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Force the host-only path even if tests are run on a PYNQ installation.
        self.platform = patch('tcb705.accel_runtime.platform_health',
                              return_value={'faulted': True})
        self.platform.start()
        self.addCleanup(self.platform.stop)
        self.workbench = TCBWorkbench(
            State(self.temp.name), simulation=True,
            profile=ROOT / 'robots/tcb705/profile.armvision_joint.json')

    def test_save_four_mm_only_updates_brush_configuration(self):
        before = copy.deepcopy(self.workbench.machine)
        result = self.workbench.configure_brush(
            {'max_press_mm': 4, 'speed_pct': 5, 'verified': True})
        self.assertEqual(MAX_PRESS_MM, 6)   # new brush, 2026-10-26: 6 mm usable press
        self.assertEqual(result['profile']['max_press_mm'], 4)
        self.assertTrue(result['profile']['verified'])
        self.assertEqual(binding(before), binding(self.workbench.machine))
        # In particular, contact Z, TCP, paper and motion limits must not move.
        self.assertEqual({k: v for k, v in before.items() if k != 'calligraphy'},
                         {k: v for k, v in self.workbench.machine.items()
                          if k != 'calligraphy'})
        saved = json.loads(self.workbench.config_file.read_text(encoding='utf-8'))
        self.assertEqual(saved, self.workbench.machine)
        self.assertFalse(self.workbench.jobs)

    def test_invalid_limit_or_missing_verification_cannot_save(self):
        original = copy.deepcopy(self.workbench.machine)
        for depth in (6.000001, 7, float('nan'), float('inf'), -1, 0, True):
            with self.subTest(depth=depth), self.assertRaises(ValueError):
                self.workbench.configure_brush(
                    {'max_press_mm': depth, 'speed_pct': 5, 'verified': True})
            self.assertEqual(self.workbench.machine, original)
        with self.assertRaises(ValueError):
            self.workbench.configure_brush(
                {'max_press_mm': 4, 'speed_pct': 5, 'verified': False})
        self.assertEqual(self.workbench.machine, original)
        self.assertFalse(self.workbench.jobs)

    def test_profile_and_all_presets_respect_four_mm_bound(self):
        c = demo_config()
        c['calligraphy'] = dict(BRUSH, max_press_mm=4, speed_pct=5,
                               verified=True, calibration_binding=binding(c))
        self.assertTrue(profile(c, require_verified=True)['verified'])
        original = copy.deepcopy(c)
        for key in list(STROKES) + list(RADICALS):
            with self.subTest(module=key):
                generated = task(key, 20, c)
                validate_task(generated, c)
                for depths in generated['calligraphy']['depth_mm']:
                    self.assertTrue(all(0 <= depth <= 4 for depth in depths))
                    self.assertEqual(depths[0], 0)
                    self.assertEqual(depths[-1], 0)
        self.assertEqual(c, original)
        c['calligraphy']['max_press_mm'] = 6.000001   # limit raised to 6 mm for the 2026-10-26 brush
        with self.assertRaises(ValueError):
            profile(c)
        c['calligraphy']['max_press_mm'] = 4
        c['T_flange_tcp'][2][3] += .001
        with self.assertRaises(ValueError):
            profile(c, require_verified=True)

    def test_actual_offline_ik_preserves_pose_and_depth(self):
        c = demo_config()
        c['calligraphy'] = dict(BRUSH, max_press_mm=4, speed_pct=5,
                               verified=True, calibration_binding=binding(c))
        original = copy.deepcopy(c)
        p = task('heng', 20, c)
        with patch('tcb705.accel_runtime.open_accelerator',
                   return_value=(None, 'test: local native IK only')):
            result = plan(p, c)
        draw = result['interval_phase'] == PHASE['DRAW']
        positions = result['geometric_positions'][1:][draw]
        origin = np.array(c['paper']['origin_m'])
        normal = np.cross(c['paper']['x_axis'], c['paper']['y_axis'])
        depths_mm = -(positions - origin).dot(normal) * 1000
        self.assertGreater(len(depths_mm), 20)
        self.assertGreater(depths_mm.max(), 1.5)
        self.assertLessEqual(depths_mm.max(), 4 + 1e-8)
        self.assertGreaterEqual(depths_mm.min(), -1e-8)
        self.assertIsNone(result['metrics']['max_orientation_error_rad'])
        # Check this fixture offline; production no longer measures this error.
        poses=Model(c).fk_batch(result['q_rad'])
        rotation=np.asarray(c['tool_rotation'])
        angles=np.arccos(np.clip((np.einsum('nij,ij->n',poses[:,:3,:3],rotation)-1)/2,-1,1))
        self.assertLess(float(angles.max()),c['planning']['orientation_tolerance_rad'])
        self.assertEqual(c, original)


if __name__ == '__main__':
    unittest.main()
