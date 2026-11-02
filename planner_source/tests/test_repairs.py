import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from r1a import evidence
from r1a.model import Model
from r1a.solve import solve

ROOT=Path(__file__).resolve().parents[1]


class Repairs(unittest.TestCase):
    def test_success_precedes_stagnation_and_records_terminal(self):
        model=Model.load(ROOT/'config/nominal_so101.json')
        cfg=json.loads((ROOT/'config/contract.json').read_text())
        cfg.update(weights=[1e-12]*3+[2.5e-13]*3,mu=1e-15)
        r=solve(model,[.1357555492962473,-.09360858065887448,.24497320472038442],
                [.6092107121775784,-.7648974573646612,-.20927060922442955],
                [-1.4038168592658238,-.9186337857088221,.04386306487896552,.6945486832498169,-.5394337356791101],cfg)
        self.assertEqual(r.status,'OK')
        self.assertEqual(r.history[-1]['q'],r.q_last)
        self.assertEqual(r.history[-1]['iteration'],r.iterations)

    def test_failed_terminal_is_recorded(self):
        model=Model.load(ROOT/'config/nominal_so101.json')
        cfg=json.loads((ROOT/'config/contract.json').read_text())
        cfg.update(weights=[0]*6)
        r=solve(model,[5,5,5],[1,0,0],[0]*5,cfg)
        self.assertEqual(r.history[-1]['iteration'],r.iterations)
        self.assertEqual(r.history[-1]['q'],r.q_last)
        self.assertIsNone(r.q_solution)

    def test_last_allowed_iteration_may_succeed(self):
        model=Model.load(ROOT/'config/nominal_so101.json')
        cfg=json.loads((ROOT/'config/contract.json').read_text())
        target=np.array([.2,-.3,.5,-.2,.1]); t,_=model.evaluate(target)
        seed=target+np.array([.03,-.04,.02,.01,.07])
        first=solve(model,t[:3,3],t[:3,:3]@model.tool_axis,seed,cfg)
        self.assertEqual(first.status,'OK')
        cfg['max_iterations']=first.iterations
        self.assertEqual(solve(model,t[:3,3],t[:3,:3]@model.tool_axis,seed,cfg).status,'OK')

    def setup_run(self, path):
        (path/'source/config').mkdir(parents=True)
        (path/'source/config/contract.json').write_text('{}')
        (path/'source/kernel.cpp').write_text('original')
        evidence.freeze(path)
        (path/'result.log').write_text('ok')
        evidence.record(path,'test',['python','test'],0,['result.log'])

    def test_changed_source_cannot_be_certified(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t); self.setup_run(path)
            evidence.verify(path,['test'])
            (path/'source/kernel.cpp').write_text('#error changed')
            with self.assertRaisesRegex(ValueError,'input changed'): evidence.verify(path)
            with self.assertRaises(ValueError): evidence.record(path,'next',['cmd'],0,['result.log'])

    def test_changed_results_and_missing_stage_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t); self.setup_run(path)
            with self.assertRaisesRegex(ValueError,'stage sequence'): evidence.verify(path,['test','native'])
            (path/'result.log').write_text('changed')
            with self.assertRaisesRegex(ValueError,'evidence changed'): evidence.verify(path)

    def test_new_source_and_refreeze_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t); self.setup_run(path)
            with self.assertRaises(FileExistsError): evidence.freeze(path)
            (path/'source/injected.py').write_text('changed')
            with self.assertRaisesRegex(ValueError,'source set changed'): evidence.verify(path)

    def test_failed_stage_cannot_get_receipt(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t); self.setup_run(path)
            with self.assertRaises(ValueError): evidence.record(path,'failed',['cmd'],1,['result.log'])
            self.assertEqual(len(evidence.receipts(path)),1)

    def test_manifest_paths_stay_inside_run(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError): evidence.safe_path(t,'../outside')
