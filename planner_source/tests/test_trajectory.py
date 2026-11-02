import copy
import json
from pathlib import Path
import unittest
import numpy as np
from r1a.model import Model
from r1a.linear import step
from r1b.fixtures import drawings
from r1b.path import arc,drawing_targets,line
from r1b.planner import plan,motion_segment

ROOT=Path(__file__).resolve().parents[1]


class TrajectoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=Model.load(ROOT/'config/nominal_so101.json')
        cls.ik=json.loads((ROOT/'config/contract.json').read_text())
        cls.cfg=json.loads((ROOT/'config/trajectory.json').read_text())
        cls.spec=drawings(cls.model)[0]

    def test_circle_directions_and_chord_bound(self):
        for sweep in (2*np.pi,-2*np.pi):
            points=arc([0,0,0],[1,0,0],[0,1,0],.02,.1,sweep,.003,2e-5,1000)
            np.testing.assert_allclose(points[0],points[-1],atol=1e-15)
            self.assertTrue(np.all(np.linalg.norm(np.diff(points,axis=0),axis=1)<=.003+1e-12))
            mid=(points[1:]+points[:-1])/2
            self.assertTrue(np.all(.02-np.linalg.norm(mid,axis=1)<=2e-5+1e-12))
            self.assertEqual(np.sign(np.cross(points[0],points[1])[2]),np.sign(sweep))

    def test_gap_must_be_separate_stroke(self):
        bad=copy.deepcopy(self.spec)
        extra=copy.deepcopy(bad['strokes'][0]['segments'][0]); extra['start_m'][1]+=.01
        bad['strokes'][0]['segments'].append(extra)
        with self.assertRaises(ValueError): drawing_targets(bad,self.cfg)

    def test_jump_is_pen_up_with_lift_and_lower(self):
        targets=drawing_targets(drawings(self.model)[4],self.cfg)
        phases=[t['phase'] for t in targets]
        self.assertIn('TRAVEL',phases)
        plane=np.array(self.spec['plane_origin_m'])
        for t in targets:
            if t['phase']=='TRAVEL': self.assertAlmostEqual(t['position'][2]-plane[2],self.cfg['lift_m'])

    def test_reject_bad_geometry_and_huge_sampling(self):
        for radius,sweep in ((0,1),(.1,0),(.1,10)):
            with self.assertRaises(ValueError): arc([0,0,0],[1,0,0],[0,1,0],radius,0,sweep,.001,1e-5,100)
        with self.assertRaises(ValueError): line([0,0,0],[100,0,0],1e-9,100)

    def test_nominal_short_line_and_time_bounds(self):
        r=plan(self.model,self.spec,self.spec['q0'],self.ik,self.cfg)
        self.assertEqual(r.status,'OK')
        self.assertFalse(r.physical_authorized)
        self.assertTrue(r.commands)
        self.assertTrue(np.all(np.diff([c['t_s'] for c in r.commands])>0))
        self.assertLessEqual(r.metrics['peak_velocity_rad_s'],self.cfg['max_velocity_rad_s']+1e-12)
        self.assertLessEqual(r.metrics['peak_acceleration_rad_s2'],self.cfg['max_acceleration_rad_s2']+1e-12)
        self.assertTrue(all(self.model.legal(c['q_rad']) for c in r.commands))
        self.assertTrue(all(c['pen_down']==(c['phase']=='DRAW') for c in r.commands))

    def test_cancel_invalidates_entire_batch(self):
        calls=[0]
        def cancel():
            calls[0]+=1
            return calls[0]>=5
        r=plan(self.model,self.spec,self.spec['q0'],self.ik,self.cfg,cancel=cancel)
        self.assertEqual(r.status,'ABORT'); self.assertIsNone(r.commands)

    def test_bad_backend_never_leaks_partial_commands(self):
        calls=[0]
        def backend(*args):
            calls[0]+=1
            if calls[0]>=5: raise FloatingPointError('injected hardware numeric failure')
            return step(*args)
        r=plan(self.model,self.spec,self.spec['q0'],self.ik,self.cfg,backend=backend)
        self.assertEqual(r.status,'NUMERIC'); self.assertIsNone(r.commands)
        self.assertLess(r.metrics['completed_targets'],r.metrics['total_targets'])

    def test_recovery_obeys_same_iteration_budget(self):
        cfg=dict(self.cfg,iterations_per_attempt=1,attempts_with_recovery=3,iterations_per_target=3)
        for recovery in (False,True):
            r=plan(self.model,self.spec,self.spec['q0'],self.ik,cfg,recovery=recovery)
            for record in r.diagnostics:
                self.assertLessEqual(sum(a['iterations'] for a in record['attempts']),3)
            self.assertLessEqual(r.metrics['ik_iterations'],cfg['max_total_ik_iterations'])

    def test_recovery_can_retry_failed_numeric_seed(self):
        calls=[0]
        def backend(*args):
            calls[0]+=1
            # First solve makes a zero step -> STAGNATION, second uses DLS.
            if calls[0]==1: return np.zeros(5)
            return step(*args)
        r=plan(self.model,self.spec,self.spec['q0'],self.ik,self.cfg,backend=backend,recovery=True)
        self.assertEqual(r.status,'OK')
        self.assertGreater(r.metrics['recovery_calls'],0)

    def test_illegal_q_and_plane_fail_closed(self):
        r=plan(self.model,self.spec,[9]*5,self.ik,self.cfg)
        self.assertEqual(r.status,'INVALID_INPUT'); self.assertIsNone(r.commands)
        bad=copy.deepcopy(self.spec); bad['plane_origin_m'][2]+=.01
        self.assertEqual(plan(self.model,bad,self.spec['q0'],self.ik,self.cfg).status,'INVALID_INPUT')
