"""The unevaluated FP32 sentinel stays unknown across ABI, diagnostics and JSON."""
import json,unittest
import numpy as np
from tcb705 import accel_contract as c
from tcb705.planning_batches import PLChain
from tests.test_tcb_partial_prefix import FakeModel
from scripts.tcb705_joint_draw import path_error_text


class Transport:
    def __init__(self,partial=False,fp32=True):self.partial,self.fp32=partial,fp32
    def execute(self,ctx,mode,inputs,job_id,generation,cancel):
        rows=np.zeros(len(inputs),dtype=c.IK_OUTPUT)
        rows['q'][:,:3]=inputs['position'];rows['id']=inputs['id']
        rows['generation']=generation;rows['context_id']=ctx['context_id'][0]
        rows['stats'][:,:2]=np.nan if self.fp32 else .000123
        if self.partial:rows['status'][-1]=1;rows['stats'][-1]=0
        header=np.zeros(1,dtype=c.HEADER)
        values=dict(abi=c.MAGIC,status=int(self.partial),job_id=job_id,generation=generation,
                    context_id=int(ctx['context_id'][0]),mode=mode,requested=len(inputs),done_count=len(inputs),
                    first_error=len(inputs)-1 if self.partial else 0xffffffff,
                    capabilities=c.FP32_CAPABILITIES if self.fp32 else 0)
        for key,value in values.items():header[key]=value
        return c.validate_completion(header,rows,inputs,ctx,mode,job_id,generation,
                                     expected_capabilities=values['capabilities'])


class UnknownResidualTests(unittest.TestCase):
    def setUp(self):
        self.model=FakeModel();self.targets=np.tile(np.eye(4),(2,1,1))
        self.targets[:,0,3]=[.001,.002]
    def test_fp32_success_and_partial_diagnostics_are_json_null(self):
        pl=PLChain(Transport(partial=True))
        rows=pl.solve_chain(self.model,self.targets,np.zeros(7),lambda:False)
        self.assertEqual(len(rows),1)
        self.assertIsNone(rows[0]['position_error_m'])
        self.assertIsNone(rows[0]['orientation_error_rad'])
        self.assertIsNone(pl.last_rejection['pl_position_error_m'])
        self.assertIsNone(pl.last_rejection['pl_orientation_error_rad'])
        # Strict JSON forbids leaking the binary NaN sentinel to app state.
        public={k:v for k,v in rows[0].items() if k!='q'}
        text=json.dumps(dict(row=public,rejection=pl.last_rejection),allow_nan=False)
        self.assertNotIn('NaN',text);self.assertIn('null',text)
    def test_fp32_joint_rejection_also_keeps_residual_unknown(self):
        self.model.upper[0]=.0015
        pl=PLChain(Transport());pl.solve_chain(self.model,self.targets,np.zeros(7),lambda:False)
        self.assertIsNone(pl.last_rejection['pl_position_error_m'])
        self.assertIsNone(pl.last_rejection['pl_orientation_error_rad'])
        json.dumps(pl.last_rejection,allow_nan=False)
    def test_legacy_measured_residual_is_preserved(self):
        self.model.upper[0]=.0015
        pl=PLChain(Transport(fp32=False));pl.solve_chain(self.model,self.targets,np.zeros(7),lambda:False)
        self.assertEqual(pl.last_rejection['pl_position_error_m'],.000123)
        self.assertEqual(pl.last_rejection['pl_orientation_error_rad'],.000123)
    def test_cli_prints_unknown_without_zero_or_crash(self):
        for value in (None,float('nan'),float('inf')):self.assertEqual(path_error_text(value),'未评估')
        self.assertEqual(path_error_text(0.),'0.0000 mm')
        self.assertEqual(path_error_text(.000123),'0.1230 mm')


if __name__=='__main__':unittest.main()
