"""Batch acceleration preserves mapping and every original brush probe."""
import copy
import unittest
import numpy as np
from tcb705.config import load
from tcb705.model import Model, ROOT
from calligraphy.execution import _Geometry, refine_merged
from tcb705.web_executor import settings
import test_calligraphy_merge as fixtures


class BatchLatencyTests(unittest.TestCase):
    def test_sdk_mapping_is_bit_identical_including_permutation_sign_and_offset(self):
        c = load(ROOT/'robots/tcb705/profile.armvision_joint.json')
        c['sdk_mapping'] = dict(sdk_to_model_index=[6, 2, 4, 0, 5, 1, 3],
                                sign=[-1, 1, -1, 1, 1, -1, 1],
                                offset_rad=[.1, -.2, .05, 0, .1, 0, -.1])
        m = Model(c); rng = np.random.default_rng(705)
        q = rng.normal(size=(123, 7))
        np.testing.assert_array_equal(m.to_sdk_batch(q), [m.to_sdk(row) for row in q])
        np.testing.assert_array_equal(m.from_sdk_batch(q), [m.from_sdk(row) for row in q])
        for bad in ([1]*7, [[0]*6], [[float('nan')]*7], [[float('inf')]*7]):
            with self.assertRaises(ValueError): m.to_sdk_batch(bad)
            with self.assertRaises(ValueError): m.from_sdk_batch(bad)

    def test_cached_checks_preserve_probe_positions_knots_and_failure_codes(self):
        for kind in ('orientation', 'depth', 'paper', 'pressure'):
            c, n, m = fixtures.BrushMergeTests.curved(kind)
            g = _Geometry(c, n, m)
            pairs = [(0, 10), (0, 1), (4, 6), (5, 10)]
            old = [g.samples(a, b) for a, b in pairs]
            def verdict(f):
                try: f(); return None
                except ValueError as e: return str(e)
            expected = [verdict(lambda p=p: g.check(p, 1)) for p, _, _ in old]
            g.prefetch(pairs)
            for i, (a, b) in enumerate(pairs):
                actual = g.samples(a, b)
                for x, y in zip(old[i], actual): np.testing.assert_array_equal(x, y)
                self.assertEqual(expected[i], verdict(lambda: g.check_segment(a, b, actual[0])))

    def test_batching_cannot_merge_a_phase_boundary_or_corner(self):
        c, n, m = fixtures.BrushMergeTests.curved('pressure')
        n['stops'] = [3, 6]; n['interval_phase'][8:] = [2, 2]
        original = copy.deepcopy(n)
        keep = refine_merged(c, n, m, [0, 10], settings(c))
        self.assertTrue({3, 5, 6, 8}.issubset(keep))
        self.assertEqual(n, original)

    def test_mixed_phase_batch_retains_air_contact_guard(self):
        c, n, m = fixtures.BrushMergeTests.curved('pressure')
        n['interval_phase'][5:] = [3]*5
        g = _Geometry(c, n, m); g.prefetch([(0, 4), (5, 10)])
        g.check_segment(0, 4, g.samples(0, 4)[0])
        with self.assertRaisesRegex(ValueError, 'BRUSH_TRAVEL'):
            g.check_segment(5, 10, g.samples(5, 10)[0])


if __name__ == '__main__': unittest.main()
