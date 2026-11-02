"""Partial-prefix / cancellation contract tests; no SDK, board or robot motion."""
import unittest
import numpy as np
from tcb705 import accel_contract as c
from tcb705.planning_batches import ChainDispatcher, PLChain, PlanningCancelled


class FakeModel:
    base_identity=True
    def __init__(self):
        self.data=np.zeros((7,21));self.tool=np.eye(4)
        self.lower=np.full(7,-1.);self.upper=np.full(7,1.)
        self.config={'ik':dict(position_tolerance_m=1e-7,orientation_tolerance_rad=1e-6,
                               max_iterations=20,step_limit_rad=.15,damping=.0001,reference_weight=1e-9)}
        self.fk_calls=[];self.cpu_calls=[]
    def fk_batch(self,q):
        self.fk_calls.append(q.copy());poses=np.tile(np.eye(4),(len(q),1,1))
        poses[:,:3,3]=q[:,:3];return poses
    def solve_chain(self,targets,seed):
        self.cpu_calls.append((targets.copy(),np.asarray(seed).copy()))
        rows=[]
        for target in targets:
            q=np.asarray(seed).copy();q[:3]=target[:3,3]
            rows.append(dict(ok=True,status=0,q=q,iterations=0,position_error_m=0.,orientation_error_rad=0.))
        return rows


class ScriptedTransport:
    """Returns real ABI-validated completion slices for a scripted FPGA run."""
    def __init__(self,script,corrupt=None,corrupt_delta=.01):
        self.script=list(script);self.starts=0;self.seeds=[];self.corrupt=corrupt;self.corrupt_delta=corrupt_delta
    def execute(self,ctx,mode,inputs,job_id,generation,cancel):
        status,done=self.script.pop(0);self.starts+=1;self.seeds.append(ctx['seed'][0].copy())
        if done is None:done=len(inputs)
        rows=np.zeros(len(inputs),dtype=c.IK_OUTPUT)
        rows['q'][:,:3]=inputs['position'];rows['id']=inputs['id']
        rows['generation']=generation;rows['context_id']=int(ctx['context_id'][0])
        if status==1:rows['status'][done-1]=1
        if self.corrupt is not None:rows['q'][self.corrupt,0]+=self.corrupt_delta
        header=np.zeros(1,dtype=c.HEADER)
        values=dict(abi=c.MAGIC,status=status,job_id=job_id,generation=generation,
                    context_id=int(ctx['context_id'][0]),mode=mode,requested=len(inputs),
                    done_count=done,first_error=done-1 if status==1 else done if status==2 else 0xffffffff)
        for key,value in values.items():header[key]=value
        return c.validate_completion(header,rows,inputs,ctx,mode,job_id,generation)


class PartialPrefixTests(unittest.TestCase):
    def setUp(self):
        self.model=FakeModel();self.seed=np.zeros(7)
        self.targets=np.tile(np.eye(4),(5,1,1))
        self.targets[:,0,3]=np.arange(1,6)*.001
        self.targets[:,1,3]=np.arange(1,6)*.002
    def test_complete_batch_checks_joints_without_recomputing_fk(self):
        pl=PLChain(ScriptedTransport([(0,None)]))
        rows=pl.solve_chain(self.model,self.targets,self.seed,lambda:False)
        self.assertEqual(len(rows),5);self.assertEqual(pl.accepted,5);self.assertEqual(pl.refused,0)
        np.testing.assert_array_equal(np.asarray([r['q'][:3] for r in rows]),self.targets[:,:3,3])
        self.assertEqual(self.model.fk_calls,[])
        self.assertTrue(all(r['position_error_m'] is None and not r['geometry_verified'] for r in rows))
    def test_partial_one_row_returns_no_candidate(self):
        pl=PLChain(ScriptedTransport([(1,1)]))
        self.assertEqual(pl.solve_chain(self.model,self.targets,self.seed,lambda:False),[])
        self.assertEqual(pl.accepted,0);self.assertEqual(pl.refused,1)
        self.assertEqual(pl.last_rejection['row'],0);self.assertEqual(self.model.fk_calls,[])
    def test_partial_three_rows_preserves_only_first_two(self):
        pl=PLChain(ScriptedTransport([(1,3)]))
        rows=pl.solve_chain(self.model,self.targets,self.seed,lambda:False)
        self.assertEqual(len(rows),2);self.assertEqual(pl.accepted,2);self.assertEqual(pl.refused,1)
        self.assertEqual(pl.last_rejection['row'],2);self.assertEqual(self.model.fk_calls,[])
        np.testing.assert_array_equal(rows[-1]['q'][:3],self.targets[1,:3,3])
    def test_geometric_residual_is_explicitly_not_rechecked(self):
        pl=PLChain(ScriptedTransport([(0,None)],corrupt=1))
        rows=pl.solve_chain(self.model,self.targets,self.seed,lambda:False)
        self.assertEqual(len(rows),5);self.assertEqual(pl.refused,0)
        self.assertIsNone(rows[1]['position_error_m']);self.assertEqual(self.model.fk_calls,[])
    def test_joint_step_still_rejects_success_row_and_suffix(self):
        pl=PLChain(ScriptedTransport([(0,None)],corrupt=1,corrupt_delta=.2))
        rows=pl.solve_chain(self.model,self.targets,self.seed,lambda:False)
        self.assertEqual(len(rows),1);self.assertEqual(pl.refused,1)
        self.assertGreater(pl.last_rejection['joint_step_rad'],self.model.config['ik']['step_limit_rad'])
    def test_joint_limit_still_rejects_success_row_and_suffix(self):
        self.model.upper[0]=.0015
        pl=PLChain(ScriptedTransport([(0,None)]))
        rows=pl.solve_chain(self.model,self.targets,self.seed,lambda:False)
        self.assertEqual(len(rows),1);self.assertEqual(pl.last_rejection['row'],1)
    def test_dispatcher_consumes_prefix_then_resumes_at_failed_target_with_last_seed(self):
        transport=ScriptedTransport([(1,3),(1,1)]);pl=PLChain(transport)
        dispatcher=ChainDispatcher(self.model,pl)
        first=dispatcher.next(self.targets,self.seed)
        second=dispatcher.next(self.targets[1:],first['q'])
        self.assertEqual(transport.starts,1);self.assertEqual(len(self.model.cpu_calls),0)
        third=dispatcher.next(self.targets[2:],second['q'])
        self.assertEqual(transport.starts,2);self.assertEqual(len(self.model.cpu_calls),1)
        np.testing.assert_array_equal(transport.seeds[1],second['q'])
        np.testing.assert_array_equal(self.model.cpu_calls[0][1],second['q'])
        np.testing.assert_array_equal(self.model.cpu_calls[0][0],self.targets[2:])
        np.testing.assert_array_equal(third['q'][:3],self.targets[2,:3,3])
        self.assertIs(dispatcher.accelerator,pl);self.assertEqual(dispatcher.errors,0)
    def test_cancelled_zero_prefix_never_launches_cpu_or_verifies_empty_rows(self):
        pl=PLChain(ScriptedTransport([(2,0)]));dispatcher=ChainDispatcher(self.model,pl)
        with self.assertRaisesRegex(PlanningCancelled,'CANCELLED'):
            dispatcher.next(self.targets,self.seed)
        self.assertEqual(self.model.cpu_calls,[]);self.assertEqual(self.model.fk_calls,[])
        self.assertIs(dispatcher.accelerator,pl);self.assertEqual(dispatcher.errors,0)
        self.assertEqual(dispatcher.fallbacks,0)
    def test_cancelled_nonempty_prefix_is_not_returned_to_the_plan(self):
        pl=PLChain(ScriptedTransport([(2,2)]));dispatcher=ChainDispatcher(self.model,pl)
        with self.assertRaises(PlanningCancelled):dispatcher.next(self.targets,self.seed)
        self.assertEqual(pl.accepted,0);self.assertEqual(self.model.cpu_calls,[])
    def test_cancelled_before_launch_does_not_call_transport(self):
        tr=ScriptedTransport([(0,None)]);pl=PLChain(tr)
        with self.assertRaises(PlanningCancelled):pl.solve_chain(self.model,self.targets,self.seed,lambda:True)
        self.assertEqual(tr.starts,0)
    def test_cancelled_cached_prefix_is_discarded(self):
        flag=[False];pl=PLChain(ScriptedTransport([(0,None)]))
        dispatcher=ChainDispatcher(self.model,pl,cancel=lambda:flag[0])
        first=dispatcher.next(self.targets,self.seed);flag[0]=True
        with self.assertRaises(PlanningCancelled):dispatcher.next(self.targets[1:],first['q'])
        self.assertEqual(dispatcher.rows,[]);self.assertEqual(self.model.cpu_calls,[])
    def test_cancel_before_accepting_joint_checked_rows(self):
        checks=[0]
        def cancel():
            checks[0]+=1;return checks[0]>=3
        pl=PLChain(ScriptedTransport([(0,None)]))
        with self.assertRaises(PlanningCancelled):
            pl.solve_chain(self.model,self.targets,self.seed,cancel)
        self.assertEqual(pl.accepted,0)
    def test_cancel_during_cpu_fallback_discards_computed_batch(self):
        flag=[False];original=self.model.solve_chain
        def cancel_during_cpu(targets,seed):
            result=original(targets,seed);flag[0]=True;return result
        self.model.solve_chain=cancel_during_cpu
        dispatcher=ChainDispatcher(self.model,cancel=lambda:flag[0])
        with self.assertRaises(PlanningCancelled):dispatcher.next(self.targets,self.seed)
        self.assertEqual(dispatcher.rows,[]);self.assertEqual(dispatcher.accepted,0)


if __name__=='__main__':unittest.main()
