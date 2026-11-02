"""Kinematic fit recovers a known sign/offset/base/TCP mapping from synthetic samples."""
import copy
import math
import unittest

import numpy as np
from tcb705.config import demo_config, validate
from tcb705.model import Model, rpy_matrix
from tcb705 import kinematic_fit as K


def rigid(xyz, rpy):
    t = np.eye(4); t[:3, :3] = rpy_matrix(rpy); t[:3, 3] = xyz; return t


def uvw(r):
    p = math.asin(-r[2, 0]); return [math.degrees(math.atan2(r[2, 1], r[2, 2])), math.degrees(p), math.degrees(math.atan2(r[1, 0], r[0, 0]))]


class KinematicFitTests(unittest.TestCase):
    def test_recovers_mapping_and_validates(self):
        base_cfg = demo_config()
        truth = copy.deepcopy(base_cfg)
        truth['sdk_mapping']['sign'] = [1, -1, 1, -1, 1, 1, -1]
        truth['sdk_mapping']['offset_rad'] = [0.02, -0.4, 0.0, 0.3, -0.01, 0.25, 0.1]
        truth['T_controller_base_from_model'] = rigid([-0.3, 0.02, 0.11], [0.0, 0.0, math.pi]).tolist()
        truth['T_flange_tcp'] = rigid([0.002, -0.001, 0.12], [0.0, 0.0, 0.0]).tolist()
        validate(truth); model = Model(truth)
        rng = np.random.default_rng(3); q0 = np.array(model.to_sdk(base_cfg['q_start_rad']))
        samples = []
        while len(samples) < 18:
            qd = q0 + rng.uniform(-8, 8, 7)
            qm = model.from_sdk(qd)
            if not model.legal(qm):
                continue
            T = model.fk(qm)
            samples.append(dict(joint_degrees=qd.tolist(), world_mm_deg=(T[:3, 3] * 1000).tolist() + uvw(T[:3, :3])))
        result = K.fit(base_cfg, samples, signs=truth['sdk_mapping']['sign'])
        self.assertTrue(result['accepted'], result)
        self.assertLess(result['holdout_max_mm'], 0.01)
        applied = K.apply(base_cfg, result); validate(applied)
        m2 = Model(applied)
        for s in samples:
            T = m2.fk(m2.from_sdk(s['joint_degrees']))
            np.testing.assert_allclose(T[:3, 3] * 1000, s['world_mm_deg'][:3], atol=0.01)

    def test_rejects_poor_spread_and_noise(self):
        cfg = demo_config(); model = Model(cfg); q0 = np.array(model.to_sdk(cfg['q_start_rad']))
        flat = [dict(joint_degrees=q0.tolist(), world_mm_deg=[0, 0, 0, 0, 0, 0])] * 12
        with self.assertRaisesRegex(ValueError, '4 度'):
            K.fit(cfg, flat)
        with self.assertRaises(ValueError):
            K.apply(cfg, dict(accepted=False))


if __name__ == '__main__':
    unittest.main()


class GeometryFitTests(unittest.TestCase):
    def test_link_geometry_corrections_recovered(self):
        base_cfg = demo_config()
        truth = copy.deepcopy(base_cfg)
        truth['sdk_mapping']['sign'] = [1, 1, 1, 1, 1, 1, 1]
        truth['sdk_mapping']['offset_rad'] = [0.0, 0.0, 0.0, -math.pi / 2, 0.0, -math.pi / 2, 0.0]
        truth['T_controller_base_from_model'] = rigid([-0.2, 0.0, 0.16], [0.0, 0.0, math.pi]).tolist()
        truth['T_flange_tcp'] = rigid([0.0, 0.0, 0.12], [0.0, 0.0, 0.0]).tolist()
        xyz = np.zeros((7, 3)); rpy = np.zeros((7, 3))
        xyz[1] = [0.0015, -0.001, 0.002]; xyz[3] = [-0.002, 0.0, 0.0012]; xyz[5] = [0.0, 0.0018, -0.001]
        rpy[2] = [0.003, -0.002, 0.0]
        truth['model_corrections'] = dict(origin_xyz_m=xyz.tolist(), origin_rpy_rad=rpy.tolist())
        validate(truth); model = Model(truth)
        rng = np.random.default_rng(11); q0 = np.array(model.to_sdk(base_cfg['q_start_rad'])); samples = []
        while len(samples) < 36:
            qd = q0 + rng.uniform(-15, 15, 7); qm = model.from_sdk(qd)
            if not model.legal(qm):
                continue
            T = model.fk(qm)
            samples.append(dict(joint_degrees=qd.tolist(), world_mm_deg=(T[:3, 3] * 1000).tolist() + uvw(T[:3, :3])))
        basic = K.fit(base_cfg, samples, signs=truth['sdk_mapping']['sign'])
        geo = K.fit(base_cfg, samples, signs=truth['sdk_mapping']['sign'], geometry=True)
        self.assertLess(geo['holdout_max_mm'], basic['holdout_max_mm'])
        self.assertTrue(geo['accepted'], geo)
        applied = K.apply(base_cfg, geo); validate(applied); m2 = Model(applied)
        self.assertIn('model_corrections', applied)
        rng2 = np.random.default_rng(5)
        for _ in range(20):  # new poses never used in the fit
            qd = q0 + rng2.uniform(-15, 15, 7); qm = model.from_sdk(qd)
            if not model.legal(qm):
                continue
            np.testing.assert_allclose(m2.fk(m2.from_sdk(qd))[:3, 3] * 1000, model.fk(qm)[:3, 3] * 1000, atol=0.5)

    def test_corrections_are_bounded(self):
        c = demo_config(); c['model_corrections'] = dict(origin_xyz_m=[[0.05, 0, 0]] + [[0, 0, 0]] * 6, origin_rpy_rad=[[0, 0, 0]] * 7)
        with self.assertRaisesRegex(ValueError, '20 mm'):
            Model(c)
