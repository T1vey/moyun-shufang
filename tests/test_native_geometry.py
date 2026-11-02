"""Optional native acceptance: arbitrary models, all samples and frozen real plan."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import planning
from r1a.model import Model
from r1b.smooth import _measure_rows
from native import geometry


class OptionalLoaderTests(unittest.TestCase):
    def test_missing_library_and_disabled_mode_use_numpy(self):
        model, _, q = planning.nominal()
        with patch.dict(os.environ, SO101_NATIVE_GEOMETRY='off'):
            expected = model.pose_many([q])
        with patch.dict(os.environ, SO101_NATIVE_GEOMETRY='auto', SO101_NATIVE_LIBRARY='missing-no-library.dll'):
            self.assertFalse(geometry.status()['enabled'])
            np.testing.assert_array_equal(model.pose_many([q]), expected)

    def test_smooth_honors_subclass_and_class_pose_override(self):
        base_pose=Model.pose_many
        def changed_pose(model,qs):
            poses=base_pose(model,qs)
            poses[:,:3,3]+=[.012,.034,.056]
            return poses
        class CustomModel(Model):
            pose_many=changed_pose
        coeffs=np.zeros((1,6,5));times=np.ones(1)
        path=(np.zeros((1,3)),np.zeros((1,3)),np.asarray([[0.,0.,1.]]),
              np.asarray([[0.,0.,1.]]),np.zeros(1))
        def check(model):
            with patch('r1b.smooth._native_geometry_rows',side_effect=AssertionError('override bypassed')):
                result=_measure_rows(model,coeffs,times,path,np.asarray([0]),np.asarray([.5]))
            np.testing.assert_array_equal(result[5],changed_pose(model,np.zeros((1,5)))[:,:3,3])
        check(CustomModel(planning.load('nominal_so101.json')))
        model=Model(planning.load('nominal_so101.json'))
        with patch.object(Model,'pose_many',changed_pose):check(model)


class NativeGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, SO101_NATIVE_GEOMETRY='auto'):
            if geometry.get_kernel() is None:
                raise unittest.SkipTest('Build native library with native/build.py before native acceptance')

    def reference(self, action):
        with patch.dict(os.environ, SO101_NATIVE_GEOMETRY='off'):
            return action()

    def accelerated(self, action):
        with patch.dict(os.environ, SO101_NATIVE_GEOMETRY='auto'):
            self.assertIsNotNone(geometry.get_kernel())
            return action()

    def test_arbitrary_calibrated_fk_chunk_boundaries_and_model_refresh(self):
        rng = np.random.default_rng(251011)
        cfg = copy.deepcopy(planning.load('nominal_so101.json'))
        axes = rng.normal(size=(5, 3)); axes /= np.linalg.norm(axes, axis=1)[:, None]
        cfg.update(axes=axes.tolist(), tool_translation_m=[.031, -.022, .073])
        cfg['offsets_m'] = (np.asarray(cfg['offsets_m'])+rng.normal(0, .006, (5, 3))).tolist()
        model = Model(cfg)
        joints = rng.uniform(-2.8, 2.8, (2051, 5))
        expected = self.reference(lambda: model.pose_many(joints))
        actual = self.accelerated(lambda: model.pose_many(joints))
        np.testing.assert_allclose(actual, expected, atol=3e-14, rtol=0)
        model.tool[:] += [.001, -.002, .003]
        changed = self.accelerated(lambda: model.pose_many(joints[:2]))
        np.testing.assert_allclose(changed, self.reference(lambda: model.pose_many(joints[:2])), atol=3e-14, rtol=0)
        self.assertGreater(np.max(abs(changed-actual[:2])), .001)
        self.assertEqual(self.accelerated(lambda: model.pose_many(np.empty((0, 5)))).shape, (0, 4, 4))
        with self.assertRaises(ValueError):
            self.accelerated(lambda: model.pose_many([[np.nan]*5]))

    def test_every_geometry_row_matches_zero_short_and_reversing_segments(self):
        rng = np.random.default_rng(73); model, _, _ = planning.nominal()
        n = 2051; q = rng.uniform(-1, 1, (n, 5))
        starts = rng.uniform(-.2, .2, (n, 3)); delta = rng.uniform(-.005, .005, (n, 3))
        delta[::3] = 0.; delta[1::3] *= 1e-9
        desired = starts+.3*delta
        axes = rng.normal(size=(n, 3)); axes /= np.linalg.norm(axes, axis=1)[:, None]
        poses = self.reference(lambda: model.pose_many(q)); actual = poses[:, :3, 3]
        squared = np.einsum('ij,ij->i', delta, delta); valid = squared > 1e-20
        fraction = np.zeros(n)
        fraction[valid] = np.clip(np.einsum('ij,ij->i', actual[valid]-starts[valid], delta[valid])/squared[valid], 0, 1)
        current = poses[:, :3, :3]@model.tool_axis
        expected = (actual, np.linalg.norm(actual-starts-fraction[:, None]*delta, axis=1),
                    np.linalg.norm(actual-desired, axis=1),
                    np.arctan2(np.linalg.norm(np.cross(axes, current), axis=1), np.einsum('ij,ij->i', axes, current)))
        output = self.accelerated(lambda: geometry.geometry_rows(model, q, starts, delta, desired, axes))
        for a, b in zip(output, expected):
            np.testing.assert_allclose(a, b, atol=3e-14, rtol=0)

    def test_authoritative_horner_and_axes_unchanged(self):
        rng = np.random.default_rng(125); model, _, _ = planning.nominal()
        n = 65; coeffs = rng.normal(0, .1, (7, 6, 5)); times = rng.uniform(.1, 2, 7)
        path = (rng.normal(0, .1, (7, 3)), rng.normal(0, .01, (7, 3)),
                np.tile([0., 0., -1.], (7, 1)), np.tile([0., 0., -1.], (7, 1)), np.zeros(7))
        indexes = np.arange(n)%7; u = np.linspace(0, 1, n)
        a = self.reference(lambda: _measure_rows(model, coeffs, times, path, indexes, u))
        b = self.accelerated(lambda: _measure_rows(model, coeffs, times, path, indexes, u))
        for x, y in zip(a[:5], b[:5]):
            np.testing.assert_array_equal(x, y)
        for x, y in zip(a[5:], b[5:]):
            np.testing.assert_allclose(x, y, atol=3e-14, rtol=0)

    def test_frozen_face_plan_all_counts_commands_and_probes_preserved(self):
        from ik_target_backend import NativeIKTarget
        from motion import counts_from_angles, quantized_angles_many
        inputs = ROOT/'reports/planning_acceleration_review_20261011/archived_face_inputs'
        library = ROOT/'build/target_ik/host/ik_target.dll'
        if not (inputs/'machine.json').is_file() or not library.is_file():
            self.skipTest('archived host face fixture unavailable')
        machine, paths, q0 = [json.loads((inputs/(name+'.json')).read_text(encoding='utf-8'))
                              for name in ('machine', 'paths', 'q0')]
        counts = counts_from_angles(machine, q0)
        with tempfile.TemporaryDirectory() as folder:
            def run(name):
                return planning.build(paths, Path(folder)/name, machine, counts,
                                      backend=NativeIKTarget(library), motion_mode='classic_fast')[0]
            before = self.reference(lambda: run('numpy'))
            after = self.accelerated(lambda: run('native'))
        self.assertEqual(before.status, 'OK'); self.assertEqual(after.status, before.status)
        self.assertEqual(before.targets, after.targets)
        self.assertEqual(before.metrics['geometry_samples'], after.metrics['geometry_samples'])
        self.assertEqual(len(before.commands), len(after.commands))
        for a, b in zip(before.commands, after.commands):
            for field in ('q_rad', 't_s', 'phase', 'stroke', 'pen_down', 'path_segment_index',
                          'source_segment_id', 'velocity_rad_s', 'acceleration_rad_s2', 'jerk_rad_s3'):
                self.assertEqual(a.get(field), b.get(field), field)
        qa = np.asarray([c['q_rad'] for c in before.commands])
        qb = np.asarray([c['q_rad'] for c in after.commands])
        np.testing.assert_array_equal(quantized_angles_many(machine, qa), quantized_angles_many(machine, qb))
        for name, value in before.metrics['quantization'].items():
            if isinstance(value, float):
                self.assertAlmostEqual(value, after.metrics['quantization'][name], delta=3e-14)


if __name__ == '__main__':
    unittest.main()
