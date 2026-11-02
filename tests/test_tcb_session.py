import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from tcb705.planning_session import PlanningSession
from tcb705.planning_batches import ChainDispatcher

class SessionTests(unittest.TestCase):
    def core(self):return SimpleNamespace(transport=SimpleNamespace(faulted=False),close=Mock())

    def test_reuses_single_owned_core_and_closes_once(self):
        core=self.core();session=PlanningSession()
        with patch('tcb705.accel_runtime.open_accelerator',return_value=(core,None)) as open_core,patch('tcb705.planner._plan',side_effect=lambda *a:{'metrics':{}}) as run:
            session.plan({},{});session.plan({},{})
            open_core.assert_called_once();self.assertEqual(run.call_count,2)
            self.assertTrue(all(call.args[-1] is core for call in run.call_args_list))
            core.close.assert_not_called()
            session.close();session.close();core.close.assert_called_once()
            with self.assertRaisesRegex(RuntimeError,'closed'):session.plan({},{})

    def test_faulted_session_keeps_dma_owner_but_uses_cpu(self):
        core=self.core();session=PlanningSession()
        with patch('tcb705.accel_runtime.open_accelerator',return_value=(core,None)),patch('tcb705.planner._plan',return_value={'metrics':{}}) as run:
            session.prepare();core.transport.faulted=True
            result=session.plan({},{})
            self.assertIsNone(run.call_args.args[-1]);self.assertIn('faulted',result['metrics']['ik_accel_unavailable_reason'])
            core.close.assert_not_called()
        session.close()

    def test_fork_cannot_attach_or_release_parent_session(self):
        session=PlanningSession()
        with patch('os.getpid',return_value=os.getpid()+1),patch('tcb705.accel_runtime.open_accelerator') as open_core:
            with self.assertRaisesRegex(RuntimeError,'fork'):session.prepare()
            with self.assertRaisesRegex(RuntimeError,'inherited'):session.close()
            open_core.assert_not_called()

    def test_metrics_are_per_plan_not_lifetime(self):
        core=SimpleNamespace(transport=SimpleNamespace(starts=30),accepted=1000,refused=2)
        dispatcher=ChainDispatcher(None,core)
        self.assertEqual(dispatcher.metrics()['ik_backend'],'ZYNQ_CPU_NATIVE_7R_BATCH')
        core.transport.starts+=2;core.accepted+=64;core.refused+=1
        metrics=dispatcher.metrics()
        self.assertEqual(metrics['pl_batch_starts'],2)
        self.assertEqual(metrics['pl_rows_cpu_verified'],64)
        self.assertEqual(metrics['pl_rows_cpu_rejected'],1)

    def test_explicit_cpu_does_not_attach_pl_or_change_an_existing_owner(self):
        core=self.core();session=PlanningSession()
        with patch('tcb705.accel_runtime.open_accelerator',return_value=(core,None)) as attach, \
                patch('tcb705.planner._plan',return_value={'metrics':{}}) as run:
            result=session.plan_cpu({}, {}, [0]*7)
            attach.assert_not_called();self.assertFalse(session.opened)
            self.assertIsNone(run.call_args.args[-1])
            self.assertEqual(result['metrics']['backend_selection'],'explicit_cpu')
            session.prepare();session.plan_cpu({}, {}, [0]*7)
            self.assertIs(session.core,core);attach.assert_called_once()
            core.close.assert_not_called()
            session.close()
            with self.assertRaisesRegex(RuntimeError,'closed'):session.plan_cpu({}, {})

if __name__=='__main__':unittest.main()
