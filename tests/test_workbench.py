import copy
import hashlib
import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import State, Server, validate_scan
from protocol import DemoPort, exchange, probe, request, ProbeError
from motion import Executor, counts_from_angles, validate_machine, read_all
from workbench import Workbench


def machine():
    data = json.loads((ROOT/'config/machine.example.json').read_text(encoding='utf-8'))
    for j in data['joints']:
        j.update(zero_count=2048, min_count=100, max_count=3900)
    data['checks'] = dict(limits=True, kinematics=True, single_joint=True)
    return data


class ResponsePort(DemoPort):
    def __init__(self, response, short=False):
        super().__init__()
        self.response, self.short = response, short

    def write(self, packet):
        self.writes.append(packet)
        self.buffer.extend(self.response)
        return len(packet)-1 if self.short else len(packet)


def status(sid=1, params=(), error=0):
    body = [sid,len(params)+2,error]+list(params)
    return b'\xff\xff'+bytes(body+[(~sum(body))&255])


class ProtocolTests(unittest.TestCase):
    def test_exact_ping_and_read(self):
        self.assertEqual(request(1,'ping'), bytes.fromhex('ff ff 01 02 01 fb'))
        self.assertEqual(request(1,'position'), bytes.fromhex('ff ff 01 04 02 38 02 be'))

    def test_no_broadcast_or_arbitrary_register(self):
        for sid in (True,0,254,-1):
            with self.assertRaises(ValueError): request(sid,'ping')
        with self.assertRaises(ValueError): request(1,'write')

    def test_fragmented_and_signed(self):
        r = exchange(ResponsePort(status(params=[7,128])),1,'position')
        self.assertEqual(r,dict(raw_word=32775,position_count=-7))

    def test_malformed_responses(self):
        cases=[(b'xy'+status()[2:],'HEADER'),(status(sid=2),'ID_MISMATCH'),
               (status(params=[1]),'LENGTH'),(status()[:-1]+b'\0','CHECKSUM'),(status(error=4),'SERVO_ERROR'),(b'','TIMEOUT')]
        for response, code in cases:
            with self.subTest(code=code), self.assertRaises(ProbeError) as c:
                exchange(ResponsePort(response),1,'ping',.005)
            self.assertEqual(c.exception.code,code)

    def test_partial_write(self):
        with self.assertRaises(ProbeError) as c:
            exchange(ResponsePort(status(),True),1,'ping')
        self.assertEqual(c.exception.code,'SHORT_WRITE')

    def test_status_10_retains_checked_encoder_data(self):
        r=exchange(ResponsePort(status(params=[135,12,0,0],error=0x10)),1,'position_speed')
        self.assertEqual(r['position_count'],3207)
        self.assertEqual(r['status_byte'],0x10)
        self.assertEqual(r['speed_raw'],0)

    def test_one_status_flag_does_not_discard_other_four_joint_samples(self):
        from types import SimpleNamespace
        import time
        from smooth_motion import SerialMotionScheduler
        class FlagPort(DemoPort):
            def write(self,packet):
                result=super().write(packet)
                if packet[2]==4 and self.buffer:
                    self.buffer[4]=0x10
                    self.buffer[-1]=(~sum(self.buffer[2:-1]))&255
                return result
        port=FlagPort();events=[]
        scheduler=SerialMotionScheduler.__new__(SerialMotionScheduler)
        scheduler.machine=dict(joints=[dict(id=i,min_count=0,max_count=4095) for i in range(1,6)])
        scheduler.port=port;scheduler.executor=SimpleNamespace(cancelled=lambda:False)
        scheduler.timing=dict(feedback_failures=0,max_feedback_s=0)
        scheduler.measured=0;scheduler.audit=lambda *row:events.append(row)
        self.assertTrue(scheduler._read_positions(time.monotonic()+.2))
        self.assertEqual(scheduler.feedback,{i:port.positions[i] for i in range(1,6)})
        self.assertEqual(scheduler.timing['feedback_failures'],0)
        self.assertTrue(any(name=='SERVO_STATUS_FLAG' and data['id']==4 for name,data in events))

    def test_status_10_does_not_hide_fault_bits_or_bad_checksum(self):
        for flag in (0x11,0x12,0x14,0x18,0x30,0x40):
            with self.subTest(flag=flag),self.assertRaises(ProbeError):
                exchange(ResponsePort(status(params=[135,12,0,0],error=flag)),1,'position_speed')
        packet=status(params=[135,12,0,0],error=0x10)
        with self.assertRaisesRegex(ProbeError,'checksum'):
            exchange(ResponsePort(packet[:-1]+bytes([packet[-1]^1])),1,'position_speed')

    def test_no_default_feedback_on_failure(self):
        rows=probe(DemoPort('missing'),[1,3],.005)
        self.assertTrue(rows[0]['read_ok'])
        self.assertIsNone(rows[1]['position_count'])
        self.assertIsNone(rows[1]['raw_word'])

    def test_read_probe_has_no_write_instruction(self):
        port=DemoPort()
        probe(port,[1,2,3,4,5,6])
        self.assertEqual(len(port.writes),12)
        self.assertEqual({p[4] for p in port.writes},{1,2})


class MotionTests(unittest.TestCase):
    def test_joint_read_errors_keep_operation_id_protocol_code_and_cause(self):
        for operation in ('ping', 'model', 'mode', 'torque', 'position'):
            for code in ('TIMEOUT', 'CHECKSUM', 'SERVO_ERROR'):
                with self.subTest(operation=operation, code=code):
                    port = DemoPort()
                    original = ProbeError(code, 'original wire failure')
                    def failing(device, sid, op):
                        if sid == 3 and op == operation:
                            raise original
                        return exchange(device, sid, op)
                    with patch('motion.exchange', side_effect=failing), self.assertRaises(ProbeError) as caught:
                        read_all(port, machine(), preflight=True, need_torque=True)
                    self.assertEqual(caught.exception.code, code)
                    self.assertIs(caught.exception.__cause__, original)
                    self.assertIn('舵机 ID 3', str(caught.exception))
                    self.assertIn('（'+operation+'）', str(caught.exception))
                    self.assertIn('original wire failure', str(caught.exception))
                    self.assertTrue(all(packet[4] in (1, 2) for packet in port.writes))

    def test_configuration_and_count_limits(self):
        with self.assertRaises(ValueError): validate_machine(json.loads((ROOT/'config/machine.example.json').read_text(encoding='utf-8')))
        m=machine()
        self.assertEqual(counts_from_angles(m,[0]*5),{i:2048 for i in range(1,6)})
        with self.assertRaises(ValueError): counts_from_angles(m,[4]*5)
        m['checks']['single_joint']=False
        with self.assertRaises(ValueError): validate_machine(m,True)

    def test_enable_primes_position_before_torque(self):
        p=DemoPort()
        p.torques={i:0 for i in range(1,254)}
        Executor(p,machine()).enable()
        writes=[b for b in p.writes if b[4]==0x83]
        self.assertEqual([b[5] for b in writes],[42,40])
        self.assertEqual([writes[1][k] for k in range(7,len(writes[1])-1,2)],[1,2,3,4,5])

    def test_jog_counts_and_end_feedback(self):
        p=DemoPort()
        initial=p.positions.copy()
        result=Executor(p,machine()).jog(2,10)
        self.assertEqual(result['frames'],20)
        self.assertEqual(p.positions[2],initial[2]+10)
        self.assertEqual(p.positions[6],initial[6])

    def test_jog_outside_limit_emits_no_targets(self):
        p=DemoPort(); m=machine();m['joints'][0]['max_count']=p.positions[1]+5
        with self.assertRaises(ValueError): Executor(p,m).jog(1,10)
        self.assertFalse(any(b[4]==0x83 for b in p.writes))

    def test_torque_off_prevents_jog(self):
        p=DemoPort();p.torques[2]=0
        with self.assertRaises(ValueError): Executor(p,machine()).jog(1,10)
        self.assertFalse(any(b[4]==0x83 for b in p.writes))

    def test_stop_holds_current_pose(self):
        p=DemoPort();before=p.positions.copy()
        with self.assertRaisesRegex(RuntimeError,'STOPPED'):
            Executor(p,machine(),lambda:True).jog(1,10)
        self.assertEqual(before,p.positions)
        self.assertTrue(any(b[4]==0x83 for b in p.writes))

    def test_excessive_speed_rejected_before_write(self):
        p=DemoPort(); m=machine(); m['execution']={'guard_policy':'strict'}; ex=Executor(p,m)
        current={i:p.positions[i] for i in range(1,6)}
        with self.assertRaises(ValueError): ex.run_frames([(.01,{i:c+100 for i,c in current.items()})],current)
        self.assertEqual(p.writes,[])

    def test_changed_start_pose_rejects_execution(self):
        p=DemoPort()
        result=SimpleNamespace(status='OK',commands=[dict(t_s=.1,q_rad=[0]*5)])
        with self.assertRaisesRegex(ValueError,'起始姿态'):
            Executor(p,machine()).execute(result,[0]*5)
        self.assertFalse(any(b[4]==0x83 for b in p.writes))

    def test_following_error_stops_and_holds(self):
        p=DemoPort();current={i:2048 for i in range(1,6)}
        m=machine(); m['execution']={'guard_policy':'strict'}
        p.positions[1]=2300
        with self.assertRaisesRegex(RuntimeError,'跟随误差'):
            Executor(p,m).run_frames([(.01,current)],current)
        self.assertEqual(p.positions[1],2300)

    def test_wrong_mode_rejects_motion(self):
        p=DemoPort()
        real_exchange=exchange
        def altered(port,sid,op,*args):
            return 1 if op=='mode' else real_exchange(port,sid,op,*args)
        with patch('motion.exchange',altered), self.assertRaisesRegex(ValueError,'位置模式'):
            Executor(p,machine()).jog(1,10)
        self.assertFalse(any(b[4]==0x83 for b in p.writes))

    def test_slow_feedback_does_not_send_stale_frame(self):
        p=DemoPort();current={i:p.positions[i] for i in range(1,6)}
        m=machine(); m['execution']={'guard_policy':'strict'}
        from motion import read_all
        def slow(*args, **kwargs):
            time.sleep(.21)
            return read_all(*args, **kwargs)
        with patch('motion.read_all',slow), self.assertRaisesRegex(RuntimeError,'反馈耗时'):
            Executor(p,m).run_frames([(.01,current)],current)
        # Only recovery hold is written; no scheduled target escapes.
        self.assertEqual(len([b for b in p.writes if b[4]==0x83]),1)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.opened=[]
        def factory(*args):
            self.opened.append(args)
            return DemoPort()
        self.state=State(self.tmp.name,False,factory)
        self.server=Server(('127.0.0.1',0),self.state)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.workbench.stop()
        if self.server.workbench.worker:self.server.workbench.worker.join(10)
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.tmp.cleanup()

    def http(self,path,body=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        h={'Content-Type':'application/json','X-Console-Token':self.state.token}
        h.update(headers or {})
        c.request('GET' if body is None else 'POST',path,body=None if body is None else json.dumps(body),headers=h)
        r=c.getresponse();status_code=r.status;data=r.read();c.close();return status_code,data

    def test_real_requires_two_switches(self):
        data=dict(mode='real',port='COM99',baudrate=1000000,ids=[1],confirmed=True)
        self.assertEqual(self.http('/api/probe',data)[0],400)
        data['confirmed']=False
        with self.assertRaises(ValueError): validate_scan(data,True)
        self.assertEqual(self.opened,[])

    def test_invalid_id_and_port(self):
        for ids in ([1,1],[True],[254],[]):
            with self.assertRaises(ValueError):validate_scan(dict(mode='demo',ids=ids),False)
        with self.assertRaises(ValueError):validate_scan(dict(mode='real',ids=[1],confirmed=True,port='socket://remote',baudrate=1000000),True)

    def test_host_origin_token(self):
        self.assertEqual(self.http('/api/status',headers={'Host':'evil.test'})[0],403)
        self.assertEqual(self.http('/api/status',headers={'Origin':'http://evil.test'})[0],403)
        self.assertEqual(self.http('/api/probe',{}, {'X-Console-Token':'bad'})[0],403)

    def test_paths_and_static_files(self):
        self.assertEqual(self.http('/../app.py')[0],404)
        # home is an asynchronous supported action; unknown actions stay 404.
        self.assertEqual(self.http('/api/unknown',{})[0],404)
        self.assertEqual(self.http('/api/home',{})[0],202)
        self.assertEqual(self.http('/')[0],200)
        self.assertEqual(self.http('/sample.png')[0],200)

    def test_simulation_export_manifest(self):
        code,raw=self.http('/api/probe',dict(mode='demo',ids=[1,2]))
        self.assertEqual(json.loads(raw)['status'],'DEMO_PASS')
        code,data=self.http('/api/export',{})
        self.assertEqual(code,200)
        self.assertNotIn(self.state.token.encode(),data)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            manifest=json.loads(z.read('SHA256.json'))
            for name,digest in manifest.items():
                self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(),digest)
                self.assertNotIn(self.state.token.encode(),z.read(name))

    def test_invalid_real_motion_never_opens_port(self):
        w=self.server.workbench
        j=w.start('jog',dict(mode='real',id=1,delta=10,confirmed=True,port='COM99',baudrate=1000000))
        w.worker.join(5)
        self.assertEqual(w.jobs[j['id']]['status'],'FAILED')
        self.assertEqual(self.opened,[])

    def test_disconnected_id3_stops_before_planning_and_cleans_up_readonly_job(self):
        workbench = self.server.workbench
        source = self.state.directory/'job_source'
        source.mkdir()
        (source/'paths.json').write_text(json.dumps({'paths': [[[0, 0], [1, 1]]]}))
        workbench.jobs['source'] = dict(kind='strokes', status='DONE')
        port = DemoPort('missing')
        initial_positions, initial_torques = port.positions.copy(), port.torques.copy()
        port.close = lambda: setattr(port, 'closed', True)
        with patch.object(workbench, 'connect', return_value=(port, machine())), patch('planning.build') as build:
            job = workbench.start('plan', dict(mode='real', image_job='source'))
            workbench.worker.join(5)
        job = workbench.jobs[job['id']]
        build.assert_not_called()
        self.assertFalse(workbench.worker.is_alive())
        self.assertEqual(job['status'], 'FAILED')
        self.assertIn('规划前舵机读取失败，尚未开始轨迹计算', job['detail'])
        self.assertIn('舵机 ID 3 通信探测（ping）失败 [TIMEOUT]', job['detail'])
        self.assertIn('Response deadline expired', job['detail'])
        self.assertTrue(port.closed)
        self.assertIsNone(workbench.active)
        self.assertFalse(self.state.lock.locked())
        self.assertNotIn(job['id'], workbench.plans)
        self.assertFalse(workbench._plan_path(job['id']).exists())
        folder = self.state.directory/('job_'+job['id'])
        self.assertFalse((folder/'plan.json').exists())
        self.assertEqual(json.loads((folder/'result.json').read_text(encoding='utf-8'))['detail'], job['detail'])
        # Nine packets: four read-only requests for each healthy joint, then
        # exactly one ID 3 ping. No retries, register writes, torque or motion.
        self.assertEqual(len(port.writes), 9)
        self.assertEqual(port.writes[-1], request(3, 'ping'))
        self.assertTrue(all(packet[4] in (1, 2) for packet in port.writes))
        self.assertEqual(port.positions, initial_positions)
        self.assertEqual(port.torques, initial_torques)

    def test_plan_status_is_detached_and_terminal_only_after_finalization(self):
        workbench = self.server.workbench
        source = self.state.directory/'job_source'
        source.mkdir()
        (source/'paths.json').write_text(json.dumps({'paths': [[[0, 0], [1, 1]]]}))
        workbench.jobs['source'] = dict(id='source', kind='strokes', status='DONE')
        result = SimpleNamespace(status='OK', metrics={'timing': {}, 'nested': {'sample': 1}}, commands=[])
        saving, release_save = threading.Event(), threading.Event()
        persisting, release_persist = threading.Event(), threading.Event()
        finalizing, release_final = threading.Event(), threading.Event()
        original_record = self.state.record
        original_write = Path.write_text

        def save(job_id, stored):
            saving.set()
            if not release_save.wait(5):
                raise RuntimeError('test did not release saving')
            return True

        def write(path, *args, **kwargs):
            if path.name == 'result.json':
                persisting.set()
                if not release_persist.wait(5):
                    raise RuntimeError('test did not release result persistence')
            return original_write(path, *args, **kwargs)

        def record(kind, detail):
            if kind == 'JOB_END':
                finalizing.set()
                if not release_final.wait(5):
                    raise RuntimeError('test did not release finalization')
            original_record(kind, detail)

        def assert_running(job_id):
            # state.lock remains held for planning, yet HTTP polling must work.
            self.assertTrue(self.state.lock.locked())
            code, raw = self.http('/api/jobs')
            self.assertEqual(code, 200)
            snapshot = json.loads(raw)
            current = next(j for j in snapshot['jobs'] if j['id'] == job_id)
            self.assertEqual(snapshot['active'], job_id)
            self.assertEqual(current['status'], 'RUNNING')
            self.assertNotIn('result', current)
            self.assertNotIn(job_id, workbench.plans)

        with patch('planning.build', return_value=(result, {'q0': [0]*5}, {})), \
                patch.object(workbench, '_save_plan', side_effect=save), \
                patch.object(Path, 'write_text', write), \
                patch.object(self.state, 'record', side_effect=record):
            try:
                accepted = workbench.start('plan', dict(mode='demo', image_job='source'))
                self.assertTrue(saving.wait(2))
                assert_running(accepted['id'])
                # These are the fields that used to be shared with HTTP JSON
                # encoding while the planning worker added final diagnostics.
                result.metrics['nested']['sample'] = 2
                result.metrics['late_metric'] = {'samples': list(range(100))}
                assert_running(accepted['id'])
                release_save.set()
                self.assertTrue(persisting.wait(2))
                assert_running(accepted['id'])
                release_persist.set()
                self.assertTrue(finalizing.wait(2))
                assert_running(accepted['id'])
            finally:
                release_save.set(); release_persist.set(); release_final.set()
                workbench.worker.join(5)
        self.assertFalse(workbench.worker.is_alive())
        snapshot = workbench.snapshot()
        complete = next(j for j in snapshot['jobs'] if j['id'] == accepted['id'])
        self.assertEqual(complete['status'], 'DONE')
        self.assertIsNone(snapshot['active'])
        self.assertFalse(self.state.lock.locked())
        self.assertIn(accepted['id'], workbench.plans)
        self.assertTrue(complete['result']['metrics']['memory_ready'])
        self.assertIn('job_ready_s', complete['result']['metrics']['timing'])
        self.assertEqual(accepted['status'], 'RUNNING')
        self.assertNotIn('result', accepted)
        # Neither a consumer nor an in-memory plan may mutate published status.
        complete['result']['metrics']['nested']['sample'] = 99
        result.metrics['nested']['sample'] = 100
        next_snapshot = workbench.snapshot()
        current = next(j for j in next_snapshot['jobs'] if j['id'] == accepted['id'])
        self.assertEqual(current['result']['metrics']['nested']['sample'], 2)

    def test_execution_timeline_is_live_but_transport_failure_is_not_published_early(self):
        workbench = self.server.workbench
        running, release_run = threading.Event(), threading.Event()
        closing, release_close = threading.Event(), threading.Event()
        port = DemoPort()

        def close():
            closing.set()
            if not release_close.wait(5):
                raise RuntimeError('test did not release close')
            raise OSError('test transport close failed')
        port.close = close

        class FakeExecutor:
            def __init__(self, device, machine, cancelled, audit):
                self.audit = audit

            def jog(self, *args):
                self.audit('FIRST_COMMAND', {'monotonic_s': 12.5})
                self.audit('FIRST_DRAW_COMMAND', {'monotonic_s': 13.5})
                running.set()
                if not release_run.wait(5):
                    raise RuntimeError('test did not release motion')
                return {'task_complete': True}

        with patch.object(workbench, 'connect', return_value=(port, machine())), \
                patch('workbench.Executor', FakeExecutor):
            try:
                accepted = workbench.start('jog', dict(mode='demo', id=1, delta=1))
                self.assertTrue(running.wait(2))
                snapshot = workbench.snapshot()
                current = snapshot['jobs'][-1]
                self.assertEqual(current['status'], 'RUNNING')
                self.assertEqual(current['timeline'], {'first_command': 12.5, 'first_pen_down': 13.5})
                release_run.set()
                self.assertTrue(closing.wait(2))
                self.assertEqual(workbench.snapshot()['jobs'][-1]['status'], 'RUNNING')
                self.assertEqual(workbench.snapshot()['active'], accepted['id'])
            finally:
                release_run.set(); release_close.set()
                workbench.worker.join(5)
        final = workbench.snapshot()
        self.assertIsNone(final['active'])
        self.assertEqual(final['jobs'][-1]['status'], 'FAILED')
        self.assertIn('test transport close failed', final['jobs'][-1]['detail'])
        self.assertFalse(self.state.lock.locked())
        self.assertFalse(port.writes)

    def test_background_save_start_failure_revokes_plan_before_failed_publication(self):
        workbench = self.server.workbench
        source = self.state.directory/'job_source'
        source.mkdir()
        (source/'paths.json').write_text(json.dumps({'paths': [[[0, 0], [1, 1]]]}))
        workbench.jobs['source'] = dict(id='source', kind='strokes', status='DONE')
        result = SimpleNamespace(status='OK', metrics={'timing': {}}, commands=[])
        registering, release_register = threading.Event(), threading.Event()

        def fail_queue(job_id, stored, folder):
            registering.set()
            if not release_register.wait(5):
                raise RuntimeError('test did not release registration')
            raise OSError('test background thread startup failed')

        with patch('planning.build', return_value=(result, {'q0': [0]*5}, {})), \
                patch.object(workbench, '_queue_plan_save', side_effect=fail_queue):
            try:
                accepted = workbench.start('plan', dict(mode='demo', image_job='source', background_save=True))
                self.assertTrue(registering.wait(2))
                self.assertIn(accepted['id'], workbench.plans)
                snapshot = workbench.snapshot()
                self.assertEqual(snapshot['active'], accepted['id'])
                self.assertEqual(snapshot['jobs'][-1]['status'], 'RUNNING')
                self.assertTrue(self.state.lock.locked())
            finally:
                release_register.set()
                workbench.worker.join(5)
        self.assertFalse(workbench.worker.is_alive())
        snapshot = workbench.snapshot()
        failed = snapshot['jobs'][-1]
        self.assertIsNone(snapshot['active'])
        self.assertEqual(failed['status'], 'FAILED')
        self.assertIn('test background thread startup failed', failed['detail'])
        self.assertNotIn(accepted['id'], workbench.plans)
        self.assertNotIn(accepted['id'], workbench._save_states)
        self.assertFalse(failed['result']['metrics']['memory_ready'])
        self.assertFalse(failed['result']['metrics']['history_saved'])
        self.assertFalse(self.state.lock.locked())
        saved = json.loads((self.state.directory/('job_'+accepted['id'])/'result.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['status'], 'FAILED')

    def test_busy_excludes_probe(self):
        self.state.lock.acquire()
        try:self.assertEqual(self.http('/api/probe',dict(mode='demo',ids=[1]))[0],409)
        finally:self.state.lock.release()

    def test_real_probe_closes_transport(self):
        p=DemoPort();p.close=lambda:setattr(p,'closed',True)
        self.state.allow_real=True;self.state.real_factory=lambda *a:p
        code,_=self.http('/api/probe',dict(mode='real',ids=[1],port='COM99',baudrate=1000000,confirmed=True))
        self.assertEqual(code,200);self.assertTrue(p.closed)

    def test_heartbeat_expiry_does_not_stop_job(self):
        w=self.server.workbench
        def expired():w.heartbeat_at=time.monotonic()-4
        with patch.object(w,'touch',expired):
            j=w.start('jog',dict(mode='demo',id=1,delta=10))
            w.worker.join(5)
        self.assertEqual(w.jobs[j['id']]['status'],'DONE')
        self.assertTrue(w.jobs[j['id']]['result']['task_complete'])

    def test_invalid_execution_never_opens_real_port(self):
        w=self.server.workbench;w.allow_motion=True;self.state.allow_real=True
        w.machine=machine()
        j=w.start('execute',dict(mode='real',plan_job='missing',port='COM99',baudrate=1000000,confirmed=True))
        w.worker.join(5)
        self.assertEqual(w.jobs[j['id']]['status'],'FAILED')
        self.assertEqual(self.opened,[])

    def test_http_image_upload_and_plan_job(self):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        raw=(ROOT/'examples/input.png').read_bytes()
        c.request('POST','/api/image',raw,{'X-Console-Token':self.state.token,'Content-Type':'image/png'})
        r=c.getresponse();self.assertEqual(r.status,202);image_id=json.loads(r.read())['id'];c.close()
        self.server.workbench.worker.join(20)
        self.assertEqual(self.server.workbench.jobs[image_id]['status'],'DONE')
        code,raw=self.http('/api/plan',dict(mode='demo',image_job=image_id))
        plan_id=json.loads(raw)['id'];self.assertEqual(code,202)
        self.server.workbench.worker.join(20)
        self.assertEqual(self.server.workbench.jobs[plan_id]['status'],'DONE')
        self.assertEqual(self.http('/job/'+plan_id+'/plan.json')[0],200)


class PipelineTests(unittest.TestCase):
    def test_original_vendor_hashes(self):
        source=ROOT/'vendor/armvision'
        manifest=json.loads((source/'ORIGIN.json').read_text(encoding='utf-8'))
        for name,info in manifest['files'].items():
            self.assertEqual(hashlib.sha256((source/name).read_bytes()).hexdigest(),info['sha256'])

    def test_image_to_nominal_plan(self):
        from vision import convert
        from planning import build
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            result=convert(ROOT/'examples/input.png',out)
            self.assertEqual(result['strokes'],1)
            plan,spec,cfg=build(result,out/'plan')
            self.assertEqual(plan.status,'OK')
            self.assertFalse(plan.physical_authorized)
            self.assertGreater(len(plan.commands),0)
            self.assertEqual(len(spec['strokes']),1)

    def test_photo_pipeline_runs_original_processor(self):
        from vision import convert
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            r=convert(ROOT/'examples/input.png',out,'photo',max_segments=800)
            self.assertGreater(r['segments'],0)
            self.assertTrue((out/'lineart.png').is_file())

    def test_blank_image_fails(self):
        from PIL import Image
        from vision import convert
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'blank.png';Image.new('RGB',(64,64),'white').save(p)
            with self.assertRaises(ValueError):convert(p,Path(d)/'out')

    def test_paper_basis_validation(self):
        from planning import drawing_spec,nominal
        _,paper,q=nominal();paper['u']=[0,0,0]
        with self.assertRaises(ValueError):drawing_spec(dict(paths=[[[0,0],[1,1]]],width_mm=20,height_mm=20),paper,q)


if __name__=='__main__': unittest.main()
