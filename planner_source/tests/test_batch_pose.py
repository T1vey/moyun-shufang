import copy
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
from r1a.model import Model
from r1b.cli import preview


ROOT = Path(__file__).resolve().parents[1]


def independent_pose(config, q):
    """Homogeneous matrix chain, independent of Model's compact FK."""
    transform = np.eye(4)
    for offset, axis, angle in zip(config['offsets_m'], config['axes'], q):
        x, y, z = axis
        skew = np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])
        local = np.eye(4)
        local[:3, :3] = (np.cos(angle)*np.eye(3)
            + (1-np.cos(angle))*np.outer(axis, axis) + np.sin(angle)*skew)
        local[:3, 3] = offset
        transform = transform @ local
    transform[:3, 3] += transform[:3, :3] @ config['tool_translation_m']
    return transform


class BatchPoseTests(unittest.TestCase):
    def setUp(self):
        self.model = Model.load(ROOT/'config/nominal_so101.json')

    def assert_batch(self, model, joints):
        batch = model.pose_many(joints)
        expected = np.asarray([independent_pose(model.config, q) for q in joints])
        scalar = np.asarray([model.pose(q) for q in joints])
        np.testing.assert_allclose(batch, expected, atol=3e-15, rtol=0)
        np.testing.assert_allclose(batch, scalar, atol=3e-15, rtol=0)
        return batch

    def test_nominal_random_and_limit_poses(self):
        rng = np.random.default_rng(2056)
        qs = np.vstack((rng.uniform(self.model.limits[:,0], self.model.limits[:,1], (256,5)),
                        self.model.limits.T, np.zeros((1,5))))
        self.assert_batch(self.model, qs)
        self.assert_batch(self.model, qs[:1].tolist())

    def test_custom_calibrated_geometry_and_tool(self):
        rng = np.random.default_rng(2057)
        config = copy.deepcopy(self.model.config)
        axes = rng.normal(size=(5,3))
        config['axes'] = (axes/np.linalg.norm(axes,axis=1)[:,None]).tolist()
        config['offsets_m'] = rng.uniform(-.2,.2,(5,3)).tolist()
        config['tool_translation_m'] = [.032, -.021, .058]
        config['tool_axis_local'] = (np.array([1.,2.,3.])/np.sqrt(14)).tolist()
        self.assert_batch(Model(config), rng.uniform(-5,5,(128,5)))

    def test_empty_batch(self):
        self.assertEqual(self.model.pose_many(np.empty((0,5))).shape, (0,4,4))

    def test_invalid_shape_or_nonfinite_is_rejected(self):
        for qs in ([], [0.]*5, np.zeros((2,4)), np.zeros((2,5,1)),
                   [[0.,0.,0.,0.,np.nan]], [[0.,0.,np.inf,0.,0.]]):
            with self.subTest(shape=np.shape(qs)):
                with self.assertRaises(ValueError):
                    self.model.pose_many(qs)

    def test_preview_preserves_every_draw_sample_and_stroke(self):
        qs = np.array([[.1,-.2,.3,-.1,0.], [.2,-.1,.4,-.2,0.],
                       [.3,-.2,.3,-.3,0.], [.1,-.1,.2,-.1,0.]])
        actual = self.assert_batch(self.model, qs)[:,:3,3]
        targets = [dict(position=(p+[.001,0.,0.]).tolist(), phase='DRAW', stroke=s)
                   for p,s in zip(actual,[0,0,1,1])]
        commands = [dict(q_rad=q.tolist(), pen_down=True, stroke=s)
                    for q,s in zip(qs,[0,0,1,1])]
        commands.insert(2, dict(q_rad=[0.]*5, pen_down=False, stroke=1))
        result = SimpleNamespace(targets=targets,commands=commands,status='OK')
        center=np.array([.2,0.])
        points=np.vstack((np.array([t['position'] for t in targets])[:,:2],actual[:,:2]))
        span=max(float(np.max(np.ptp(points,axis=0))),.02)
        def formatted(points):
            return ' '.join(f'{300+(p[0]-center[0])*400/span:.3f},{280-(p[1]-center[1])*400/span:.3f}'
                            for p in points)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'preview.svg'
            preview(self.model, dict(plane_origin_m=[.2,0.,0.]), result, path)
            svg=path.read_text(encoding='utf-8')
        lines=re.findall(r'<polyline points="([^"]*)".*?stroke="([^"]+)"', svg)
        self.assertEqual(len(lines),4)
        self.assertEqual(lines[0],(formatted([t['position'] for t in targets[:2]]),'#2563eb'))
        self.assertEqual(lines[1],(formatted(actual[:2]),'#ea580c'))
        self.assertEqual(lines[2],(formatted([t['position'] for t in targets[2:]]),'#2563eb'))
        self.assertEqual(lines[3],(formatted(actual[2:]),'#ea580c'))


if __name__ == '__main__':
    unittest.main()
