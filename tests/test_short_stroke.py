"""Offline short-stroke prototype: SDK rounding, geometry gates and no execution."""
import copy
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from calligraphy import curves
from calligraphy.presets import BRUSH, binding, task
from tcb705 import artifact
from tcb705.config import load
from tcb705.model import Model,ROOT
from tcb705.planner import _plan,PlanningError
from tcb705.short_stroke import compile_single,validate_segments
from tcb705.web_executor import build,settings


class ShortStrokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=load(ROOT/'robots/tcb705/profile.armvision_joint.json')
        cls.c['execution']['sdk']={'enabled':True}
        cls.c['calligraphy']=dict(BRUSH,max_press_mm=4.,verified=True,
                                 calibration_binding=binding(cls.c))
        cls.model=Model(cls.c)
        cls.q=cls.model.from_sdk(cls.c['execution']['web_program']['home']['joint_degrees'])
        cls.paths=task('heng',40,cls.c)
        cls.result=compile_single(cls.paths,cls.c,cls.q)

    def test_matches_full_planner_geometry_and_guards_non_executable_contract(self):
        full=_plan(self.paths,self.c,self.q)
        n=artifact.nodes_of(full);actual=self.result['nodes']
        for k in ('positions_m','interval_phase','interval_stroke','stops','interval_feed_ratio'):
            self.assertEqual(n[k],actual[k])
        self.assertFalse(self.result['execution_ready'])
        self.assertNotIn('duration_s',self.result['metrics'])
        self.assertIsNone(self.result['metrics']['near_error_mm'])
        self.assertEqual(self.result['metrics']['collision_probe_samples'],0)
        self.assertEqual(self.result['keep'],list(range(len(actual['positions_m']))))
        with self.assertRaisesRegex(ValueError,'research candidate'):
            artifact.freeze(self.result,'real')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'research candidate'):
                artifact.save(self.result,tmp,'real')

    def test_rounding_matches_real_sdk_serialization(self):
        n=self.result['nodes'];keep=self.result['keep']
        _,chunks=build(self.c,n,settings(self.c),joint_keep=keep)
        sent=[]
        for chunk in chunks:
            for b in chunk['content']['programs'][0]['codeBlock']:
                if b['fc']=='hmcRobotFree':
                    sent.append([float('%.4f'%float(v)) for v in b['code']['endp']])
        np.testing.assert_array_equal(np.asarray(sent,dtype=np.float32).astype(float),
                                      np.asarray(n['sdk_degrees'])[keep[1:]])

    def test_batch_prefix_refinement_matches_original_planner(self):
        original=Model.solve_chain
        def run(geometry_only):
            calls=[0]
            def once(model,targets,seed):
                rows=original(model,targets,seed);calls[0]+=1
                if calls[0]==1 and len(rows)>3:
                    rows[3]=dict(rows[3],ok=False)
                return rows
            with patch.object(Model,'solve_chain',once):
                return _plan(self.paths,self.c,self.q,_geometry_only=geometry_only)
        full,short=run(False),run(True)
        for key in ('node_q_rad','geometric_positions','interval_phase','node_stroke_ids','node_stops'):
            np.testing.assert_array_equal(full[key],short[key])
        self.assertEqual(full['interval_feed_ratio'],short['interval_feed_ratio'])

    def test_prefetch_cannot_hide_non_finite_angles(self):
        original=Model.solve_chain
        def damaged(model,targets,seed):
            rows=original(model,targets,seed)
            rows[0]=dict(rows[0],q=np.full(7,np.nan),ok=True)
            return rows
        # A corrupt native result must be rejected or recomputed, not accepted
        # as a valid prefix. Refinement recomputes it via the scalar IK path.
        with patch.object(Model,'solve_chain',damaged):
            result=_plan(self.paths,self.c,self.q,_geometry_only=True)
        self.assertTrue(np.isfinite(result['node_q_rad']).all())

    def test_modified_pressure_and_multiple_strokes_are_rejected(self):
        bad=copy.deepcopy(self.paths);bad['calligraphy']['depth_mm'][0][2]+=.001
        with self.assertRaisesRegex(ValueError,'重新生成'):compile_single(bad,self.c,self.q)
        bad=copy.deepcopy(self.paths);bad['paths']*=2
        with self.assertRaisesRegex(ValueError,'SHORT_STROKE_ONLY'):compile_single(bad,self.c,self.q)

    def test_cancellation_and_no_sdk_connection(self):
        with patch('tcb705.sdk_motion.open_client',side_effect=AssertionError('robot connection')):
            with self.assertRaisesRegex(PlanningError,'CANCELLED'):
                compile_single(self.paths,self.c,self.q,lambda:True)
            compile_single(self.paths,self.c,self.q)

    def test_actual_segment_collision_failure_propagates(self):
        with patch('tcb705.short_stroke.check_collision_batch',side_effect=ValueError('OBSTACLE_COLLISION')):
            with self.assertRaisesRegex(ValueError,'OBSTACLE_COLLISION'):
                validate_segments(self.c,self.result['nodes'],self.result['keep'],self.model)

    def test_actual_rounded_joint_limits_are_checked(self):
        m=Model(self.c);m.upper[:]=-100
        with self.assertRaisesRegex(PlanningError,'FINAL_SAMPLE_LIMIT'):
            validate_segments(self.c,self.result['nodes'],self.result['keep'],m)

    def test_curve_cache_is_immutable_and_tracks_edits_and_scale(self):
        points=[[0.,0.,0.,.5],[20.,1.,.8,1.],[30.,0.,0.,.5]]
        expect=curves.BrushCurve(points).sample(.8)
        a=curves.sample(points,.8);self.assertEqual(a,expect)
        a[0][0]=999
        self.assertEqual(curves.sample(points,.8),expect)
        changed=copy.deepcopy(points);changed[1][2]=.2
        self.assertNotEqual(curves.sample(changed,.8),expect)
        self.assertEqual(curves.sample(points,1.4),curves.BrushCurve(points).sample(1.4))


if __name__=='__main__':unittest.main()
