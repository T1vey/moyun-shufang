"""ArmStudio job ownership without Tk windows, network, or servo commands."""
import sys
import http.client
import io
import urllib.error
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.arm_studio import ArmStudio,BoardClient,BoardConnectionError


class Widget:
    def __init__(self, value=""):
        self.value = value
        self.options = {}
        self.index = -1

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        self.index = -1

    def config(self, **options):
        self.options.update(options)

    def current(self, index=None):
        if index is not None:
            self.index = index
        return self.index

    def __setitem__(self, key, value):
        self.options[key] = value


class QueuedRoot:
    def __init__(self):
        self.callbacks = []

    def after(self, delay, callback):
        self.callbacks.append(callback)

    def drain(self):
        while self.callbacks:
            self.callbacks.pop(0)()


class DeferredThreads:
    def __init__(self):
        self.targets = []

    def thread(self, target, **kwargs):
        return SimpleNamespace(start=lambda: self.targets.append(target))

    def run_next(self):
        self.targets.pop(0)()


def plan_info(job_id, mode="real", commands=158):
    return dict(id=job_id, mode=mode, commands=commands, duration_s=15,
                matches_current_calibration=True)


def studio_fixture():
    studio = ArmStudio.__new__(ArmStudio)
    studio.root = QueuedRoot()
    studio.image_job_id = "registered-image"
    studio.plan_job_id = None
    studio._planning_token = None
    studio._active_plan_job_id = None
    studio._plan_before_planning = None
    studio._execution_active = False
    studio._history_refresh_id = 0
    studio._plan_history = []
    studio.backend_name = "PL_z20_ik_target"
    studio.var_hw = Widget(False)
    studio.var_port = Widget("/dev/ttyACM0")
    studio.var_test_mm = Widget("40")
    for name in ("btn_plan", "btn_auto", "btn_make_test", "btn_home", "btn_exec_arm",
                 "btn_exec_history", "btn_preview", "cmb_plans", "lbl_plan_hist"):
        setattr(studio, name, Widget())
    studio.log_msg = Mock()
    studio.set_prog = Mock()
    studio.client = Mock(token="test-token")
    return studio


class PlanningJobTests(unittest.TestCase):
    def run_plan_with_snapshots(self, snapshots):
        studio = studio_fixture()
        studio.client.plan.return_value = {'id': 'submitted-new'}
        studio.client.get_jobs.side_effect = snapshots
        studio._log_plan_timing = Mock()
        studio._refresh_plans = Mock()
        callback = Mock()
        threads = DeferredThreads()
        with patch('scripts.arm_studio.threading.Thread', threads.thread), \
                patch('scripts.arm_studio.time.sleep'):
            studio._plan(callback)
            threads.run_next()
            studio.root.drain()
        studio.client.plan.assert_called_once()
        studio.client.execute.assert_not_called()
        return studio, callback

    def test_poll_disconnect_recovers_same_plan_after_publication(self):
        done = {'id': 'submitted-new', 'status': 'DONE', 'result': {'status': 'OK', 'metrics': {}}}
        studio, callback = self.run_plan_with_snapshots([
            BoardConnectionError('Remote end closed connection without response'),
            {'jobs': [done], 'active': 'submitted-new'},
            {'jobs': [done], 'active': None},
        ])
        self.assertEqual(studio.client.get_jobs.call_count, 3)
        self.assertEqual(studio.plan_job_id, 'submitted-new')
        callback.assert_called_once_with(True)
        self.assertTrue(any('连接已恢复' in c.args[0] for c in studio.log_msg.call_args_list))

    def test_poll_explicit_failure_or_missing_job_does_not_resubmit(self):
        for snapshots in ([{'jobs': [{'id': 'submitted-new', 'status': 'FAILED', 'detail': 'IK failed'}]}],
                          [{'jobs': [], 'active': None}] * 3):
            with self.subTest(snapshots=snapshots):
                studio, callback = self.run_plan_with_snapshots(snapshots)
                self.assertIsNone(studio.plan_job_id)
                callback.assert_called_once_with(False)

    def test_poll_continuous_disconnect_is_bounded(self):
        with patch('scripts.arm_studio.time.monotonic', side_effect=[0, 0, 0, 31]):
            studio, callback = self.run_plan_with_snapshots([BoardConnectionError('offline')])
        self.assertEqual(studio.client.get_jobs.call_count, 1)
        callback.assert_called_once_with(False)
        self.assertTrue(any('持续中断' in c.args[0] for c in studio.log_msg.call_args_list))

    def test_new_gui_refuses_old_board_pipeline_before_job_submission(self):
        client=BoardClient();client.fetch_status=Mock(return_value={'version':'old'})
        client._request=Mock()
        with self.assertRaisesRegex(RuntimeError,'板端仍使用旧绘画程序'):client.plan('image')
        with self.assertRaisesRegex(RuntimeError,'板端仍使用旧绘画程序'):client.execute('plan')
        client._request.assert_not_called()

    def test_old_pipeline_history_is_not_automatically_executable(self):
        studio=studio_fixture()
        old=dict(plan_info('old-real'),needs_replan=True)
        studio._apply_plan_history([old],['old'])
        self.assertIsNone(studio.plan_job_id)
        self.assertEqual(studio.btn_exec_arm.options['state'],'disabled')
        studio.cmb_plans.current(0);studio._on_pick_plan()
        self.assertIsNone(studio.plan_job_id)

    def test_history_selection_waits_for_new_extraction(self):
        studio=studio_fixture();studio._extraction_active=True
        studio._apply_plan_history([plan_info('old-real')],['old'])
        studio.cmb_plans.current(0);studio._on_pick_plan()
        self.assertIsNone(studio.plan_job_id)
        self.assertIsNone(studio._begin_planning())

    def test_timing_prefers_whole_job_and_shows_cpu_stages(self):
        studio=studio_fixture()
        studio.client.get_job_file.return_value=dict(job_ready_s=25.2,build_total_s=24.,
            ik_s=12.,interpolation_s=3.,quantization_s=1.,drawing_preview_s=.5,
            plan_save_s=2.,saved_plan_s=1.2)
        studio._log_plan_timing('current-real',{})
        studio.client.get_job_file.assert_called_once_with('current-real','timing.json')
        messages=[call.args[0] for call in studio.log_msg.call_args_list]
        self.assertIn('25.200s',messages[0])
        self.assertTrue(any('30 秒目标：达标' in line for line in messages))
        stages=next(line for line in messages if '插值' in line)
        for expected in ['3.000s','1.000s','0.500s','2.000s','1.200s']:
            self.assertIn(expected,stages)

    def test_timing_reports_missed_goal_and_this_job_pl_not_session_totals(self):
        studio=studio_fixture()
        studio.client.get_job_file.return_value=dict(job_ready_s=31.2,ik_s=12.)
        studio._log_plan_timing('current-real',dict(pl_session=dict(write_s=500.),
            pl_job=dict(write_s=.03,wait_s=.001,read_s=.02,validate_s=.01),
            planning_engine_version='planning-speed-v2',history_saved=False))
        messages=[call.args[0] for call in studio.log_msg.call_args_list]
        self.assertTrue(any('30 秒目标：未达标' in line for line in messages))
        line=next(line for line in messages if '本次 PL' in line)
        self.assertIn('0.030s',line);self.assertNotIn('500.000s',line)
        self.assertTrue(any('历史保存失败' in line for line in messages))

    def test_submitted_job_is_polled_and_reported_despite_stale_history(self):
        studio = studio_fixture()
        studio.plan_job_id = "previous-real"
        old = plan_info("old-demo", mode="demo")
        metrics = dict(completed_targets=1285, commands=8283, duration_s=700)
        studio.client.plan.return_value = {"id": "submitted-new"}
        studio.client.get_jobs.side_effect = [
            {"jobs": [{"id": "submitted-new", "status": "RUNNING"},
                      {"id": "old-demo", "status": "DONE", "result": {"metrics": {"commands": 158}}}]},
            {"jobs": [{"id": "submitted-new", "status": "DONE",
                       "result": {"status": "OK", "metrics": metrics}}]},
        ]
        threads = DeferredThreads()
        studio._log_plan_timing = Mock()
        studio._refresh_plans = Mock()
        callback = Mock()

        def old_history_arrives(_delay):
            studio._apply_plan_history([old], ["old-demo"])
            studio.cmb_plans.current(0)
            studio._on_pick_plan()  # Selection event queued before disabling.
            self.assertIsNone(studio.plan_job_id)
            self.assertEqual(studio.btn_exec_arm.options["state"], "disabled")
            # Independently prove that the worker polls its captured ID, even
            # if an unrelated callback erroneously mutates the UI selection.
            studio.plan_job_id = "old-demo"

        with patch("scripts.arm_studio.threading.Thread", threads.thread), \
                patch("scripts.arm_studio.time.sleep", old_history_arrives):
            studio._plan(callback)
            self.assertIsNone(studio.plan_job_id)
            threads.run_next()
            self.assertEqual(studio.client.get_jobs.call_count, 2)
            studio._log_plan_timing.assert_called_once_with("submitted-new", metrics)
            studio.root.drain()

        self.assertEqual(studio.plan_job_id, "submitted-new")
        self.assertIsNone(studio._planning_token)
        callback.assert_called_once_with(True)
        self.assertTrue(any("Job submitte" in call.args[0] for call in studio.log_msg.call_args_list))
        self.assertTrue(any("目标点 1285" in call.args[0] for call in studio.log_msg.call_args_list))

    def test_delayed_history_never_replaces_new_or_restored_job(self):
        studio = studio_fixture()
        studio.plan_job_id = "requested-restore"
        old = plan_info("old-demo", mode="demo")
        studio._apply_plan_history([old], ["old"])
        self.assertEqual(studio.plan_job_id, "requested-restore")
        self.assertEqual(studio.cmb_plans.current(), -1)
        new = plan_info("requested-restore", commands=8283)
        studio._apply_plan_history([old, new], ["old", "new"])
        self.assertEqual(studio.plan_job_id, "requested-restore")
        self.assertEqual(studio.cmb_plans.current(), 1)
        self.assertIn("8283", studio.lbl_plan_hist.options["text"])

    def test_failed_request_restores_previous_selection_before_callback(self):
        studio = studio_fixture()
        old = plan_info("previous-real")
        studio._plan_history = [old]
        studio.plan_job_id = old["id"]
        token = studio._begin_planning()
        self.assertIsNone(studio.plan_job_id)
        self.assertIsNone(studio._begin_planning())
        seen = []
        studio._finish_planning(token, "failed-new", False,
                                lambda ok: seen.append((ok, studio.plan_job_id, studio._planning_token)))
        self.assertEqual(studio.plan_job_id, "previous-real")
        self.assertEqual(studio.cmb_plans.current(), 0)
        self.assertEqual(seen, [(False, "previous-real", None)])
        self.assertEqual(studio.btn_exec_arm.options["state"], "normal")

    def test_pending_planning_rejects_history_execution_and_home(self):
        studio = studio_fixture()
        studio.plan_job_id = "old-plan"
        token = studio._begin_planning()
        self.assertIsNotNone(token)
        with patch("scripts.arm_studio.messagebox.showwarning") as warning:
            studio._execute_selected_plan()
            studio._drive_arm()
            studio._draw_home()
        self.assertFalse(studio.client.execute.called)
        self.assertFalse(studio.client.home.called)
        warning.assert_not_called()

    def test_automatic_execution_does_not_follow_a_changed_selection(self):
        studio = studio_fixture()
        studio.plan_job_id = "manually-selected-other"
        studio._drive_arm(expected_plan_job_id="just-planned")
        self.assertFalse(studio.client.execute.called)
        self.assertFalse(studio._execution_active)

    def test_only_latest_history_response_is_applied(self):
        studio = studio_fixture()
        threads = DeferredThreads()
        studio.client.plans.side_effect = [
            {"plans": [plan_info("outdated-demo", "demo")]},
            {"plans": [plan_info("restored-real")]},
        ]
        with patch("scripts.arm_studio.threading.Thread", threads.thread):
            studio._refresh_plans()
            threads.run_next()
            studio._refresh_plans()
            threads.run_next()
            studio.root.drain()
        self.assertEqual(studio.plan_job_id, "restored-real")
        self.assertEqual([p["id"] for p in studio._plan_history], ["restored-real"])

    def test_initial_history_prefers_real_calibrated_plan(self):
        studio = studio_fixture()
        old = plan_info("old-demo", "demo")
        real = plan_info("good-real")
        studio._apply_plan_history([old, real], ["demo", "real"])
        self.assertEqual(studio.plan_job_id, "good-real")
        self.assertEqual(studio.cmb_plans.current(), 1)

    def test_execution_keeps_captured_id_and_blocks_pending_selection(self):
        studio = studio_fixture()
        studio.plan_job_id = "chosen-real"
        studio._plan_history = [plan_info("chosen-real"), plan_info("other-real")]
        studio.client.execute.return_value = {"id": "execution"}
        studio.client.get_jobs.return_value = {"jobs": [{"id": "execution", "status": "DONE", "result": {}}]}
        threads = DeferredThreads()
        with patch("scripts.arm_studio.threading.Thread", threads.thread):
            studio._drive_arm()
            studio.cmb_plans.current(1)
            studio._on_pick_plan()
            self.assertEqual(studio.plan_job_id, "chosen-real")
            self.assertEqual(studio.cmb_plans.current(), 0)
            studio._drive_arm()  # A double click may already be queued.
            self.assertEqual(len(threads.targets), 1)
            threads.run_next()
            studio.root.drain()
        studio.client.execute.assert_called_once_with("chosen-real", port="/dev/ttyACM0")
        self.assertFalse(studio._execution_active)


class ReadRetryTests(unittest.TestCase):
    def client(self):
        client = BoardClient()
        client.token = 'test-token'
        client.opener = Mock()
        return client

    def response(self):
        response = Mock()
        response.headers = {'Content-Type': 'application/json'}
        response.read.return_value = b'{"jobs": [], "active": null}'
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        return context

    def test_get_retries_dropped_reply_but_post_never_does(self):
        for error in (http.client.RemoteDisconnected('closed'), TimeoutError('slow'),
                      http.client.IncompleteRead(b'{'), urllib.error.URLError('offline')):
            with self.subTest(error=type(error).__name__):
                client = self.client()
                client.opener.open.side_effect = [error, self.response()]
                with patch('scripts.arm_studio.time.sleep'):
                    self.assertEqual(client.get_jobs(), {'jobs': [], 'active': None})
                self.assertEqual(client.opener.open.call_count, 2)
                client = self.client()
                client.opener.open.side_effect = error
                with self.assertRaises(BoardConnectionError):
                    client._request('/api/execute', method='POST', data={'plan_job': 'existing'})
                self.assertEqual(client.opener.open.call_count, 1)

    def test_get_retries_are_bounded_and_http_errors_are_not_retried(self):
        client = self.client()
        client.opener.open.side_effect = http.client.RemoteDisconnected('closed')
        with patch('scripts.arm_studio.time.sleep'), self.assertRaises(BoardConnectionError):
            client.get_jobs()
        self.assertEqual(client.opener.open.call_count, 3)
        client = self.client()
        client.opener.open.side_effect = urllib.error.HTTPError('http://localhost/api/jobs', 500,
                                                              'error', {}, io.BytesIO(b'bad result'))
        with self.assertRaisesRegex(RuntimeError, 'HTTP 500'):
            client.get_jobs()
        self.assertEqual(client.opener.open.call_count, 1)


if __name__ == "__main__":
    unittest.main()
