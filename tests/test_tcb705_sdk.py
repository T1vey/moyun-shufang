"""SDK V2.4.1 motion path (2026-10-20): program blocks -> moveJoints/moveLine, live speed. No hardware."""
import copy
import json
import math
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_tcb705_web import WebExecutorTests, Clock  # noqa: E402
from tcb705 import sdk_motion as S  # noqa: E402
from tcb705 import web_executor as W  # noqa: E402
from tcb705.config import validate, digest  # noqa: E402


class FakeSdk:
    """Drives the web test's FakeController like the real controller would execute queued SDK moves."""

    def __init__(self, ctrl, clock, positions, refuse_after=None):
        self.ctrl = ctrl; self.clock = clock; self.positions = positions; self.refuse_after = refuse_after
        self.seq = 9; self.moves = []; self.ends = {}; self.speeds = []; self.stops = 0; self.gen = 0
        ctrl.is_home = False

    def _xyz(self, kind, values):
        if kind == 'L':
            return list(values[:3])
        return self.positions[tuple(round(v, 4) for v in values)]

    def move(self, kind, values, smooth=0, acc=0.0, dec=0.0, ratio=0.0):
        if self.refuse_after is not None and len(self.moves) >= self.refuse_after:
            return 1
        c = self.ctrl
        target = self._xyz(kind, values)
        if not c.running or self._reached(len(c.targets)):   # idle: a new move starts from here
            c.pose(); c.origin = list(c.p[:3]); c.t0 = self.clock(); c.targets = []; c.running = True
            self.gen += 1
        c.targets.append(target)
        c.final_q = list(values) if kind == 'J' else None
        self.seq += 1; self.moves.append((kind, list(values), smooth)); self.ends[self.seq] = (self.gen, len(c.targets))
        return self.seq

    def _reached(self, n):
        c = self.ctrl
        if not c.running:
            return True
        pts = [c.origin] + c.targets[:n]
        need = sum(math.dist(a, b) for a, b in zip(pts[:-1], pts[1:]))
        return c.speed * (self.clock() - c.t0) >= need - 1e-9

    def finished(self, seq):
        gen, n = self.ends[seq]
        return True if gen < self.gen or self._reached(n) else None

    def stop(self, emergency=True):
        self.stops += 1; self.ctrl.pose(); self.ctrl.running = False

    def set_speed(self, pct):
        self.speeds.append(pct); return float(pct)


class SdkExecutorTests(WebExecutorTests):
    def sdk_fake(self, refuse_after=None, depth=1):
        cfg, ctrl, clock = self.home_fake()
        cfg['execution']['sdk'] = dict(enabled=True, queue_depth=depth)
        validate(cfg)
        positions = {tuple(round(v, 4) for v in q): self.mm[i].tolist() for i, q in enumerate(self.nodes['sdk_degrees'])}
        sdk = FakeSdk(ctrl, clock, positions, refuse_after)
        return cfg, ctrl, clock, sdk, S.SdkMotion(sdk, ctrl, cfg, sleep=clock.sleep)

    def run_sdk(self, cfg, ctrl, clock, motion, **kw):
        return W.execute(self.tmp.name, cfg, controller=ctrl, clock=clock, sleep=clock.sleep, motion=motion, **kw)

    def test_draws_through_sdk_without_programs(self):
        for depth in (1, 4):
            cfg, ctrl, clock, sdk, motion = self.sdk_fake(depth=depth)
            result = self.run_sdk(cfg, ctrl, clock, motion)
            self.assertEqual((result['status'], result['motion']), ('DONE', 'sdk'))
            self.assertEqual(ctrl.programs, [])                       # no controller program downloaded
            self.assertNotIn('run_1', ctrl.calls)                     # run key never pressed
            self.assertEqual(sdk.speeds, [W.settings(cfg)['draw_speed_pct']])
            kinds = [m[0] for m in sdk.moves]
            self.assertEqual(kinds[:3], ['L', 'L', 'J'])              # home: up, across, exact joints
            self.assertEqual(kinds[-3:], ['L', 'L', 'J'])             # back home at the end
            drawn = [m[1] for m in sdk.moves[3:-3]]
            self.assertTrue(drawn and all(m[0] == 'J' for m in sdk.moves[3:-3]))
            self.assertEqual(drawn[-1], [round(v, 4) for v in self.nodes['sdk_degrees'][-1]])
            self.assertLess(math.dist(ctrl.p[:3], self.mm[0]), 0.6)   # ended at home
            self.assertEqual(ctrl.calls[-1], 'restore')

    def test_queue_depth_limits_outstanding_moves(self):
        cfg, ctrl, clock, sdk, motion = self.sdk_fake(depth=2)
        seen = []
        orig = sdk.move
        def move(*a, **k):
            seen.append(sum(1 for s in motion.sent if sdk.finished(s) is None)); return orig(*a, **k)
        sdk.move = move
        self.run_sdk(cfg, ctrl, clock, motion)
        self.assertLessEqual(max(seen), 1)    # never a third move while two are running

    def test_refused_move_stops_and_is_not_resent(self):
        cfg, ctrl, clock, sdk, motion = self.sdk_fake(refuse_after=5)
        events = []
        with self.assertRaises(W.ExecutionError):
            self.run_sdk(cfg, ctrl, clock, motion, progress=events.append)
        self.assertGreaterEqual(sdk.stops, 1)
        self.assertIn('stop', ctrl.calls)                          # Web stop as backup
        self.assertEqual(len(sdk.moves), 5)                         # nothing re-sent after the refusal
        self.assertTrue(any('SDK_REFUSED' in e.get('error', '') for e in events))

    def test_board_stop_goes_home_through_sdk(self):
        cfg, ctrl, clock, sdk, motion = self.sdk_fake()
        seen = []
        def cancel():
            t = next((e['t'] for e in seen if e.get('event') == 'CHUNK_START'), None)
            return t is not None and clock() > t + 1.0
        with self.assertRaises(W.CancelledByUser):
            self.run_sdk(cfg, ctrl, clock, motion, cancel=cancel, progress=seen.append)
        events = [e['event'] for e in seen]
        self.assertGreaterEqual(sdk.stops, 1)
        self.assertIn('HOME_AFTER_STOP_DONE', events)
        self.assertEqual(ctrl.programs, [])

    def test_live_speed_reaches_running_drawing(self):
        cfg, ctrl, clock, sdk, motion = self.sdk_fake()
        self.assertIsNone(S.live_speed(30))                # nothing running
        with motion:
            self.assertEqual(S.live_speed(42), 42.0)
        self.assertEqual(sdk.speeds, [42.0])
        self.assertIsNone(S.live_speed(30))
        for bad in (0, -1, 101, 'x', None, float('nan')):
            with self.assertRaises(ValueError):
                S.check_speed(bad)

    def test_sdk_settings_validation_and_digest(self):
        cfg = copy.deepcopy(self.cfg)
        before = digest(cfg)
        cfg['execution']['sdk'] = dict(enabled=True)
        with self.assertRaisesRegex(ValueError, 'joint'):     # cartesian web_program cannot use SDK joints
            validate(cfg)
        cfg['execution']['web_program'].update(mode='joint', ik_role='execution'); validate(cfg)
        self.assertEqual(digest(cfg), digest(dict(cfg, execution={k: v for k, v in cfg['execution'].items() if k != 'sdk'})))
        for bad in (dict(queue_depth=0), dict(acc_time=0.05), dict(port=0), dict(enabled='yes'), dict(local_ip='')):
            c = copy.deepcopy(cfg); c['execution']['sdk'].update(bad)
            with self.assertRaises(ValueError):
                validate(c)
        self.assertEqual(before, digest(self.cfg))


class SdkClientProtocolTests(unittest.TestCase):
    def test_client_against_stand_in_server(self):
        server = str(Path(__file__).resolve().parent / 'fake_sdk_server.py')
        client = S.SdkClient([sys.executable, '-u', server], reply_timeout_s=10)
        try:
            with self.assertRaisesRegex(S.SdkError, 'not connected'):
                client.set_speed(10)
            self.assertEqual(client.connect('192.168.4.23', '192.168.4.4', 8001, 1)['lib_version'], 'V2.4.1')
            self.assertEqual(client.set_speed(35), 35.0)
            self.assertEqual(client.speed(), 35.0)
            seq = client.move('J', [0, 30, 0, 70, 0, 80, 0], smooth=0)
            self.assertGreaterEqual(seq, 10)
            for _ in range(200):
                if client.finished(seq) is not None:
                    break
                threading.Event().wait(0.01)
            self.assertTrue(client.finished(seq))
            with self.assertRaisesRegex(S.SdkError, 'bad target'):
                client.move('L', [1, 2, 3])
            self.assertEqual(client.state(), dict(move=0, paused=False, link=True))
            self.assertEqual(client.alarms(), [])
            client.stop(True)
        finally:
            client.close()
        self.assertIsNotNone(client.proc.poll())


class WorkbenchSpeedTests(unittest.TestCase):
    def test_set_speed_saves_without_touching_plan_identity(self):
        from tcb705.workbench import TCBWorkbench
        from tcb705.config import load
        from tcb705.model import ROOT
        cfg = load(ROOT / 'robots/tcb705/profile.armvision_joint.json')
        records = []
        with tempfile.TemporaryDirectory() as tmp:
            stub = type('Stub', (), {})()
            stub.machine = cfg; stub._speed_lock = threading.Lock(); stub.config_file = Path(tmp) / 'm.json'
            stub.state = type('St', (), {'record': lambda self, k, v: records.append((k, v))})()
            running = cfg   # a drawing holds this same object
            before = digest(cfg)
            r = TCBWorkbench.set_speed(stub, {'speed_pct': 37})
            self.assertEqual((r['speed_pct'], r['live_applied']), (37.0, False))
            saved = json.loads(stub.config_file.read_text(encoding='utf-8'))
            self.assertEqual(saved['execution']['web_program']['draw_speed_pct'], 37.0)
            self.assertEqual(running['execution']['web_program']['air_speed_pct'], 37.0)
            self.assertEqual(digest(saved), before)
            with self.assertRaises(ValueError):
                TCBWorkbench.set_speed(stub, {'speed_pct': 0})
        self.assertEqual(records[0][0], 'TCB_SPEED')


# the inherited web-program tests already run in test_tcb705_web
for _name in [n for n in dir(WebExecutorTests) if n.startswith('test_')]:
    setattr(SdkExecutorTests, _name, None)
del WebExecutorTests

if __name__ == '__main__':
    unittest.main()
