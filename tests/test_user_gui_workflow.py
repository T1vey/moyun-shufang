import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

from PIL import Image
from user_gui.workflow import Workflow, validate_image, BoardPipeline, Cancelled, source_image_svg
from scripts.arm_studio import BoardConnectionError
from user_gui.display_server import Hub, DisplayServer
from scripts.run_user_gui import DesktopSupervisor, parse_args, server_command, settings_command
from scripts.user_gui_kiosk import allowed_navigation


class Pipeline:
    def __init__(self):
        self.calls = []
        self.gate = None
        self.entered = threading.Event()
        self.fail_execute = False

    def busy(self): return False
    def generate(self, raw, folder, cancelled, **cloud_options):
        self.calls.append('cloud'); self.cloud_options = cloud_options; self.entered.set()
        if self.gate: self.gate.wait(3)
        Image.new('RGB',(32,24),'white').save(folder/'line.png')
        return folder / 'line.png'
    def extract(self, *args): self.calls.append('extract'); return {'paths': []}
    def extract_local(self, *args): self.calls.append('extract_local'); return {'paths': []}
    def register(self, *args): self.calls.append('strokes'); return 'strokes-1'
    def plan(self, *args, **kw): self.calls.append('plan'); self.stored = kw.get('store'); return 'plan-1'
    def preview(self, *args):
        self.calls.append('preview')
        return b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M20 70L50 20L80 70Z" fill="none" stroke="#684325"/></svg>'
    def execute(self, *args):
        self.calls.append('execute')
        if self.fail_execute: raise OSError('response lost')
    def stop_execution(self): self.calls.append('stop')


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pipeline = Pipeline()
        self.workflow = Workflow(self.pipeline, self.tmp.name)

    def prepare(self):
        job = self.workflow.reserve('phone001', 'upload001')
        self.workflow.submit(job, b'test', {'id': 1})
        self.workflow.worker.join(3)
        self.assertFalse(self.workflow.worker.is_alive())
        self.assertEqual(self.workflow.snapshot()['phase'], 'ready')
        return self.workflow.snapshot()

    def test_prepare_never_executes_and_confirmation_is_single_use(self):
        ready = self.prepare()
        self.assertNotIn('execute', self.pipeline.calls)
        with self.assertRaises(ValueError): self.workflow.start(ready['job_id'], ready['revision']-1, True)
        with self.assertRaises(ValueError): self.workflow.start(ready['job_id'], ready['revision'], False)
        self.workflow.start(ready['job_id'], ready['revision'], True)
        self.workflow.worker.join(3)
        with self.assertRaises((ValueError, RuntimeError)): self.workflow.start(ready['job_id'], ready['revision'], True)
        self.assertEqual(self.pipeline.calls.count('execute'), 1)

    def test_portrait_displays_cloud_image_without_trajectory_preview(self):
        ready=self.prepare()
        self.assertNotIn('preview',self.pipeline.calls)
        self.assertEqual(ready['preview_kind'],'cloud_image')
        image=(self.workflow.directory/ready['job_id']/'line.png').read_bytes()
        import base64
        self.assertIn(base64.b64encode(image),self.workflow.preview(ready['job_id']))
        self.assertNotIn(b'<polyline',self.workflow.preview(ready['job_id']))
        with patch('user_gui.workflow.source_image_svg',side_effect=AssertionError('reencoded on polling')):
            self.workflow.snapshot();self.workflow.preview(ready['job_id'])

    def test_calligraphy_keeps_authored_preview(self):
        self.pipeline.register_calligraphy=Mock(return_value='brush-1')
        with patch('user_gui.workflow.source_image_svg',side_effect=AssertionError('brush has no cloud image')):
            self.workflow.submit_calligraphy('heng',40,'brush-preview')
            self.workflow.worker.join(3)
        state=self.workflow.snapshot()
        self.assertEqual(state['phase'],'ready',state)
        self.assertEqual(state['input_mode'],'calligraphy')
        self.assertEqual(self.pipeline.calls,['plan','preview'])
        self.assertIn(b'<path',self.workflow.preview(state['job_id']))
        self.assertNotIn('execute',self.pipeline.calls)

    def test_large_source_preview_is_bounded_without_changing_original(self):
        import base64,numpy as np,xml.etree.ElementTree as ET
        source=Path(self.tmp.name)/'large-cloud.png'
        pixels=np.random.default_rng(24).integers(0,256,(900,1200,3),dtype=np.uint8)
        Image.fromarray(pixels).save(source)
        original=source.read_bytes();self.assertGreater(len(original),384*1024)
        svg=ET.fromstring(source_image_svg(source))
        node=svg.find('{http://www.w3.org/2000/svg}image')
        payload=node.attrib['{http://www.w3.org/1999/xlink}href'].split(',',1)[1]
        self.assertLessEqual(len(base64.b64decode(payload)),384*1024)
        self.assertLessEqual(int(node.attrib['width']),1024)
        self.assertLessEqual(int(node.attrib['height']),600)
        self.assertEqual(source.read_bytes(),original)

    def test_source_preview_normalizes_exif_orientation_once(self):
        import base64,xml.etree.ElementTree as ET
        source=Path(self.tmp.name)/'rotated-cloud.jpg'
        image=Image.new('RGB',(12,24),'white');exif=image.getexif();exif[274]=6
        image.save(source,exif=exif)
        svg=ET.fromstring(source_image_svg(source))
        self.assertEqual(svg.attrib['viewBox'],'0 0 24 12')
        node=svg.find('{http://www.w3.org/2000/svg}image')
        raw=base64.b64decode(node.attrib['{http://www.w3.org/1999/xlink}href'].split(',',1)[1])
        with Image.open(io.BytesIO(raw)) as shown:
            self.assertEqual(shown.size,(24,12));self.assertEqual(shown.getexif().get(274,1),1)

    def test_second_phone_cannot_replace_ready_image(self):
        self.prepare()
        with self.assertRaises(RuntimeError): self.workflow.reserve('phone002', 'upload002')

    def test_same_photo_reuses_its_line_art_and_saved_plan(self):
        # 照片绘画 (2026-10-28): the second time no cloud call and no extraction; the board plan is stored.
        self.pipeline.extract = lambda *a: self.pipeline.calls.append('extract') or {'paths': [[[1, 1], [9, 9]]]}
        for n, options in enumerate(({}, {}, {'detail': 'rich'})):
            job = self.workflow.reserve('phone00%d' % n, 'upload00%d' % n)
            self.workflow.submit(job, b'same photo', {'id': 1}, cloud_options=options)
            self.workflow.worker.join(3)
            self.assertEqual(self.workflow.snapshot()['phase'], 'ready')
            self.assertTrue(self.pipeline.stored)
            self.workflow.cancel(job)
        self.assertEqual(self.pipeline.calls.count('cloud'), 2)            # first time, and other choices
        self.assertEqual(self.pipeline.calls.count('extract'), 2)
        self.assertEqual(self.pipeline.calls.count('plan'), 3)

    def test_local_lineart_skips_cloud_and_waits_for_confirmation(self):
        job = self.workflow.reserve('screen001', 'lineart001')
        stream=io.BytesIO();Image.new('RGB',(20,10),'white').save(stream,'PNG');raw=stream.getvalue()
        self.workflow.submit(job, raw, {'id': 1, 'url': '/frames/1.png'}, input_mode='lineart')
        self.workflow.worker.join(3)
        status = self.workflow.snapshot()
        self.assertEqual(status['phase'], 'ready')
        self.assertEqual(status['input_mode'], 'lineart')
        self.assertEqual(self.pipeline.calls, ['extract_local', 'strokes', 'plan'])
        self.assertEqual(status['preview_kind'],'source_image')
        self.assertNotIn('cloud_s', status['timing'])
        self.assertIn('extraction_s', status['timing'])
        self.assertEqual((self.workflow.directory/job/'input').read_bytes(), raw)
        with self.assertRaises(ValueError):
            self.workflow.start(job, status['revision'], False)
        self.assertNotIn('execute', self.pipeline.calls)

    def test_bad_local_lineart_does_not_fall_back_to_cloud(self):
        self.pipeline.extract_local = Mock(side_effect=ValueError('没有可提取的线条'))
        job = self.workflow.reserve('screen001')
        self.workflow.submit(job, b'blank', {'id': 1}, input_mode='lineart')
        self.workflow.worker.join(3)
        self.assertEqual(self.workflow.snapshot()['phase'], 'error')
        self.assertFalse(self.workflow.snapshot()['can_start'])
        self.assertEqual(self.pipeline.calls, [])

    def test_quality_warning_finishes_ui_without_claiming_verified_return(self):
        ready=self.prepare()
        self.pipeline.execute=Mock(return_value={'quality_warning':True})
        self.workflow.start(ready['job_id'],ready['revision'],True)
        self.workflow.worker.join(3)
        status=self.workflow.snapshot()
        self.assertEqual(status['phase'],'completed')
        self.assertIn('质量提示',status['message'])
        self.assertNotIn('已返回起始位置',status['message'])

    def test_cancel_cloud_does_not_submit_strokes_or_motion(self):
        self.pipeline.gate = threading.Event()
        job = self.workflow.reserve('phone001')
        self.workflow.submit(job, b'test', {'id': 1})
        self.assertTrue(self.pipeline.entered.wait(1))
        self.workflow.cancel(job)
        with self.assertRaises(RuntimeError): self.workflow.reserve('phone002')
        self.pipeline.gate.set(); self.workflow.worker.join(3)
        self.assertEqual(self.pipeline.calls, ['cloud'])
        self.assertEqual(self.workflow.snapshot()['phase'], 'cancelled')

    def test_settings_and_upload_exclude_each_other(self):
        self.workflow.set_view('settings')
        with self.assertRaises(RuntimeError): self.workflow.reserve('phone001')
        self.workflow.set_view('user')
        self.workflow.reserve('phone001')
        with self.assertRaises(RuntimeError): self.workflow.set_view('settings')

    def test_phone_only_reads_its_own_job(self):
        ready = self.prepare()
        status = self.workflow.status_for('phone001', ready['job_id'])
        self.assertNotIn('revision', status); self.assertNotIn('preview_url', status)
        with self.assertRaises(ValueError): self.workflow.status_for('phone002', ready['job_id'])

    def test_restart_never_restores_execution_authority(self):
        ready = self.prepare()
        new = Workflow(self.pipeline, self.tmp.name)
        self.assertEqual(new.snapshot()['phase'], 'idle')
        with self.assertRaises(ValueError): new.start(ready['job_id'], ready['revision'], True)

    def test_lost_execute_response_keeps_stop_without_replay(self):
        ready = self.prepare(); self.pipeline.fail_execute = True
        self.workflow.start(ready['job_id'], ready['revision'], True)
        self.workflow.worker.join(3)
        self.assertTrue(self.workflow.snapshot()['can_cancel'])
        self.workflow.cancel(ready['job_id'])
        self.assertEqual(self.pipeline.calls.count('execute'), 1)
        self.assertIn('stop', self.pipeline.calls)

    def test_close_after_uncertain_execution_requests_stop(self):
        ready = self.prepare(); self.pipeline.fail_execute = True
        self.workflow.start(ready['job_id'], ready['revision'], True)
        self.workflow.worker.join(3)
        self.workflow.close()
        self.assertIn('stop', self.pipeline.calls)
        self.assertEqual(self.pipeline.calls.count('execute'), 1)

    def test_abandoned_next_upload_releases_its_reservation(self):
        ready = self.prepare()
        self.workflow.cancel(ready['job_id'])
        job = self.workflow.reserve('phone002', 'next-upload')
        self.workflow.abandon(job)
        self.assertEqual(self.workflow.snapshot()['phase'], 'error')
        self.workflow.reserve('phone003', 'retry-upload')

    def test_image_decode_rejects_truncated_and_mismatched_content(self):
        stream = io.BytesIO(); Image.new('RGB', (16, 16), 'white').save(stream, 'PNG')
        self.assertEqual(validate_image(stream.getvalue(), 'image/png'), {'w': 16, 'h': 16})
        for raw, kind in [(stream.getvalue()[:40], 'image/png'), (stream.getvalue(), 'image/jpeg')]:
            with self.assertRaises(ValueError): validate_image(raw, kind)

    def test_backend_cannot_be_repointed_to_external_host(self):
        with self.assertRaises(ValueError): BoardPipeline('https://example.com:443', self.tmp.name)


class BoardPollingTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = BoardPipeline.__new__(BoardPipeline)
        self.pipeline.client = Mock()
        self.pipeline.poll_s = .35
        self.pipeline.timeline = None
        self.pipeline.port = '/dev/ttyACM0'
        self.pipeline.baudrate = 1000000
        self.now = 0.
        monotonic = patch('user_gui.workflow.time.monotonic', side_effect=lambda: self.now)
        sleep = patch('user_gui.workflow.time.sleep', side_effect=self.advance)
        monotonic.start(); sleep.start()
        self.addCleanup(monotonic.stop); self.addCleanup(sleep.stop)

    def advance(self, seconds):
        self.now += seconds

    def test_local_extraction_preserves_aspect_and_uses_faithful_strokes(self):
        self.pipeline.client.fetch_status.return_value = {'sugar_calibration_ready': True}
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory)/'wide.png'
            Image.new('RGB', (200, 100), 'white').save(image)
            with patch('vision.convert', return_value={'paths': []}) as convert, patch('cloud.generate') as cloud:
                self.pipeline.extract_local(image, Path(directory), lambda: False)
                args = convert.call_args
                self.assertEqual(args.args[3:5], (100., 50.))
                self.assertEqual(args.kwargs['stroke_profile'], 'faithful')
                cloud.assert_not_called()

    def test_tcb_execute_sends_confirmation_and_accepts_joint_done(self):
        self.pipeline.robot_type = 'TCB705'; self.pipeline.simulation = False
        self.pipeline.check_plan = Mock()
        self.pipeline.client._request.return_value = {'id': 'execute-1'}
        result = {'status': 'DONE', 'result': {'robot_type': 'TCB705', 'status': 'DONE', 'physical_motion': True}}
        self.pipeline._wait = Mock(return_value=result)
        self.assertIs(self.pipeline.execute('plan-1', lambda: False), result)
        self.pipeline.client._request.assert_called_once_with('/api/execute', method='POST',
            data={'plan_job': 'plan-1', 'mode': 'real', 'confirm_physical': True}, timeout=60)
        self.pipeline.client.execute.assert_not_called()
        result['result']['restore_deferred'] = True
        with self.assertRaisesRegex(ValueError, '不允许切回手动'):
            self.pipeline.execute('plan-1', lambda: False)

    def test_deferred_restore_reports_last_restore_reason_without_retrying(self):
        self.pipeline.robot_type='TCB705';self.pipeline.simulation=False
        self.pipeline.check_plan=Mock()
        self.pipeline.client._request.return_value={'id':'execute-1'}
        self.pipeline._wait=Mock(return_value={'status':'DONE','motion_stage':'RETURN_HOME_DONE','result':{
            'robot_type':'TCB705','status':'DONE','restore_deferred':True,'log':[
                {'event':'RESTORE','steps':[['restore_deferred',False,'old reason']]},
                {'event':'RESTORE','steps':[['restore_deferred',False,'归位后静止确认超时']]},
                {'event':'POST_RESTORE','error':'summary only'}]}})
        with self.assertRaises(ValueError) as raised:
            self.pipeline.execute('plan-1',lambda:False)
        self.assertIn('归位后静止确认超时',str(raised.exception))
        self.assertIn('后续动作未启动',str(raised.exception))
        self.assertNotIn('old reason',str(raised.exception))
        self.pipeline.client._request.assert_called_once()
        self.pipeline.client.execute.assert_not_called()

    def test_deferred_restore_without_valid_diagnostics_still_blocks(self):
        self.pipeline.robot_type='TCB705';self.pipeline.simulation=False
        self.pipeline.check_plan=Mock()
        self.pipeline.client._request.return_value={'id':'execute-1'}
        for log in (None,{},[None,{'event':'RESTORE','steps':[None,[],['restore',True,'ok']]}]):
            with self.subTest(log=log):
                self.pipeline._wait=Mock(return_value={'result':{'robot_type':'TCB705','status':'DONE',
                    'restore_deferred':True,'log':log}})
                with self.assertRaisesRegex(ValueError,'高度或位置反馈尚未满足安全条件'):
                    self.pipeline.execute('plan-1',lambda:False)

    def test_quality_warning_does_not_turn_finished_execution_into_failure(self):
        self.pipeline.check_plan=Mock()
        self.pipeline.client.execute.return_value={'id':'execute-1'}
        result={'status':'DONE','quality_warning':True,'result':{
            'quality_guard_policy':'warn_continue','execution_finished':True,'task_complete':False,
            'auto_home':{'execution_finished':True,'task_complete':False}}}
        self.pipeline._wait=Mock(return_value=result)
        self.assertIs(self.pipeline.execute('plan-1',lambda:False),result)
        self.pipeline.client.execute.assert_called_once()
        result['result']['auto_home_error']='communication lost'
        with self.assertRaises(ValueError):self.pipeline.execute('plan-1',lambda:False)

    def snapshot(self, status='RUNNING', active='plan-1'):
        return {'active': active, 'jobs': [{'id': 'plan-1', 'status': status,
                'result': {'status': 'OK', 'metrics': {'memory_ready': True}}}]}

    def test_calibration_gate_precedes_cloud_and_ready_keeps_existing_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.pipeline.data_dir = folder
            self.pipeline.secrets_file = None
            self.pipeline.profile = 'seedream'
            saved_image = folder/'saved.png'
            with patch('cloud.profile_path', return_value=folder/'profile.json'), \
                    patch('cloud.load_config', return_value={'model':'test-model'}) as config, \
                    patch('cloud.generate', return_value=(b'generated-image', {'elapsed_s':1.})) as generate, \
                    patch('cloud_gallery.CloudImageLibrary') as library:
                library.return_value.save.return_value = {'path':saved_image}
                self.pipeline.client.fetch_status.return_value = {'sugar_calibration_ready':False}
                with self.assertRaisesRegex(ValueError, '尚未完成实测标定'):
                    self.pipeline.generate(b'phone-image', folder, lambda:False)
                generate.assert_not_called()
                config.assert_not_called()
                library.assert_not_called()
                self.pipeline.client.fetch_status.return_value = {'sugar_calibration_ready':True}
                result = self.pipeline.generate(b'phone-image', folder, lambda:False)
                self.assertEqual(result, saved_image)
                generate.assert_called_once_with(b'phone-image',
                    {'model':'test-model','client_max_edge':1024}, 'portrait', custom='', detail='simple')
                library.return_value.save.assert_called_once_with(b'generated-image',
                    profile='seedream', model='test-model', subject='portrait', source_name='手机上传')
                self.assertEqual(json.loads((folder/'cloud_timing.json').read_text(encoding='utf-8')),
                                 {'elapsed_s':1.})

    def test_plan_reconnects_to_same_job_and_waits_for_publication(self):
        self.pipeline.client.plan.return_value = {'id': 'plan-1'}
        self.pipeline.check_plan = Mock()
        self.pipeline.client.get_jobs.side_effect = [
            self.snapshot(), BoardConnectionError('reply lost'),
            self.snapshot('DONE'), self.snapshot('DONE', active=None)]
        self.assertEqual(self.pipeline.plan('image-1', lambda: False), 'plan-1')
        self.pipeline.client.plan.assert_called_once()
        self.assertEqual(self.pipeline.client.get_jobs.call_count, 4)
        self.pipeline.check_plan.assert_called_once_with('plan-1')
        self.pipeline.client.execute.assert_not_called()
        self.pipeline.client.stop.assert_not_called()

    def test_successful_snapshot_resets_continuous_disconnect_window(self):
        events = iter(['offline', 'online', 'offline', 'done'])
        def get_jobs():
            event = next(events)
            if event == 'offline':
                self.advance(20.)
                raise BoardConnectionError('reply lost')
            return self.snapshot('DONE', active=None) if event == 'done' else self.snapshot()
        self.pipeline.client.get_jobs.side_effect = get_jobs
        self.assertEqual(self.pipeline._wait('plan-1', lambda: False)['status'], 'DONE')
        self.assertGreater(self.now, 40.)

    def test_continuous_disconnect_is_bounded_without_another_write(self):
        def offline():
            self.advance(8.)
            raise BoardConnectionError('reply lost')
        self.pipeline.client.get_jobs.side_effect = offline
        with self.assertRaisesRegex(BoardConnectionError, '状态连接持续中断'):
            self.pipeline._wait('plan-1', lambda: False)
        self.assertEqual(self.pipeline.client.get_jobs.call_count, 4)
        self.assertLess(self.now, 40.)
        self.pipeline.client.plan.assert_not_called()
        self.pipeline.client.execute.assert_not_called()

    def test_missing_job_after_restart_fails_after_three_snapshots(self):
        self.pipeline.client.get_jobs.return_value = {'active': None, 'jobs': []}
        with self.assertRaisesRegex(ValueError, '找不到原任务'):
            self.pipeline._wait('plan-1', lambda: False)
        self.assertEqual(self.pipeline.client.get_jobs.call_count, 3)
        self.pipeline.client.plan.assert_not_called()
        self.pipeline.client.execute.assert_not_called()

    def test_failed_job_and_http_error_are_not_hidden_by_reconnect(self):
        failed = self.snapshot('FAILED', active=None)
        failed['jobs'][0]['detail'] = 'vertical axis unreachable'
        self.pipeline.client.get_jobs.return_value = failed
        with self.assertRaisesRegex(ValueError, 'vertical axis unreachable'):
            self.pipeline._wait('plan-1', lambda: False)
        self.pipeline.client.get_jobs.assert_called_once()
        self.pipeline.client.get_jobs.reset_mock()
        self.pipeline.client.get_jobs.side_effect = RuntimeError('HTTP 403')
        with self.assertRaisesRegex(RuntimeError, 'HTTP 403'):
            self.pipeline._wait('plan-1', lambda: False)
        self.pipeline.client.get_jobs.assert_called_once()

    def test_cancellation_after_reconnect_stops_only_owned_active_job(self):
        self.pipeline.client.get_jobs.side_effect = [BoardConnectionError('reply lost'), self.snapshot()]
        with self.assertRaises(Cancelled):
            self.pipeline._wait('plan-1', lambda: True)
        self.pipeline.client.stop.assert_called_once_with()
        self.pipeline.client.stop.reset_mock()
        self.pipeline.client.get_jobs.side_effect = None
        self.pipeline.client.get_jobs.return_value = self.snapshot(active='settings-2')
        with self.assertRaises(Cancelled):
            self.pipeline._wait('plan-1', lambda: True)
        self.pipeline.client.stop.assert_not_called()


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.pipeline = Pipeline(); self.workflow = Workflow(self.pipeline, self.tmp.name)
        hub = Hub(Path(self.tmp.name)/'uploads', token='phone-token')
        self.server = DisplayServer(('127.0.0.1', 0), hub, workflow=self.workflow, interfaces=[])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.close)
        self.base = 'http://127.0.0.1:%d' % self.server.server_port

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def req(self, path, data=None, headers=None):
        headers = dict(headers or {})
        if isinstance(data, dict): data = json.dumps(data).encode(); headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.base+path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=3) as r: return r.status, r.read()
        except urllib.error.HTTPError as e: return e.code, e.read()

    def test_control_needs_screen_token_and_same_origin(self):
        code, raw = self.req('/api/state'); self.assertEqual(code, 200)
        token = json.loads(raw)['control_token']
        self.assertEqual(self.req('/api/settings/open', {})[0], 403)
        self.assertEqual(self.req('/api/settings/open', {}, {'X-Screen-Token': token, 'Origin':'http://evil.invalid'})[0], 403)
        self.assertEqual(self.req('/api/state', headers={'Host':'evil.invalid'})[0], 403)
        self.assertEqual(self.req('/api/settings/open', {}, {'X-Screen-Token': token})[0], 200)
        self.assertEqual(json.loads(self.req('/api/view')[1])['view'], 'settings')

    def test_upload_runs_pipeline_but_not_motion(self):
        buf=io.BytesIO(); Image.new('RGB',(24,24),'white').save(buf,'PNG')
        path='/api/upload?t=phone-token&cid=phone001&rid=upload001'
        code,raw=self.req(path,buf.getvalue(),{'Content-Type':'image/png'})
        self.assertEqual(code,200,raw)
        jid=json.loads(raw)['job_id'];self.workflow.worker.join(3)
        self.assertEqual(self.workflow.snapshot()['phase'],'ready')
        self.assertNotIn('execute',self.pipeline.calls)
        self.assertEqual(self.req('/api/workflow/preview?job_id='+jid)[0],200)
        self.assertEqual(self.req(path,buf.getvalue(),{'Content-Type':'image/png'})[0],409)
        self.assertEqual(self.req('/api/upload-status?t=phone-token&cid=other001&job_id='+jid)[0],404)

    def test_phone_subject_and_own_prompt_reach_cloud(self):
        # 2026-10-18: the phone chooses portrait / object / landscape, or types its own description
        from urllib.parse import quote
        buf=io.BytesIO(); Image.new('RGB',(24,24),'white').save(buf,'PNG')
        path='/api/upload?t=phone-token&cid=phone001&rid=upload101&subject=landscape'
        code,raw=self.req(path,buf.getvalue(),{'Content-Type':'image/png'}); self.assertEqual(code,200,raw)
        self.workflow.worker.join(3); self.assertEqual(self.pipeline.cloud_options,{'subject':'landscape','custom':'','detail':'simple'})
        jid=json.loads(raw)['job_id']; self.workflow.cancel(jid); self.workflow.reset(jid)
        path='/api/upload?t=phone-token&cid=phone001&rid=upload102&subject=custom&detail=detail&prompt='+quote('一只  坐着的猫\n和月亮')
        code,raw=self.req(path,buf.getvalue(),{'Content-Type':'image/png'}); self.assertEqual(code,200,raw)
        self.workflow.worker.join(3); self.assertEqual(self.pipeline.cloud_options,{'subject':'custom','custom':'一只 坐着的猫 和月亮','detail':'detail'})

    def test_bad_subject_or_empty_own_prompt_refused_before_upload(self):
        buf=io.BytesIO(); Image.new('RGB',(24,24),'white').save(buf,'PNG')
        for i,q in enumerate(('subject=people','subject=custom&prompt=%20%20','subject=object&detail=fancy')):
            code,raw=self.req('/api/upload?t=phone-token&cid=phone001&rid=upload20%d&'%i+q,buf.getvalue(),{'Content-Type':'image/png'})
            self.assertNotEqual(code,200,raw)
        self.assertNotIn('cloud',self.pipeline.calls)

    def test_local_upload_requires_screen_authority_and_skips_cloud(self):
        token = json.loads(self.req('/api/state')[1])['control_token']
        buf = io.BytesIO(); Image.new('RGB', (24, 24), 'white').save(buf, 'PNG')
        path = '/api/local-lineart?cid=screen001&rid=lineart001'
        headers = {'Content-Type': 'image/png', 'X-Screen-Token': token}
        self.assertEqual(self.req(path, buf.getvalue(), {'Content-Type': 'image/png'})[0], 403)
        self.assertEqual(self.req(path, buf.getvalue(), dict(headers, Origin='http://evil.invalid'))[0], 403)
        self.assertEqual(self.req(path, b'not an image', headers)[0], 400)
        code, raw = self.req(path+'&unused=1', buf.getvalue(), headers)
        self.assertEqual(code, 409)  # Same request ID cannot silently replay a failed upload.
        code, raw = self.req('/api/local-lineart?cid=screen001&rid=lineart002', buf.getvalue(), headers)
        self.assertEqual(code, 200, raw)
        self.workflow.worker.join(3)
        self.assertEqual(self.workflow.snapshot()['phase'], 'ready')
        self.assertNotIn('cloud', self.pipeline.calls)
        self.assertNotIn('execute', self.pipeline.calls)
        self.assertIn('extract_local', self.pipeline.calls)


class DesktopTests(unittest.TestCase):
    def test_launch_commands_keep_backend_and_ui_separate(self):
        args=parse_args(['--port','8765','--web-port','8090'])
        self.assertIn('--workflow',server_command(args))
        self.assertIn('--return-user-gui',settings_command(args))
        self.assertIn('--windowed',settings_command(args))
        self.assertTrue(allowed_navigation('http://127.0.0.1:8090/?kiosk=1',8090))
        self.assertFalse(allowed_navigation('https://example.com/',8090))
        self.assertFalse(allowed_navigation('http://127.0.0.1:8765/',8090))


if __name__ == '__main__': unittest.main()


class CloudPromptTests(unittest.TestCase):
    def test_general_part_always_first_and_custom_is_bounded(self):
        import cloud
        for subject in ('portrait', 'object', 'landscape'):
            self.assertTrue(cloud.build_prompt(subject).startswith(cloud.PROMPT))
        self.assertIn('不出现人物', cloud.build_prompt('landscape'))
        own = cloud.build_prompt('custom', '画一只猫\x00' + '长' * 500)
        self.assertTrue(own.startswith(cloud.PROMPT)); self.assertNotIn('\x00', own)
        self.assertIn('以线条要求为准', own)
        self.assertEqual(len(cloud.clean_custom('长' * 500)), cloud.CUSTOM_MAX_CHARS)
        for mode in ('simple', 'detail'):
            for subject in ('portrait', 'object', 'landscape'):
                self.assertTrue(cloud.build_prompt(subject, '', mode).startswith(cloud.GENERAL_PROMPTS[mode]))
        self.assertIn('15～25', cloud.build_prompt('object')); self.assertIn('60', cloud.build_prompt('object', '', 'detail'))
        # 人物: 简略 keeps the minimal allocation, 细节 swaps in the detailed portrait text
        self.assertIn(cloud.SUBJECT_PROMPTS['portrait'], cloud.build_prompt('portrait'))
        self.assertIn(cloud.SUBJECT_PROMPTS_DETAIL['portrait'], cloud.build_prompt('portrait', '', 'detail'))
        self.assertNotIn(cloud.SUBJECT_PROMPTS['portrait'], cloud.build_prompt('portrait', '', 'detail'))
        self.assertIn(cloud.SUBJECT_PROMPTS['landscape'], cloud.build_prompt('landscape', '', 'detail'))
        for bad in (('people', ''), ('custom', '   '), ('object', '', 'fancy')):
            with self.assertRaises(ValueError):
                cloud.build_prompt(*bad)

    def test_provider_error_code_is_shown_but_not_its_message(self):
        import cloud, urllib.error
        from unittest.mock import patch
        body = io.BytesIO(json.dumps({'error': {'code': 'InputImageSensitiveContentDetected',
                                                'message': 'secret account 123 detail'}}).encode())
        err = urllib.error.HTTPError('https://example.invalid', 400, 'Bad Request', {}, body)
        with patch('urllib.request.OpenerDirector.open', side_effect=err):
            with self.assertRaises(ValueError) as ctx:
                cloud.fetch(urllib.request.Request('https://example.invalid'), 5, 1000)
        self.assertIn('InputImageSensitiveContentDetected', str(ctx.exception))
        self.assertIn('换一张照片', str(ctx.exception)); self.assertNotIn('account', str(ctx.exception))
        self.assertEqual(cloud.error_message(400, None), cloud.error_message(400, 'not a <code>'))
