"""Execution preparation parity and cache invalidation; fake controller only."""
import copy
import unittest
from unittest.mock import patch
import numpy as np
import test_tcb705_web as fixtures
from tcb705.model import Model, rpy_matrix
from tcb705 import web_executor as W


class PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.WebExecutorTests.setUpClass()
        cls.fixture = fixtures.WebExecutorTests()

    @classmethod
    def tearDownClass(cls):
        fixtures.WebExecutorTests.tearDownClass()

    def test_native_matches_reference_for_mapping_base_phases_and_stops(self):
        cfg, _, _ = self.fixture.fake('joint')
        if not Model(cfg).native_joint_preparation:
            self.skipTest('rebuild CPU core to test native preparation')
        rng = np.random.default_rng(705)
        for transformed in (False, True):
            c = copy.deepcopy(cfg)
            if transformed:
                c['sdk_mapping'] = dict(sdk_to_model_index=[6, 2, 4, 0, 5, 1, 3],
                                        sign=[-1, 1, -1, 1, 1, -1, 1],
                                        offset_rad=[.1, -.2, .05, 0, .1, 0, -.1])
                base = np.eye(4);base[:3, :3] = rpy_matrix([.1, -.2, .3])
                base[:3, 3] = [.03, -.02, .01]
                c['T_controller_base_from_model'] = base.tolist()
            model = Model(c)
            q0 = np.asarray(c['q_start_rad'])
            q = q0 + np.cumsum(rng.normal(0, .0004, (90, 7)), axis=0)
            nodes = dict(positions_m=model.fk_batch(q)[:, :3, 3].tolist(),
                         sdk_degrees=[model.to_sdk(row) for row in q],
                         interval_phase=([W.PHASE['DRAW']]*30 + [W.PHASE['TRAVEL']]*30 +
                                         [W.PHASE['LOWER']]*29), stops=[17, 38, 57, 73])
            for tol in (.005, .05, .5):
                s = dict(W.settings(c), joint_merge_tolerance_mm=tol)
                keep = W._joint_merge_candidates(c, nodes, s)
                error = W.joint_block_error(c, nodes, keep)
                model.native_joint_preparation = False
                with patch.object(W, 'Model', return_value=model):
                    self.assertEqual(keep, W._joint_merge_candidates(c, nodes, s))
                    np.testing.assert_allclose(error, W.joint_block_error(c, nodes, keep),
                                               atol=1e-10, rtol=0)
                model.native_joint_preparation = True

    def test_cached_execution_skips_geometry_but_keeps_live_checks(self):
        cfg, ctrl, clock = self.fixture.fake('joint')
        prepared = W.prepare_joint(cfg, self.fixture.nodes)
        with patch.object(W, 'joint_merge', side_effect=AssertionError('unexpected recompute')):
            result = W.execute(self.fixture.tmp.name, cfg, controller=ctrl,
                               clock=clock, sleep=clock.sleep, prepared=prepared)
        self.assertEqual(result['status'], 'DONE')
        self.assertTrue(result['preparation']['cached'])
        self.assertIn('login', ctrl.calls)
        cfg, ctrl, clock = self.fixture.fake('joint')
        ctrl.active_alarms = lambda: ['test alarm']
        with self.assertRaises(W.ExecutionError):
            W.execute(self.fixture.tmp.name, cfg, controller=ctrl,
                      clock=clock, sleep=clock.sleep, prepared=prepared)
        self.assertNotIn('power_auto', ctrl.calls)

    def test_invalidation_covers_geometry_and_execution_tolerances(self):
        cfg, _, _ = self.fixture.fake('joint')
        key = W.preparation_key(cfg, self.fixture.nodes)
        for field in ('joint_merge_tolerance_mm', 'joint_air_merge_tolerance_mm',
                      'joint_max_block_mm', 'joint_draw_tolerance_mm', 'joint_air_tolerance_mm'):
            changed = copy.deepcopy(cfg)
            changed['execution']['web_program'][field] = W.settings(cfg)[field] * .9
            self.assertNotEqual(key, W.preparation_key(changed, self.fixture.nodes))
        for field in ('positions_m', 'sdk_degrees'):
            changed = copy.deepcopy(self.fixture.nodes);changed[field][1][0] += .001
            self.assertNotEqual(key, W.preparation_key(cfg, changed))
        changed = copy.deepcopy(self.fixture.nodes);changed['stops'] = [1]
        self.assertNotEqual(key, W.preparation_key(cfg, changed))
        changed = copy.deepcopy(cfg);changed['T_flange_tcp'][0][3] += .001
        self.assertNotEqual(key, W.preparation_key(changed, self.fixture.nodes))

    def test_changed_tolerance_recomputes_and_speed_rebuilds_blocks(self):
        cfg, ctrl, clock = self.fixture.fake('joint')
        prepared = W.prepare_joint(cfg, self.fixture.nodes)
        cfg['execution']['web_program']['joint_merge_tolerance_mm'] = .01
        with patch.object(W, 'prepare_joint', wraps=W.prepare_joint) as compute:
            result = W.execute(self.fixture.tmp.name, cfg, controller=ctrl,
                               clock=clock, sleep=clock.sleep, prepared=prepared)
            self.assertEqual(compute.call_count, 1)
        self.assertFalse(result['preparation']['cached'])
        cfg, ctrl, clock = self.fixture.fake('joint')
        cfg['execution']['web_program'].update(draw_speed_pct=13, air_speed_pct=17)
        result = W.execute(self.fixture.tmp.name, cfg, controller=ctrl,
                           clock=clock, sleep=clock.sleep, prepared=prepared)
        self.assertTrue(result['preparation']['cached'])
        speeds = {b['code']['speed'] for p in ctrl.programs
                  for b in p['programs'][0]['codeBlock'] if b['fc'] != 'end'}
        self.assertEqual(speeds, {13, 17})

    def test_cancel_before_power_with_valid_cache(self):
        cfg, ctrl, clock = self.fixture.fake('joint')
        prepared = W.prepare_joint(cfg, self.fixture.nodes)
        with self.assertRaises(W.CancelledByUser):
            W.execute(self.fixture.tmp.name, cfg, controller=ctrl, clock=clock,
                      sleep=clock.sleep, prepared=prepared, cancel=lambda: True)
        self.assertNotIn('power_auto', ctrl.calls)


if __name__ == '__main__':
    unittest.main()
