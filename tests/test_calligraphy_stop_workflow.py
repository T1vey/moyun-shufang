"""Calligraphy stop ownership, repeated-stop handling and homing status, without hardware."""
import copy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch

from scripts.arm_studio import BoardConnectionError
from tcb705.workbench import TCBWorkbench,_StopRequests
from user_gui.workflow import BoardPipeline,Cancelled,Workflow


class StopRequestsTests(unittest.TestCase):
    def test_only_second_request_cancels_return_and_clear_resets(self):
        token=_StopRequests()
        self.assertFalse(token.is_set());self.assertFalse(token.recovery_cancelled())
        token.set();self.assertTrue(token.is_set());self.assertFalse(token.recovery_cancelled())
        token.set();self.assertTrue(token.recovery_cancelled())
        token.clear();self.assertFalse(token.is_set());self.assertFalse(token.recovery_cancelled())

    def test_workbench_persists_home_result_even_when_execution_cancelled(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);board=TCBWorkbench.__new__(TCBWorkbench)
            board.state=Mock();board.state.lock=threading.Lock();board.state.lock.acquire()
            board._jobs_lock=threading.Lock();board.jobs={};board.active='run';board.plans={
                'plan':{'folder':folder,'doc':{},'nodes':{}}}
            board.machine={};board.simulation=False;board.cancel=_StopRequests();board.allow_motion=False
            job={'id':'run','kind':'execute','status':'RUNNING'}
            def execute(*args,**kw):
                kw['progress']({'event':'HOME_START'})
                self.assertEqual(board.snapshot()['jobs'][0]['motion_stage'],'HOME')
                board.stop();self.assertFalse(kw['recovery_cancel']())
                kw['progress']({'event':'HOME_AFTER_STOP_START'})
                kw['progress']({'event':'HOME_AFTER_STOP_DONE'})
                raise ValueError('CANCELLED: 用户停止')
            with patch('tcb705.bridge.execute',side_effect=execute):board._run(job,folder,{'plan_job':'plan'})
            saved=board.snapshot()['jobs'][0]
            self.assertEqual(saved['home_after_stop_status'],'done')
            self.assertEqual(saved['motion_stage'],'HOME_AFTER_STOP_DONE')
            self.assertEqual(saved['status'],'FAILED');self.assertIsNone(board.active)
            self.assertFalse(board.state.lock.locked())

    def test_bridge_forwards_recovery_cancel_without_motion(self):
        from tcb705.bridge import execute
        callback=lambda:False
        with patch('tcb705.bridge.web_program_enabled',return_value=True), \
             patch('tcb705.sdk_motion.sdk_enabled',return_value=False), \
             patch('tcb705.web_executor.execute',return_value={'ok':True}) as backend:
            self.assertEqual(execute(None,{},recovery_cancel=callback),{'ok':True})
            self.assertIs(backend.call_args.kwargs['recovery_cancel'],callback)


class StopPollingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.pipeline=BoardPipeline('http://127.0.0.1:8785',self.tmp.name)
        self.pipeline.client=Mock();self.pipeline.poll_s=.001

    def snapshot(self,stage='HOME_AFTER_STOP',active='run',status='RUNNING',**extra):
        job=dict(id='run',kind='execute',status=status,motion_stage=stage,detail='CANCELLED: 用户停止')
        job.update(extra)
        return dict(active=active,jobs=[job])

    def test_waits_for_actual_backend_exit_and_never_repeats_first_stop(self):
        pipe=self.pipeline;pipe.client.get_jobs.return_value=self.snapshot()
        pipe.stop_execution(first_only=True)
        final=self.snapshot('HOME_AFTER_STOP_DONE',status='FAILED',home_after_stop_status='done')
        released=copy.deepcopy(final);released['active']=None
        pipe.client.get_jobs.side_effect=[self.snapshot(),final,released]
        progress=[]
        with self.assertRaisesRegex(Cancelled,'已停止书写并归位'):
            pipe._wait('run',lambda:True,wait_after_cancel=True,progress=progress.append)
        pipe.client.stop.assert_called_once_with()
        self.assertEqual(len(progress),3)

    def test_acceptance_race_sends_one_initial_stop_and_explicit_second_still_works(self):
        pipe=self.pipeline
        pipe.client.get_jobs.side_effect=[self.snapshot(),self.snapshot('HOME_AFTER_STOP_DONE',None,'FAILED',home_after_stop_status='done')]
        with self.assertRaises(Cancelled):pipe._wait('run',lambda:True,wait_after_cancel=True)
        pipe.client.stop.assert_called_once_with()
        pipe.client.get_jobs.side_effect=None;pipe.client.get_jobs.return_value=self.snapshot()
        pipe.stop_execution(first_only=True)
        self.assertEqual(pipe.client.stop.call_count,1)
        pipe.stop_execution();self.assertEqual(pipe.client.stop.call_count,2)

    def test_second_click_during_execute_post_is_not_lost(self):
        pipe=self.pipeline;pipe.check_plan=Mock();pipe.robot_type='TCB705';pipe.simulation=False
        pipe.client.get_jobs.return_value={'active':None,'jobs':[]}
        def accepted(*args,**kwargs):
            pipe.stop_execution(first_only=True);pipe.stop_execution()
            return {'id':'run'}
        pipe.client._request.side_effect=accepted
        pipe._wait=Mock(return_value={'result':{'robot_type':'TCB705','status':'DONE'}})
        pipe.execute('plan',lambda:False,calligraphy=True)
        self.assertEqual(pipe.client.stop.call_count,2)

    def test_lost_execute_reply_clears_pending_and_never_retries_motion(self):
        pipe=self.pipeline;pipe.check_plan=Mock();pipe.robot_type='TCB705';pipe.simulation=False
        pipe.client._request.side_effect=BoardConnectionError('execute reply lost')
        with self.assertRaises(BoardConnectionError):pipe.execute('plan',lambda:False,calligraphy=True)
        self.assertFalse(pipe._pending_calligraphy_execute);self.assertEqual(pipe._deferred_stop_count,0)
        pipe.client._request.assert_called_once();pipe.client.stop.assert_not_called()

    def test_return_failure_is_not_reported_as_return_complete(self):
        self.pipeline.client.get_jobs.return_value=self.snapshot('HOME_AFTER_STOP_FAILED',None,'FAILED',
            home_after_stop_status='failed',detail='HOME_AFTER_STOP_FAILED: feedback lost')
        with self.assertRaisesRegex(ValueError,'feedback lost'):
            self.pipeline._wait('run',lambda:True,wait_after_cancel=True)
        self.pipeline.client.stop.assert_not_called()

    def test_late_cancel_after_normal_home_keeps_confirmed_home_result(self):
        self.pipeline.client.get_jobs.return_value=self.snapshot('RETURN_HOME_DONE',None,'FAILED')
        with self.assertRaisesRegex(Cancelled,'已停止书写并归位'):
            self.pipeline._wait('run',lambda:True,wait_after_cancel=True)
        self.pipeline.client.stop.assert_not_called()

    def test_lost_stop_reply_does_not_automatically_send_second_stop(self):
        pipe=self.pipeline;pipe.client.get_jobs.return_value=self.snapshot()
        pipe.client.stop.side_effect=BoardConnectionError('lost reply')
        with self.assertRaises(BoardConnectionError):pipe.stop_execution(first_only=True)
        pipe.client.get_jobs.side_effect=[self.snapshot(),self.snapshot('HOME_AFTER_STOP_DONE',None,'FAILED',home_after_stop_status='done')]
        with self.assertRaises(Cancelled):pipe._wait('run',lambda:True,wait_after_cancel=True)
        pipe.client.stop.assert_called_once_with()


class WorkflowStopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.pipe=BoardPipeline('http://127.0.0.1:8785',self.tmp.name)
        self.pipe.robot_type='TCB705';self.pipe.simulation=False;self.pipe.busy=Mock(return_value=False)
        self.pipe.stop_execution=Mock()
        self.flow=Workflow(self.pipe,self.tmp.name)
        self.jid=self.flow.reserve('calligraphy')
        self.flow._plan_id='plan';self.flow._occupied=False
        self.flow._set(phase='ready',input_mode='calligraphy',can_start=True,can_cancel=True)

    def test_cancel_waits_and_keeps_second_stop_available_until_home_done(self):
        entered=threading.Event();release=threading.Event()
        def execute(*args,**kwargs):
            entered.set();release.wait(3)
            kwargs['progress']({'motion_stage':'HOME_AFTER_STOP','detail':'正在归位'})
            raise Cancelled('已停止书写并归位',{'motion_stage':'HOME_AFTER_STOP_DONE'})
        self.pipe.execute=execute
        self.flow.start(self.jid,self.flow.snapshot()['revision'],True);self.assertTrue(entered.wait(1))
        try:
            first=self.flow.cancel(self.jid)
            self.assertEqual(first['phase'],'stopping');self.assertTrue(first['can_cancel'])
            self.assertTrue(self.flow._occupied)
            self.flow.cancel(self.jid)
            self.assertEqual([c.kwargs for c in self.pipe.stop_execution.call_args_list],[{'first_only':True},{'first_only':False}])
        finally:release.set();self.flow.worker.join(3)
        final=self.flow.snapshot()
        self.assertEqual(final['phase'],'cancelled');self.assertEqual(final['message'],'已停止书写并归位')
        self.assertFalse(final['can_cancel']);self.assertFalse(self.flow._occupied)

    def test_normal_completion_claims_home_only_with_confirmed_stage(self):
        self.pipe.execute=Mock(return_value={'motion_stage':'RETURN_HOME_DONE','result':{'robot_type':'TCB705','status':'DONE'}})
        self.flow.start(self.jid,self.flow.snapshot()['revision'],True);self.flow.worker.join(3)
        self.assertEqual(self.flow.snapshot()['message'],'书写完成，已归位')

    def test_failed_return_keeps_stop_and_never_reports_home_done(self):
        self.pipe.execute=Mock(side_effect=ValueError('HOME_AFTER_STOP_FAILED: feedback lost'))
        self.flow.start(self.jid,self.flow.snapshot()['revision'],True);self.flow.worker.join(3)
        final=self.flow.snapshot();self.assertEqual(final['phase'],'error')
        self.assertTrue(final['can_cancel']);self.assertTrue(final['motion_uncertain'])
        self.assertNotIn('已归位',final['message'])
        requested=self.flow.cancel(self.jid)
        self.assertEqual(requested['phase'],'error')
        self.assertTrue(requested['motion_uncertain'])
        self.assertNotIn('已归位',requested['message'])
        self.assertIn(final['message'],requested['message'])
        self.assertEqual(requested['fault_message'],final['message'])
        repeated=self.flow.cancel(self.jid)
        self.assertEqual(repeated['message'],requested['message'])
        self.assertEqual([c.kwargs for c in self.pipe.stop_execution.call_args_list],
                         [{'first_only':True},{'first_only':False}])

    def test_failed_stop_request_preserves_original_fault_without_repeated_suffixes(self):
        self.flow._set(phase='error',motion_uncertain=True,motion_stage='RETURN_HOME_DONE',
                       message='归位后静止确认超时；后续动作未启动')
        self.pipe.stop_execution.side_effect=BoardConnectionError('stop reply lost')
        first=self.flow.cancel(self.jid)
        repeated=self.flow.cancel(self.jid)
        self.assertEqual(first['message'],repeated['message'])
        self.assertIn('归位后静止确认超时',first['message'])
        self.assertIn('停止请求未确认：stop reply lost',first['message'])
        self.assertEqual(first['motion_stage'],'RETURN_HOME_DONE')
        self.assertTrue(first['motion_uncertain'])
        self.assertEqual(self.pipe.stop_execution.call_count,2)

    def test_restore_wait_updates_same_stage_without_changing_motion_state(self):
        self.flow._set(phase='drawing',motion_stage='RETURN_HOME_DONE',motion_uncertain=False,
                       can_start=False,can_cancel=True,message='书写完成并已归位')
        self.flow._motion_progress(self.jid,{'motion_stage':'RETURN_HOME_DONE','restore_waiting':True,
            'detail':'已归位，正在确认静止，请稍候'})
        state=self.flow.snapshot()
        self.assertEqual(state['message'],'已归位，正在确认静止，请稍候')
        self.assertEqual(state['phase'],'drawing')
        self.assertEqual(state['motion_stage'],'RETURN_HOME_DONE')
        self.assertFalse(state['motion_uncertain']);self.assertFalse(state['can_start'])
        self.assertTrue(state['can_cancel'])
        self.flow._motion_progress('expired',{'motion_stage':'RETURN_HOME_DONE','restore_waiting':True,
            'detail':'wrong job'})
        self.assertEqual(self.flow.snapshot(),state)


if __name__=='__main__':unittest.main()
