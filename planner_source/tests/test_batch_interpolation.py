"""Compare batching with frozen scalar commands and exercise failure paths."""
import json
from pathlib import Path
import unittest
import numpy as np
from r1a.model import Model
from r1b.continuous import interpolate, evaluate

ROOT = Path(__file__).resolve().parents[1]


class BatchInterpolationTests(unittest.TestCase):
    def setUp(self):
        self.model = Model.load(ROOT/'config/nominal_so101.json')
        self.cases = json.loads((Path(__file__).parent/'fixtures/continuous_before_batch.json').read_text())

    def test_cubic_and_quintic_match_frozen_scalar_output(self):
        for case in self.cases:
            commands, metrics = interpolate(self.model,case['qs'],case['targets'],case['cfg'])
            self.assertEqual(len(commands),len(case['commands']))
            for actual, expected in zip(commands,case['commands']):
                for key in ['q_rad','velocity_rad_s','acceleration_rad_s2','tip_target_m','axis_target','t_s']:
                    np.testing.assert_allclose(actual[key],expected[key],rtol=0,atol=1e-14)
                for key in ['phase','stroke','pen_down','physical_authorized']:
                    self.assertEqual(actual[key],expected[key])
                # Equal counts at the hardware's 4096 counts/revolution.
                np.testing.assert_array_equal(np.rint(np.asarray(actual['q_rad'])*4096/(2*np.pi)+2048),
                                              np.rint(np.asarray(expected['q_rad'])*4096/(2*np.pi)+2048))
            measured_fields={'max_interpolation_error_m','max_tilt_rad','geometry_check',
                'max_requested_sample_error_m','max_draw_path_error_m','max_draw_tilt_rad',
                'geometry_samples','geometry_scope','geometry_fk_batches','geometry_batch_limit'}
            self.assertEqual({k:v for k,v in metrics.items() if k not in measured_fields},
                             {k:v for k,v in case['metrics'].items() if k not in measured_fields})
            # These frozen polynomial cases intentionally have positions that
            # do not match their joint poses. Previously they reported zero.
            scalar_errors=[np.linalg.norm(self.model.pose(c['q_rad'])[:3,3]-c['tip_target_m']) for c in commands]
            self.assertGreater(metrics['max_requested_sample_error_m'],.01)
            self.assertGreaterEqual(metrics['max_requested_sample_error_m']+1e-12,max(scalar_errors))
            self.assertGreater(metrics['geometry_samples'],len(commands))
            self.assertEqual(metrics['geometry_batch_limit'],1024)
            self.assertGreater(metrics['geometry_fk_batches'],0)

    def test_multiple_chunks_have_every_sample_and_correct_endpoint(self):
        case=self.cases[1]
        cfg=dict(case['cfg'],command_period_s=.0001)
        commands, _=interpolate(self.model,case['qs'],case['targets'],cfg)
        self.assertGreater(len(commands),2000)
        self.assertTrue(np.all(np.diff([c['t_s'] for c in commands])>0))
        np.testing.assert_allclose(commands[-1]['q_rad'],case['qs'][-1],atol=1e-14)

    def test_limits_budget_and_cancellation_fail_closed(self):
        case=self.cases[1]
        cfg=dict(case['cfg'],max_commands=2)
        with self.assertRaisesRegex(ValueError,'COMMAND_BUDGET'):
            interpolate(self.model,case['qs'],case['targets'],cfg)
        self.model.limits[0]=[-.01,.01]
        with self.assertRaisesRegex(ValueError,'INTERPOLATION_ERROR'):
            interpolate(self.model,case['qs'],case['targets'],case['cfg'])
        with self.assertRaisesRegex(ValueError,'ABORT'):
            interpolate(self.model,case['qs'],case['targets'],case['cfg'],lambda:True)

    def test_batched_polynomials_match_scalar_over_random_coefficients(self):
        rng=np.random.default_rng(29)
        for degree in (4,6):
            coeff=rng.normal(size=(degree,5)); us=np.linspace(0,1,1001)
            actual=evaluate(coeff,us[:,None],.37)
            expected=[evaluate(coeff,float(u),.37) for u in us]
            for i in range(3):
                np.testing.assert_array_equal(actual[i],np.asarray([e[i] for e in expected]))


if __name__ == '__main__': unittest.main()
