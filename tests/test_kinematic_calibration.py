"""Numerical fit tests; all generated samples are simulation, never real contact."""
import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kinematic_calibration import (SCHEMA, RAD_PER_COUNT, fit_calibration,
    make_candidate, validate_acceptance, capture_template, fit_pen_axis)
from planning import Model


def simulation_fixture(noise_counts=.20, seed=71):
    machine = json.loads((ROOT/'config/machine.example.json').read_text(encoding='utf-8'))
    for joint in machine['joints']:
        joint.update(zero_count=2048, min_count=0, max_count=4095)
    # Test sign handling; fitting must not assume every servo direction is +1.
    machine['joints'][2]['direction'] = -1
    machine['checks'].update(limits=True)
    truth = copy.deepcopy(machine)
    zero_corrections = {'2':34, '3':-28, '4':17}
    for joint in truth['joints']:
        joint['zero_count'] += zero_corrections.get(str(joint['id']), 0)
    truth['model']['tool_translation_m'] = [.095,0.,0.]
    model = Model(truth['model'])
    origin = model.pose([0.,-.55,1.,np.pi/2-.45,0.])[:3,3]
    machine['paper'].update(origin_m=(origin+[.006,-.004,.009]).tolist(),u=[1,0,0],v=[0,1,0],normal=[0,0,1],pen_axis=[0,0,-1])
    captures = []; rng=np.random.RandomState(seed)
    points = [(x,y,'fit') for y in (-50.,0.,50.) for x in (-50.,0.,50.)]
    points += [(x,y,'validation') for x,y in [(-25.,-25.),(-25.,25.),(25.,-25.),(25.,25.)]]
    for x,y,split in points:
        for tilt,label in ((-.23,'forward'),(0.,'vertical'),(.23,'backward')):
            pitch=np.pi/2+tilt
            target=origin+np.array([x/1000,y/1000,0])
            unknown=np.array([0.,-.55,1.])
            def full(z): return np.array([z[0],z[1],z[2],pitch-z[1]-z[2],0.])
            for iteration in range(80):
                q=full(unknown); error=target-model.pose(q)[:3,3]
                if np.linalg.norm(error)<1e-10:break
                jac=np.column_stack([(model.pose(full(unknown+np.eye(3)[i]*1e-6))[:3,3]-model.pose(q)[:3,3])/1e-6 for i in range(3)])
                step=np.linalg.lstsq(jac,error,rcond=None)[0]
                unknown += step * min(1., .2/max(np.linalg.norm(step),1e-15))
            if np.linalg.norm(target-model.pose(full(unknown))[:3,3])>1e-7:
                raise AssertionError('simulation IK did not converge')
            counts={str(j['id']):int(round(j['zero_count']+j['direction']*angle/RAD_PER_COUNT+rng.normal(0,noise_counts))) for j,angle in zip(truth['joints'],full(unknown))}
            captures.append(dict(counts=counts,xy_mm=[x,y],pose_label=label,split=split))
    dataset=dict(schema=SCHEMA,source='simulation',initial_pen_length_mm=80.,captures=captures,
                 note='SIMULATION ONLY. Numerical regression data; never physical encoder captures.')
    return machine,dataset,truth


class CalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.machine,cls.dataset,cls.truth=simulation_fixture()
        cls.result=fit_calibration(cls.machine,cls.dataset)

    def test_finds_joint_zeros_and_pen_length_in_simulation(self):
        self.assertEqual(self.result['status'],'ACCEPT',self.result)
        self.assertLess(self.result['fit']['max_mm'],1.5)
        self.assertEqual(self.result['solver']['jacobian_rank'],10)
        self.assertLess(abs(self.result['parameters']['pen_length_mm']-95.),.8)
        for joint in self.truth['joints']:
            self.assertLessEqual(abs(self.result['parameters']['zero_count'][str(joint['id'])]-joint['zero_count']),3)
        self.assertEqual(self.result['independent_validation'],'PASS')

    def test_simulation_never_creates_hardware_candidate(self):
        self.assertFalse(self.result['applicable_to_hardware'])
        with self.assertRaises(ValueError):make_candidate(self.machine,self.dataset,self.result)
        with self.assertRaises(ValueError):validate_acceptance(self.machine)

    def test_no_independent_measurement_is_pending_not_passed(self):
        dataset=copy.deepcopy(self.dataset)
        dataset['captures']=[r for r in dataset['captures'] if r['split']=='fit']
        result=fit_calibration(self.machine,dataset)
        self.assertEqual(result['status'],'ACCEPT',result)
        self.assertEqual(result['independent_validation'],'PENDING')

    def test_bad_contact_is_rejected_not_robustly_hidden(self):
        dataset=copy.deepcopy(self.dataset);dataset['captures'][7]['counts']['2']+=70
        result=fit_calibration(self.machine,dataset)
        self.assertEqual(result['status'],'REJECT')
        self.assertGreater(result['fit']['max_mm'],1.5)

    def test_heldout_error_is_rejected(self):
        dataset=copy.deepcopy(self.dataset);dataset['captures'][-1]['counts']['4']+=80
        result=fit_calibration(self.machine,dataset)
        self.assertEqual(result['status'],'REJECT')
        self.assertIn('validation_residual_above_1.5mm',result['reasons'])

    def test_template_is_blank_not_measurement(self):
        dataset=capture_template()
        self.assertEqual(len(dataset['captures']),27)
        with self.assertRaisesRegex(ValueError,'integers'):fit_calibration(self.machine,dataset)

    def test_no_tilt_diversity_rejected(self):
        dataset=copy.deepcopy(self.dataset)
        for start in range(0,27,3):
            for row in dataset['captures'][start:start+3]:
                row['counts']=copy.deepcopy(dataset['captures'][start+1]['counts'])
        with self.assertRaisesRegex(ValueError,'pitch spread'):fit_calibration(self.machine,dataset)

    def test_candidate_invalidates_old_plane_and_stale_fk_is_rejected(self):
        # Unit-test the measured gate with synthetic data only in memory. This
        # fabricated declaration must never be exported as actual measurement.
        dataset=copy.deepcopy(self.dataset);dataset['source']='measured'
        machine=copy.deepcopy(self.machine)
        machine['paper']['xy_calibration']={'obsolete':True}
        result=fit_calibration(machine,dataset)
        candidate=make_candidate(machine,dataset,result)
        self.assertNotIn('xy_calibration',candidate['paper'])
        self.assertFalse(candidate['checks']['kinematics'])
        self.assertEqual(candidate['paper']['geometry_mode'],'four_point')
        self.assertEqual(validate_acceptance(candidate)['status'],'ACCEPT')
        candidate['joints'][1]['zero_count']+=1
        with self.assertRaisesRegex(ValueError,'TCP'):validate_acceptance(candidate)

    def test_candidate_requires_exact_source_dataset(self):
        dataset=copy.deepcopy(self.dataset);dataset['source']='measured'
        result=fit_calibration(self.machine,dataset)
        dataset['captures'][0]['counts']['1']+=1
        with self.assertRaisesRegex(ValueError,'changed'):make_candidate(self.machine,dataset,result)

    def test_axis_fit_requires_external_confirmation_and_distinct_poses(self):
        rows=[]
        for count in (1950,2048,2150):
            rows.append(dict(source='measured',externally_vertical_confirmed=True,
                counts={'1':count,'2':2048,'3':2048,'4':3072,'5':2048}))
        result=fit_pen_axis(self.machine,rows)
        self.assertEqual(result['status'],'ACCEPT')
        np.testing.assert_allclose(result['tool_axis_local'],[1,0,0],atol=1e-12)
        rows[0]['externally_vertical_confirmed']=False
        with self.assertRaisesRegex(ValueError,'external'):fit_pen_axis(self.machine,rows)

    def test_cli_cannot_replace_machine_or_capture_input_with_report(self):
        from scripts.kinematic_calibration import main
        for output in ('machine.json','captures.json'):
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as caught:
                main(['fit','--machine','machine.json','--captures','captures.json','--report',output])
            self.assertEqual(caught.exception.code,2)


if __name__=='__main__':unittest.main()
