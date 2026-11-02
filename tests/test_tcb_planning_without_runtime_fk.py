"""Execution frames survive removal of repeated pose checks; offline oracle retained."""
import unittest
from unittest.mock import patch
import numpy as np
from tcb705.config import demo_config
from tcb705.model import Model
from tcb705.planner import _plan,PlanningError


class PlanningWithoutRuntimeFKTests(unittest.TestCase):
    def setUp(self):
        self.cfg=demo_config();self.model=Model(self.cfg)
        self.paths=dict(units='mm',width_mm=100,height_mm=100,
                        paths=[[[40,45],[60,45]],[[40,55],[60,55]]])
    def test_no_batch_fk_but_real_timed_frames_and_cloud_preview(self):
        with patch.object(self.model,'fk_batch',side_effect=AssertionError('runtime batch FK forbidden')):
            result=_plan(self.paths,self.cfg,_model=self.model)
        self.assertGreater(len(result['times']),len(result['node_q_rad']))
        self.assertEqual(len(result['sdk_degrees']),len(result['times']))
        self.assertTrue(np.isfinite(result['sdk_degrees']).all())
        self.assertTrue(np.all(result['q_rad']>=self.model.lower))
        self.assertTrue(np.all(result['q_rad']<=self.model.upper))
        self.assertEqual(result['metrics']['geometry_fk_batches'],0)
        self.assertEqual(result['metrics']['geometry_probe_samples'],0)
        self.assertIsNone(result['metrics']['max_path_error_m'])
        self.assertIsNone(result['metrics']['max_orientation_error_rad'])
        self.assertEqual(result['preview']['paths'],[])
        self.assertEqual(result['preview']['source'],'cloud')
        # Independent offline quality audit remains a test, not runtime work.
        poses=self.model.fk_batch(result['q_rad'])
        seg=np.minimum(np.searchsorted(result['interval_times'],result['times'],side='right')-1,
                       len(result['interval_times'])-2)
        begin=result['geometric_positions'][seg];delta=result['geometric_positions'][seg+1]-begin
        fraction=np.clip(np.einsum('ij,ij->i',poses[:,:3,3]-begin,delta)/np.maximum(np.einsum('ij,ij->i',delta,delta),1e-30),0,1)
        error=np.linalg.norm(poses[:,:3,3]-(begin+fraction[:,None]*delta),axis=1)
        self.assertLess(error.max(),self.cfg['planning']['path_tolerance_m'])
    def test_nonfinite_execution_samples_still_rejected(self):
        original=self.model.sample_rows
        def corrupt(*args):
            sdk,q=original(*args);sdk[0,0]=np.nan;return sdk,q
        with patch.object(self.model,'sample_rows',side_effect=corrupt):
            with self.assertRaisesRegex(PlanningError,'FINAL_SAMPLE_NONFINITE'):
                _plan(self.paths,self.cfg,_model=self.model)
    def test_out_of_limit_execution_samples_still_rejected(self):
        original=self.model.sample_rows
        def corrupt(*args):
            sdk,q=original(*args);q[0,0]=self.model.upper[0]+.001;return sdk,q
        with patch.object(self.model,'sample_rows',side_effect=corrupt):
            with self.assertRaisesRegex(PlanningError,'FINAL_SAMPLE_LIMIT'):
                _plan(self.paths,self.cfg,_model=self.model)
    def test_polynomial_joint_limit_check_remains(self):
        original=self.model.extrema_batch
        def corrupt(*args):
            bounds=original(*args);bounds[0,0,1,0]=self.model.lower[0]-.01;return bounds
        with patch.object(self.model,'extrema_batch',side_effect=corrupt):
            with self.assertRaisesRegex(PlanningError,'CURVE_LIMIT'):
                _plan(self.paths,self.cfg,_model=self.model)


if __name__=='__main__':unittest.main()
