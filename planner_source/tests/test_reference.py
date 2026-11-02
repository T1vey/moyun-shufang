import copy
import json
import unittest
from pathlib import Path
import numpy as np
from r1a.model import Model
from r1a.linear import step, system, independent_wls
from r1a.solve import solve
from r1a.upstream_oracle import chain

ROOT = Path(__file__).resolve().parents[1]


class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = Model.load(ROOT / "config/nominal_so101.json")
        cls.cfg = json.loads((ROOT / "config/contract.json").read_text())
        cls.et = chain()

    def fixture(self):
        rng = np.random.default_rng(20260924)
        return rng.normal(size=(6, 5)), rng.normal(size=6), np.array([0, .1, .4, 1, 2, 4]), np.array([10, 10, 10, 1, 1, 1])

    def target(self, q):
        t, _ = self.model.evaluate(q)
        return t[:3, 3], t[:3, :3] @ self.model.tool_axis

    def test_01_fk_and_geometric_j_against_upstream_et(self):
        rng = np.random.default_rng(31)
        for q in rng.uniform(self.model.limits[:, 0], self.model.limits[:, 1], (80, 5)):
            t, j = self.model.evaluate(q)
            np.testing.assert_allclose(t, self.et.fkine(q), atol=2e-14, rtol=0)
            np.testing.assert_allclose(j, self.et.jacob0(q), atol=2e-14, rtol=0)

    def test_02_geometric_j_finite_difference(self):
        rng = np.random.default_rng(32)
        h = 1e-6
        for q in rng.uniform(-1, 1, (30, 5)):
            t, j = self.model.evaluate(q)
            for col in range(5):
                d = np.eye(5)[col] * h
                tp, _ = self.model.evaluate(q + d)
                tm, _ = self.model.evaluate(q - d)
                dt = (tp - tm) / (2 * h)
                omega = dt[:3, :3] @ t[:3, :3].T
                numerical = np.r_[dt[:3, 3], omega[2, 1], omega[0, 2], omega[1, 0]]
                np.testing.assert_allclose(j[:, col], numerical, atol=self.cfg["derivative_abs_tolerance"], rtol=0)

    def test_03_task_derivative_large_direction_error(self):
        rng = np.random.default_rng(33)
        for q in rng.uniform(-1, 1, (24, 5)):
            axis = rng.normal(size=3)
            axis /= np.linalg.norm(axis)
            p = [.2, .03, .15]
            _, j, _, _ = self.model.task(q, p, axis)
            for col in range(5):
                d = np.eye(5)[col] * 1e-6
                derivative = (self.model.task(q+d, p, axis)[0] - self.model.task(q-d, p, axis)[0]) / 2e-6
                np.testing.assert_allclose(-j[:, col], derivative, atol=self.cfg["derivative_abs_tolerance"], rtol=0)

    def test_04_tool_translation_derivative(self):
        cfg = copy.deepcopy(self.model.config)
        cfg["tool_translation_m"] = [.04, -.02, .06]
        model = Model(cfg)
        q = np.array([.4, -.4, .6, -.3, .2])
        _, j = model.evaluate(q)
        for col in range(5):
            d = np.eye(5)[col] * 1e-6
            dp = (model.evaluate(q+d)[0][:3, 3] - model.evaluate(q-d)[0][:3, 3]) / 2e-6
            np.testing.assert_allclose(j[:3, col], dp, atol=2e-7, rtol=0)

    def test_05_roll_free_nominal_task_has_only_rank_four(self):
        q = [.3, -.5, .7, .1, .2]
        p, a = self.target(q)
        j = self.model.task(q, p, a)[1]
        self.assertEqual(np.linalg.matrix_rank(j, tol=1e-9), 4)
        np.testing.assert_allclose(j[:, 4], 0, atol=1e-14)

    def test_06_weighted_step_matches_augmented_svd(self):
        j, e, w, s = self.fixture()
        for mu in (1e-4, 1e-3, .1, 1):
            np.testing.assert_allclose(step(j, e, w, s, mu), independent_wls(j, e, w, s, mu), rtol=1e-8, atol=1e-9)

    def test_07_zero_weight_rows_disappear(self):
        j, e, w, s = self.fixture()
        w[3:] = 0
        first = step(j, e, w, s, .01)
        j[3:] *= 123
        e[3:] += 100
        np.testing.assert_allclose(step(j, e, w, s, .01), first, rtol=0, atol=1e-12)

    def test_08_unit_weights_equal_original_formula(self):
        j, e, _, s = self.fixture()
        np.testing.assert_array_equal(step(j, e, np.ones(6), s, .02), step(j, e, np.ones(6), s, .02, "rhs_only"))

    def test_09_nonunit_weights_fix_measurable_error(self):
        j, e, w, _ = self.fixture()
        s = np.ones(6)  # S=1: original single-step formula conditions.
        oracle = independent_wls(j, e, w, s, .01)
        self.assertGreater(np.linalg.norm(step(j, e, w, s, .01, "rhs_only") - oracle), .01)
        np.testing.assert_allclose(step(j, e, w, s, .01), oracle, atol=1e-10)

    def test_10_W_mu_and_scale_semantics(self):
        j = np.vstack((np.eye(5), np.zeros(5)))
        e = np.ones(6)
        actual = step(j, e, np.full(6, 4.), np.full(6, 2.), 3.)
        np.testing.assert_allclose(actual, np.full(5, 16/19), atol=1e-14)

    def test_11_invalid_linear_inputs_rejected(self):
        j, e, w, s = self.fixture()
        for bad_w, bad_s, mu in ((-np.ones(6), s, .1), (w, np.zeros(6), .1), (w, s, 0), (w, s, np.nan)):
            with self.assertRaises(ValueError):
                step(j, e, bad_w, bad_s, mu)
        for value in (np.nan, np.inf):
            bad = j.copy(); bad[0, 0] = value
            with self.assertRaises(ValueError):
                step(bad, e, w, s, .1)

    def test_12_bounded_local_ik_success(self):
        target = np.array([.2, -.3, .5, -.2, .1])
        result = solve(self.model, *self.target(target), target + [.03, -.04, .02, .01, .07], self.cfg)
        self.assertEqual(result.status, "OK")
        self.assertLessEqual(result.position_error_m, self.cfg["position_tolerance_m"])
        self.assertLessEqual(result.tilt_error_rad, self.cfg["tilt_tolerance_rad"])
        self.assertTrue(all(self.model.legal(h["q"]) for h in result.history))

    def test_13_all_zero_weights_cannot_fake_physical_success(self):
        cfg = dict(self.cfg, weights=[0]*6)
        result = solve(self.model, *self.target([.2, -.3, .5, -.2, 0]), np.zeros(5), cfg)
        self.assertEqual(result.status, "STAGNATION")
        self.assertIsNone(result.q_solution)

    def test_14_antipodal_axis_never_reports_success(self):
        p, a = self.target(np.zeros(5))
        result = solve(self.model, p, -a, np.zeros(5), self.cfg)
        self.assertNotEqual(result.status, "OK")
        self.assertIsNone(result.q_solution)

    def test_15_distant_target_bounded_failure_with_legal_history(self):
        result = solve(self.model, [5, 5, 5], [0, 0, 1], np.zeros(5), self.cfg)
        self.assertIn(result.status, ("MAX_ITER", "LIMIT_STALL", "STAGNATION"))
        self.assertIsNone(result.q_solution)
        self.assertLessEqual(result.iterations, self.cfg["max_iterations"])
        self.assertTrue(all(self.model.legal(h["q"]) for h in result.history))

    def test_16_failure_then_success_no_stale_solution(self):
        for _ in range(3):
            bad = solve(self.model, [np.nan, 0, 0], [1, 0, 0], np.zeros(5), self.cfg)
            self.assertEqual(bad.status, "INVALID_INPUT")
            self.assertIsNone(bad.q_solution)
            good = solve(self.model, *self.target(np.zeros(5)), np.zeros(5), self.cfg)
            self.assertEqual(good.status, "OK")
            np.testing.assert_array_equal(good.q_solution, np.zeros(5))

    def test_17_out_of_limit_seed_not_silently_clipped(self):
        result = solve(self.model, *self.target(np.zeros(5)), [9]*5, self.cfg)
        self.assertEqual(result.status, "INVALID_INPUT")
        self.assertIsNone(result.q_solution)

    def test_18_bad_model_rejected(self):
        for field, value in (("units", "mm"), ("axes", [[0, 0, 0]]*5), ("tool_axis_local", [0, 0, 0]), ("limits_rad", [[1, -1]]*5)):
            cfg = copy.deepcopy(self.model.config); cfg[field] = value
            with self.assertRaises(ValueError):
                Model(cfg)

    def test_19_invalid_solver_config_rejected(self):
        for field, value in (("stagnation_cost_change", np.nan), ("max_iterations", 1.2), ("line_search_trials", 0), ("mu", -1)):
            cfg = dict(self.cfg); cfg[field] = value
            result = solve(self.model, *self.target(np.zeros(5)), np.zeros(5), cfg)
            self.assertEqual(result.status, "INVALID_INPUT")

    def test_20_zero_jacobian_regularized_step(self):
        np.testing.assert_array_equal(step(np.zeros((6, 5)), np.ones(6), np.ones(6), np.ones(6), .001), np.zeros(5))


if __name__ == "__main__":
    unittest.main(verbosity=2)
