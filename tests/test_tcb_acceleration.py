"""Precision, prefix invalidation and ABI tests; no hardware or physical motion."""
import copy,sys,unittest
import numpy as np
from tcb705.config import demo_config
from tcb705.model import Model,ROOT
from tcb705.planner import plan,extrema
from tcb705.planning_batches import ChainDispatcher,PLChain
from tcb705 import accel_contract as c
from planner_accel_backend import NativePlannerTransport

class AccelerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg=demo_config();cls.model=Model(cls.cfg)
        cls.library=ROOT/'build/tcb705'/('tcb_pl_sim.dll' if sys.platform=='win32' else 'libtcb_pl_sim.so')
    def transport(self):return NativePlannerTransport(self.library,protocol=c)
    def targets(self,n=5):
        start=self.model.fk(self.cfg['q_start_rad']);targets=np.tile(start,(n,1,1))
        targets[:,0,3]+=np.arange(1,n+1)*.0005
        return targets
    def test_native_extrema_match_numpy_random_all_orders(self):
        rng=np.random.RandomState(24);coeff=rng.normal(size=(256,6,7))*10**rng.uniform(-6,2,(256,1,1))
        actual=self.model.extrema_batch(coeff)
        for i,row in enumerate(coeff):
            for order in range(4):np.testing.assert_allclose(actual[i,order],np.array(extrema(row,order)),atol=4e-9,rtol=2e-11)
    def test_repeated_nearby_endpoint_and_degenerate_roots(self):
        coeff=np.zeros((12,6,7));sets=[[.5,.5,.5,.5],[0,0,1,1],[.1,.10000001,.7,.9],[.5,.5]]
        for i in range(12):
            derivative=np.polynomial.polynomial.polyfromroots(sets[i%4]);p=np.polynomial.polynomial.polyint(derivative)
            coeff[i,:len(p),:]=p[:,None]
        bounds=self.model.extrema_batch(coeff)
        us=np.linspace(0,1,10001)
        for i,row in enumerate(coeff):
            for order in range(4):
                vals=np.polynomial.polynomial.polyval(us,row).T
                self.assertTrue(np.all(vals.min(axis=0)>=bounds[i,order,1]-1e-12))
                self.assertTrue(np.all(vals.max(axis=0)<=bounds[i,order,2]+1e-12))
                row=row[1:]*np.arange(1,len(row))[:,None]
    def test_cpu_chain_matches_scalar_exactly(self):
        # Chain row k starts from the linear extrapolation of the two previous solutions
        # (same rule as the PL core) with the previous solution as reference.
        targets=self.targets();q=np.array(self.cfg['q_start_rad']);before=None;batch=self.model.solve_chain(targets,q)
        for target,row in zip(targets,batch):
            start=q if before is None else np.clip(2*q-before,self.model.lower,self.model.upper)
            scalar=self.model.solve(target,start,q);np.testing.assert_array_equal(row['q'],scalar['q']);before,q=q,row['q']
    def test_hls_chain_is_accepted_after_joint_checks(self):
        transport=self.transport();pl=PLChain(transport);targets=self.targets()
        result=pl.solve_chain(self.model,targets,self.cfg['q_start_rad'],lambda:False)
        self.assertEqual(len(result),len(targets));self.assertEqual(transport.starts,1)
        cpu=self.model.solve_chain(targets,self.cfg['q_start_rad'])
        for a,b in zip(result,cpu):np.testing.assert_allclose(a['q'],b['q'],atol=1e-12)
    def test_seed_change_invalidates_speculative_suffix(self):
        d=ChainDispatcher(self.model);targets=self.targets();q=np.array(self.cfg['q_start_rad'])
        first=d.next(targets,q);q=first['q'].copy();q[0]+=1e-5
        second=d.next(targets[1:],q)
        expected=self.model.solve(targets[1],q,q)
        np.testing.assert_array_equal(second['q'],expected['q']);self.assertEqual(d.invalidations,1);self.assertEqual(d.batches,2)
    def test_rejected_hardware_proposal_uses_cpu(self):
        class Bad:
            def solve_chain(self,*args):raise ValueError('injected transport fault')
        d=ChainDispatcher(self.model,Bad());row=d.next(self.targets(),self.cfg['q_start_rad'])
        self.assertTrue(row['ok']);self.assertEqual(d.fallbacks,1);self.assertIsNone(d.accelerator)
    def test_empty_hardware_prefix_records_cpu_fallback(self):
        class Empty:
            accepted=0
            def solve_chain(self,*args):return []
        d=ChainDispatcher(self.model,Empty());row=d.next(self.targets(),self.cfg['q_start_rad'])
        self.assertTrue(row['ok']);self.assertEqual(d.fallbacks,1)
        self.assertEqual(d.metrics()['ik_cpu_batches'],1)
        self.assertEqual(d.metrics()['ik_backend'],'ZYNQ_CPU_NATIVE_7R_BATCH')
    def test_base_transform_supported_in_hardware_chain(self):
        cfg=copy.deepcopy(self.cfg);base=np.eye(4);base[:3,3]=[.02,-.03,.04];cfg['T_controller_base_from_model']=base.tolist()
        m=Model(cfg);targets=np.matmul(base,self.targets());pl=PLChain(self.transport())
        rows=pl.solve_chain(m,targets,cfg['q_start_rad'],lambda:False)
        self.assertEqual(len(rows),len(targets))
    def test_fk_rows_full_seven_axis_pose(self):
        ctx=c.context(self.model,self.cfg['q_start_rad'],np.eye(3));data=np.zeros(17,dtype=c.FK_INPUT)
        data['q']=self.cfg['q_start_rad'];data['q'][:,6]+=np.arange(17)*.001;data['id']=np.arange(17)
        h,rows=self.transport().execute(ctx,c.FK_ROWS,data,5,3)
        self.assertEqual(h['status'],0);np.testing.assert_allclose(rows['pose'],self.model.fk_batch(data['q']),atol=1e-13)
    def test_cancel_and_bad_model_do_not_return_success(self):
        ctx=c.context(self.model,self.cfg['q_start_rad'],np.eye(3));data=np.zeros(1,dtype=c.FK_INPUT);data['q']=self.cfg['q_start_rad']
        tr=self.transport();h,rows=tr.execute(ctx,c.FK_ROWS,data,3,4,cancel=lambda:True)
        self.assertEqual(h['status'],2);self.assertEqual(len(rows),0)
        ctx['model_id']=123;h,rows=tr.execute(ctx,c.FK_ROWS,data,3,5)
        self.assertEqual(h['status'],4);self.assertEqual(len(rows),0)
    def test_plan_hls_matches_within_one_sdk_float_ulp_without_runtime_fk(self):
        paths=dict(units='mm',width_mm=100,height_mm=100,paths=[[[40,45],[60,45]],[[40,55],[60,55]]])
        cpu=plan(paths,self.cfg);pl=plan(paths,self.cfg,accelerator=PLChain(self.transport()))
        np.testing.assert_array_max_ulp(pl['sdk_degrees'],cpu['sdk_degrees'],maxulp=1)
        np.testing.assert_allclose(pl['times'],cpu['times'],atol=1e-6,rtol=0)
        self.assertIsNone(pl['metrics']['max_path_error_m'])
        self.assertIsNone(pl['metrics']['max_orientation_error_rad'])
        self.assertEqual(pl['metrics']['ik_batches'],3)
        self.assertEqual(pl['metrics']['geometry_fk_batches'],0)
        self.assertEqual(pl['metrics']['geometry_probe_samples'],0)
        self.assertFalse(pl['metrics']['runtime_geometry_verification'])
    def test_wrong_generation_rejected(self):
        ctx=c.context(self.model,self.cfg['q_start_rad'],np.eye(3));data=np.zeros(1,dtype=c.FK_INPUT);header=np.zeros(1,dtype=c.HEADER)
        with self.assertRaises(FloatingPointError):c.validate_completion(header,np.zeros(1,dtype=c.FK_OUTPUT),data,ctx,c.FK_ROWS,1,1)

if __name__=='__main__':unittest.main()
