"""Numerical coupled-height goals and an independent unequal-rate motor plant."""
import copy
import math
import unittest
import numpy as np
import planning
from cartesian_feedback import NormalFeedbackController
from motion import angles_from_counts, counts_from_angles
from test_feedback_drawing import machine


class NormalFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.m = machine()
        self.m['execution']['feedback_control'] = dict(max_correction_counts=64.)
        self.model = planning.Model(self.m['model'])
        self.q = np.asarray(planning.nominal()[2])
        self.base = counts_from_angles(self.m, self.q)
        # Reference equals the actual integer nominal, so the measurement
        # error being corrected is independent of integer-target rounding.
        self.q = np.asarray(angles_from_counts(self.m, self.base))
        self.pose = self.model.pose(self.q)
        self.command = dict(phase='DRAW', q_rad=self.q.tolist(),
                            tip_reference_m=self.pose[:3, 3].tolist())

    def measured(self, shift=15):
        result = self.base.copy(); result[2] += shift
        return result

    def run_fixed(self, controller, measured, command=None, base=None, frames=8):
        for k in range(frames):
            result, detail = controller.target(command or self.command, base or self.base,
                                               measured, True, k*.05)
        return result, detail

    def test_signed_height_is_corrected_with_zero_tangent_and_axis_change(self):
        for shift in (-15, 15):
            with self.subTest(shift=shift):
                controller = NormalFeedbackController(self.m, self.model, .05)
                result, detail = self.run_fixed(controller, self.measured(shift))
                signed = detail['signed_normal_error_m']
                expected = -.6*math.copysign(max(0., abs(signed)-.00015), signed)
                self.assertAlmostEqual(controller.offset, expected, places=12)
                after = self.model.pose(angles_from_counts(self.m, result))
                delta = after[:3, 3]-self.pose[:3, 3]
                self.assertLess(float(np.linalg.norm(delta[:2])), .0003)
                self.assertAlmostEqual(float(delta[2]), expected, delta=.0003)
                self.assertLess(detail['axis_side_effect_rad'], .0035)
                self.assertLess(detail['applied_normal_offset_m']*signed, 0.)
                # Height and axis are coupled through multiple joint goals.
                self.assertGreater(sum(result[sid] != self.base[sid] for sid in self.base), 1)

    def test_tilted_paper_uses_normal_rather_than_global_z(self):
        m = copy.deepcopy(self.m)
        angle = .2
        m['paper']['u'] = [1, 0, 0]
        m['paper']['v'] = [0, math.cos(angle), math.sin(angle)]
        m['paper']['normal'] = [0, -math.sin(angle), math.cos(angle)]
        controller = NormalFeedbackController(m, self.model, .05)
        result, detail = self.run_fixed(controller, self.measured())
        delta = self.model.pose(angles_from_counts(m, result))[:3, 3]-self.pose[:3, 3]
        n = np.asarray(m['paper']['normal'])
        self.assertLess(np.linalg.norm(delta-n*(delta@n)), .0003)
        self.assertLess(detail['axis_side_effect_rad'], .0035)

    def test_deadband_disabled_and_noncontact_phase_preserve_base(self):
        controller = NormalFeedbackController(self.m, self.model, .05)
        self.assertEqual(controller.target(self.command, self.base, self.base, True, 0.)[0], self.base)
        disabled = NormalFeedbackController(self.m, self.model, .05, dict(enabled=False))
        self.assertEqual(self.run_fixed(disabled, self.measured())[0], self.base)
        self.run_fixed(controller, self.measured())
        travel = dict(self.command, phase='TRAVEL')
        self.assertEqual(controller.target(travel, self.base, self.measured(), True, .5)[0], self.base)
        self.assertEqual(controller.offset, 0.)

    def test_lower_phase_also_corrects_height(self):
        controller = NormalFeedbackController(self.m, self.model, .05)
        result, detail = self.run_fixed(controller, self.measured(), dict(self.command, phase='LOWER'))
        self.assertNotEqual(result, self.base)
        self.assertTrue(detail['active'])

    def test_stale_feedback_slews_extra_offset_to_zero_preserving_load_bias(self):
        controller = NormalFeedbackController(self.m, self.model, .05)
        loaded = self.base.copy(); loaded[2] -= 26; loaded[3] -= 17
        self.run_fixed(controller, self.measured(30), base=loaded)
        before = controller.offset
        result, _ = controller.target(self.command, loaded, None, False, .40)
        self.assertLessEqual(abs(controller.offset-before), .00100000001)
        for k in range(9, 30):
            result, _ = controller.target(self.command, loaded, None, False, k*.05)
        self.assertEqual(result, loaded)
        self.assertEqual(controller.offset, 0.)
        self.assertGreater(controller.summary()['stale_samples'], 0)

    def test_incomplete_reading_continues_and_decays_correction(self):
        controller = NormalFeedbackController(self.m, self.model, .05)
        self.run_fixed(controller, self.measured())
        for k in range(8, 30):
            result, detail = controller.target(self.command, self.base, {1: 1000}, True, k*.05)
        self.assertEqual(result, self.base)
        self.assertIsNone(detail['signed_normal_error_m'])

    def test_height_and_total_count_caps_remain_bounded_without_abort(self):
        m = copy.deepcopy(self.m)
        m['execution']['feedback_control']['max_correction_counts'] = 3.
        controller = NormalFeedbackController(m, self.model, .05)
        result, detail = self.run_fixed(controller, self.measured(250), frames=40)
        self.assertEqual(abs(controller.offset), .004)
        self.assertTrue(all(abs(result[sid]-self.base[sid]) <= 3 for sid in self.base))
        self.assertLess(detail['coupling_scale'], 1.)
        self.assertGreater(controller.summary()['saturated_samples'], 0)
        self.assertEqual(controller.summary()['fallback_samples'], 0)

    def test_joint_count_limits_scale_coupled_goal_instead_of_crossing_bound(self):
        m = copy.deepcopy(self.m)
        for joint in m['joints']:
            joint['min_count'] = self.base[joint['id']]-1
            joint['max_count'] = self.base[joint['id']]+1
        controller = NormalFeedbackController(m, self.model, .05)
        result, detail = self.run_fixed(controller, self.measured(30))
        for joint in m['joints']:
            self.assertGreaterEqual(result[joint['id']], joint['min_count'])
            self.assertLessEqual(result[joint['id']], joint['max_count'])
        self.assertLess(detail['coupling_scale'], 1.)
        self.assertGreater(controller.summary()['saturated_samples'], 0)

    def test_independent_unequal_rate_loaded_plant_reduces_height_transient(self):
        # An external first-order plant with different joint time constants.
        # Its load offsets are independent of either controller's equations.
        tau = np.asarray([.16, .70, .12, .35, .10])
        load = np.asarray([0., 26., -17., 4., 0.])
        nominal = np.asarray([self.base[sid] for sid in range(1, 6)], dtype=float)
        base = {sid: int(nominal[sid-1]+load[sid-1]) for sid in range(1, 6)}
        def simulate(enabled):
            controller = NormalFeedbackController(self.m, self.model, .05, dict(enabled=enabled))
            position = nominal+np.asarray([0., 18., -5., 3., 0.])
            errors = []
            for k in range(100):
                measured = {sid: int(round(position[sid-1])) for sid in range(1, 6)}
                goal, _ = controller.target(self.command, base, measured, True, k*.05)
                position += (np.asarray([goal[sid] for sid in range(1, 6)])-load-position)*(1-np.exp(-.05/tau))
                actual = self.model.pose(angles_from_counts(self.m, dict(zip(range(1, 6), position))))[:3, 3]
                errors.append(abs(float((actual-self.pose[:3, 3])@controller.normal)))
            return np.asarray(errors)
        baseline, corrected = simulate(False), simulate(True)
        self.assertLess(float(corrected[:30].sum()), .8*float(baseline[:30].sum()))
        self.assertLess(float(corrected[-10:].max()), .0003)


if __name__ == '__main__':
    unittest.main()
