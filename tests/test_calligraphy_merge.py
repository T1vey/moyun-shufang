"""Merged brush execution: real offline IK and deliberately invalid shortcuts."""
import copy
import unittest
from unittest.mock import patch

import numpy as np

from calligraphy import execution as E
from calligraphy.presets import BRUSH, VERSION, binding, profile, task
from tcb705 import web_executor as W
from tcb705.artifact import nodes_of
from tcb705.config import demo_config, load
from tcb705.model import Model, ROOT
from tcb705.planner import plan


class CurvedModel:
    """Nonlinear joint coupling: original nodes are legal, shortcuts may not be."""
    def __init__(self, kind):
        self.kind = kind

    def from_sdk(self, values):
        return np.asarray(values)

    def fk_batch(self, q):
        q = np.asarray(q); error = q[:, 1]-q[:, 0]**2
        p = np.tile(np.eye(4), (len(q), 1, 1))
        p[:, :3, 3] = np.column_stack((.01+q[:, 0]*.01, q[:, 0]*0+.01,
                                      q[:, 0]*0-.001))
        if self.kind == 'orientation':
            angle = error*.02
            p[:, 0, 0] = p[:, 1, 1] = np.cos(angle)
            p[:, 0, 1] = -np.sin(angle); p[:, 1, 0] = np.sin(angle)
        elif self.kind == 'depth':
            p[:, 2, 3] = -.00395-error*.002
        elif self.kind == 'paper':
            p[:, 0, 3] = .00005-error*.001
            p[:, 1, 3] = .01+q[:, 0]*.01
        elif self.kind == 'pressure':
            p[:, 2, 3] = -.001+q[:, 2]
        return p


class BrushMergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c = load(ROOT/'robots/tcb705/profile.armvision_joint.json')
        c['calligraphy'] = dict(BRUSH, max_press_mm=4., verified=True,
                               calibration_binding=binding(c))
        m = Model(c)
        q = m.from_sdk(c['execution']['web_program']['home']['joint_degrees'])
        with patch('tcb705.accel_runtime.open_accelerator', return_value=(None, 'offline test')):
            cls.result = plan(task('heng', 40, c), c, q)
        cls.config = c; cls.nodes = nodes_of(cls.result)

    def test_real_forty_mm_horizontal_merges_verified_blocks(self):
        c, n = self.config, self.nodes
        before = copy.deepcopy(n)
        prepared = W.prepare_joint(c, n)
        self.assertEqual(len(n['positions_m']), 558)
        self.assertEqual((prepared.keep[0], prepared.keep[-1]), (0, 557))
        self.assertLess(len(prepared.keep), 558 // 4)        # far fewer stop-and-go SDK moves
        self.assertEqual(prepared.error_mm, (None, None))
        self.assertTrue(set(n['stops']).issubset(prepared.keep))
        for a, b in zip(prepared.keep[:-1], prepared.keep[1:]):
            self.assertEqual(len(set(n['interval_phase'][a:b])), 1)
        E.check_geometry(c, n, Model(c), prepared.keep)
        self.assertEqual(n, before)

    def test_native_and_python_candidates_result_in_same_valid_brush_blocks(self):
        c, n = self.config, self.nodes
        expected = W.joint_merge(c, n, W.settings(c))
        model = Model(c); model.native_joint_preparation = False
        with patch.object(W, 'Model', return_value=model):
            self.assertEqual(W.joint_merge(c, n, W.settings(c)), expected)

    def test_loose_requested_draw_merge_keeps_brush_precision(self):
        c = copy.deepcopy(self.config)
        c['execution']['web_program']['joint_merge_tolerance_mm'] = .5
        actual = W.prepare_joint(c, self.nodes)
        self.assertEqual(actual.keep, W.prepare_joint(self.config, self.nodes).keep)  # still capped at 0.02 mm
        E.check_geometry(c, self.nodes, Model(c), actual.keep)

    def test_preparation_cache_tracks_algorithm_but_not_gui_speed(self):
        c, n = self.config, self.nodes
        key = W.preparation_key(c, n)
        with patch.object(E, 'MERGE_VERSION', 'changed-algorithm'):
            self.assertNotEqual(key, W.preparation_key(c, n))
        changed = copy.deepcopy(c)
        changed['execution']['web_program']['draw_speed_pct'] = 47
        self.assertEqual(key, W.preparation_key(changed, n))

    @staticmethod
    def curved(kind):
        c = demo_config()
        c['paper'].update(origin_m=[0, 0, 0], x_axis=[1, 0, 0], y_axis=[0, 1, 0],
                          width_mm=100, height_mm=100)
        c['tool_rotation'] = np.eye(3).tolist()
        c['calligraphy'] = dict(BRUSH, max_press_mm=4., verified=True,
                               calibration_binding=binding(c))
        m = CurvedModel(kind); q = np.zeros((11, 7)); q[:, 0] = np.linspace(0., 1., 11)
        q[:, 1] = q[:, 0]**2
        if kind == 'pressure':
            q[5, 2] = -.00008  # small, but meaningful, depth peak between matching endpoints
        n = dict(positions_m=m.fk_batch(q)[:, :3, 3].tolist(), sdk_degrees=q.tolist(),
                 interval_phase=[W.PHASE['DRAW']]*10, interval_feed_ratio=[1.]*10, stops=[0, 10],
                 calligraphy=dict(module='heng', version=VERSION, brush=profile(c)))
        return c, n, m

    def test_orientation_depth_and_paper_shortcuts_split_instead_of_rejecting_plan(self):
        for kind, message in [('orientation', 'BRUSH_ORIENTATION'), ('depth', 'BRUSH_DEPTH'),
                              ('paper', 'BRUSH_PAPER')]:
            with self.subTest(kind=kind):
                c, n, m = self.curved(kind)
                E.check_geometry(c, n, m)  # original fine nodes are legal
                with self.assertRaisesRegex(ValueError, message):
                    E.check_geometry(c, n, m, [0, 10])
                keep = E.refine_merged(c, n, m, [0, 10], W.settings(c))
                self.assertGreater(len(keep), 2)
                E.check_geometry(c, n, m, keep)

    def test_small_pressure_peak_is_not_shortcut_and_boundaries_are_retained(self):
        c, n, m = self.curved('pressure')
        keep = E.refine_merged(c, n, m, [0, 10], W.settings(c))
        self.assertIn(5, keep)
        n['stops'].append(3)
        n['interval_phase'][7:] = [W.PHASE['LIFT']]*3
        keep = E.refine_merged(c, n, m, [0, 10], W.settings(c))
        self.assertIn(3, keep); self.assertIn(7, keep)

    def test_invalid_original_interval_remains_rejected(self):
        c, n, m = self.curved('orientation')
        q = np.asarray(n['sdk_degrees']); q[:, 1] += 1.
        n['sdk_degrees'] = q.tolist()
        with self.assertRaisesRegex(ValueError, 'BRUSH_ORIENTATION'):
            E.refine_merged(c, n, m, [0, 10], W.settings(c))


if __name__ == '__main__':
    unittest.main()
