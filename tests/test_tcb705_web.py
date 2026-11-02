"""Web-program executor: program building, chunking and safety exits (fake controller, no hardware)."""
import copy
import math
import tempfile
import unittest

import numpy as np
from tcb705.config import demo_config, validate, readiness
from tcb705.planner import plan
from tcb705 import artifact
from tcb705 import web_executor as W


def strokes():
    return dict(units='mm', width_mm=100, height_mm=100, coordinate_system='full_canvas_xy_up',
                paths=[[[40, 45], [60, 45]], [[40, 55], [50, 60], [60, 55]]])


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, dt):
        self.t += dt


class FakeController:
    """Follows the downloaded program at `speed` mm/s from the moment the run key is set."""

    def __init__(self, clock, start, joints, speed=40.0, sag_mm=0.0, drift=None, stall_after=None, positions=None):
        self.clock = clock; self.p = list(start); self.q = list(joints); self.speed = speed
        self.sag = sag_mm; self.drift = drift; self.stall_after = stall_after; self.positions = positions
        self.calls = []; self.programs = []; self.running = False; self.mode = 'manual'; self.targets = []

    def login(self): self.calls.append('login')
    def axis_count(self): return 7
    def state(self):
        return {'_phc_ctrlkey': '100' if self.mode == 'auto' else '200', '_phc_key': '100' if self.running else '200',
                'g_servo_statero_': '1', '_phc_alarm_': '0', 'g_state_': '1'}
    def active_alarms(self): return []
    def joints(self, n=7): return list(self.q)

    def power(self, mode):
        self.calls.append('power_' + mode)
        if mode == 'auto' and self.mode != 'auto':
            self.p[2] -= self.sag
        self.mode = mode

    def load_program(self, mold, content):
        self.calls.append('load'); self.programs.append(copy.deepcopy(content))
        blocks = [b for b in content['programs'][0]['codeBlock'] if b['fc'] != 'end']
        self.targets = [b['code']['endp'][:3] if b['fc'] == 'hmcLine' else
                        self.positions[tuple(round(v, 4) for v in b['code']['endp'])] for b in blocks]
        self.is_home = blocks[0]['fc'] == 'hmcLine' and blocks[-1]['fc'] == 'hmcRobotFree'
        free = [b['code']['endp'] for b in blocks if b['fc'] == 'hmcRobotFree']
        self.final_q = list(free[-1]) if free and blocks[-1]['fc'] == 'hmcRobotFree' else None

    def run_key(self, running):
        self.calls.append('run_%d' % running)
        if running and not self.running:
            self.t0 = self.clock(); self.origin = list(self.p); self.seg = 0
        self.running = running

    def pose(self):
        self.reads = getattr(self, 'reads', 0) + 1
        if self.reads in getattr(self, 'fail_reads', ()):
            raise OSError('timed out')
        if getattr(self, 'dip_t0', None) is not None:
            dt = self.clock() - self.dip_t0
            self.p[2] = self.dip_ref[2] - (self.restore_dip if dt < 1.0 else 0.0)
        if self.running and self.targets:
            budget = self.speed * (self.clock() - self.t0)
            if self.stall_after is not None:
                budget = min(budget, self.stall_after)
            pts = [self.origin] + self.targets; pos = list(pts[0])
            for a, b in zip(pts[:-1], pts[1:]):
                d = math.dist(a, b)
                if budget <= d:
                    f = budget / d if d else 1.0; pos = [a[i] + f * (b[i] - a[i]) for i in range(3)]; break
                budget -= d; pos = list(b)
            else:
                if getattr(self, 'final_q', None) is not None:
                    self.q = list(self.final_q)   # program finished: joints are the last joint target
            if self.drift:
                pos = [pos[i] + self.drift[i] * (self.clock() - self.t0) for i in range(3)]
            self.p[:3] = pos
        bump = getattr(self, 'bump', None)
        if bump and self.running and not self.is_home and bump[0] <= self.clock() - self.t0 < bump[1]:
            return [self.p[0], self.p[1] + bump[2], self.p[2]] + [180.0, 0.0, 0.0]
        return list(self.p[:3]) + [180.0, 0.0, 0.0]

    def stop(self):
        self.calls.append('stop'); self.running = False; return [('run_key_200', True, '')]

    def restore(self, mold='ArmVision_Draw', manual=True):
        self.calls.append('restore'); self.running = False
        if manual:
            self.mode = 'manual'
        if getattr(self, 'restore_dip', 0):   # simulate the auto->manual transient: dip, then recover
            self.dip_t0 = self.clock(); self.dip_ref = list(self.p)
        return []


class WebExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = demo_config()
        cfg['execution']['web_program'] = dict(enabled=True, mode='cartesian', max_blocks=2000)
        cfg['calibration_verified'] = cfg['sdk_mapping_verified'] = True
        cfg['planning']['final_lift_m'] = 0.06
        from tcb705.model import Model
        model = Model(cfg); seed = np.asarray(cfg['q_start_rad'])
        target = model.fk(seed); target[2, 3] = cfg['paper']['origin_m'][2] + 0.08
        solved = model.solve(target, seed, seed)
        if not solved['ok']:
            raise RuntimeError('Test setup could not reach the high start')
        cfg['q_start_rad'] = solved['q'].tolist()
        validate(cfg)
        cls.cfg = cfg; cls.tmp = tempfile.TemporaryDirectory()
        cls.doc = artifact.save(plan(strokes(), cfg), cls.tmp.name, 'real')
        cls.nodes = artifact.load_nodes(cls.tmp.name, cls.doc)
        cls.mm, _ = W.controller_points(cfg, cls.nodes)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def fake(self, mode='cartesian', **kw):
        clock = Clock(); cfg = copy.deepcopy(self.cfg); cfg['execution']['web_program']['mode'] = mode
        if mode == 'joint':
            cfg['execution']['web_program']['ik_role'] = 'execution'
        positions = {tuple(round(v, 4) for v in q): self.mm[i].tolist() for i, q in enumerate(self.nodes['sdk_degrees'])}
        ctrl = FakeController(clock, self.mm[0].tolist(), self.nodes['sdk_degrees'][0], positions=positions, **kw)
        return cfg, ctrl, clock

    def run_exec(self, cfg, ctrl, clock):
        return W.execute(self.tmp.name, cfg, controller=ctrl, clock=clock, sleep=clock.sleep)

    def test_readiness_and_validation(self):
        self.assertTrue(readiness(self.cfg)['physical_ready'])
        bad = copy.deepcopy(self.cfg); bad['execution']['web_program']['mode'] = 'stream'
        with self.assertRaises(ValueError):
            validate(bad)

    def test_cartesian_merge_and_chunking(self):
        s = W.settings(self.cfg)
        mm, chunks = W.build(self.cfg, self.nodes, s)
        self.assertEqual(len(chunks), 1)
        blocks = chunks[0]['content']['programs'][0]['codeBlock']
        self.assertEqual(blocks[-1]['fc'], 'end')
        self.assertLess(len(blocks) - 1, len(mm) / 3)  # straight 1 mm samples merged
        self.assertTrue(all(b['fc'] == 'hmcLine' and b['code']['mask'] == 63 for b in blocks[:-1]))
        np.testing.assert_allclose(blocks[0]['code']['endp'][3:], [180, 0, 0], atol=1e-6)
        self.assertEqual(chunks[0]['node_index'][-1], len(mm) - 1)
        # every dropped node lies on its chord within tolerance
        keep = [0] + chunks[0]['node_index']
        for a, b in zip(keep[:-1], keep[1:]):
            for k in range(a + 1, b):
                self.assertLessEqual(W._point_line(mm[k], mm[a], mm[b]), s['merge_tolerance_mm'] + 1e-9)
        s2 = dict(s, max_blocks=5)
        _, small = W.build(self.cfg, self.nodes, s2)
        self.assertGreater(len(small), 1)
        self.assertEqual(sum(c['blocks'] for c in small), len(blocks) - 1)
        self.assertTrue(all(c['blocks'] <= 5 for c in small))

    def test_joint_mode_blocks(self):
        s = dict(W.settings(self.cfg), mode='joint', ik_role='execution')
        _, chunks = W.build(self.cfg, self.nodes, s)
        blocks = [b for c in chunks for b in c['content']['programs'][0]['codeBlock'] if b['fc'] != 'end']
        keep = W.joint_merge(self.cfg, self.nodes, s)          # verified merged knots (2026-10-25)
        self.assertEqual(len(blocks), len(keep) - 1); self.assertLess(len(keep), len(self.mm))
        self.assertTrue(all(b['fc'] == 'hmcRobotFree' and b['code']['mask'] == 127 and len(b['code']['endp']) == 7 for b in blocks))

    def test_execute_cartesian_completes_and_restores(self):
        cfg, ctrl, clock = self.fake()
        result = self.run_exec(cfg, ctrl, clock)
        self.assertEqual(result['status'], 'DONE'); self.assertTrue(result['physical_motion'])
        self.assertEqual(ctrl.calls[:2], ['login', 'power_auto'])
        self.assertEqual(ctrl.calls[-1], 'restore'); self.assertNotIn('stop', ctrl.calls)
        self.assertLess(math.dist(ctrl.p[:3], self.mm[-1]), 0.11)

    def test_execute_joint_mode_completes(self):
        cfg, ctrl, clock = self.fake('joint')
        self.assertEqual(self.run_exec(cfg, ctrl, clock)['mode'], 'joint')
        self.assertEqual(ctrl.programs[0]['programs'][0]['codeBlock'][0]['fc'], 'hmcRobotFree')

    def home_fake(self, offset=(12.0, -8.0, -6.0), tilt_joints=0.7):
        """Joint mode with home = plan start; the arm starts elsewhere (drifted, pen tilted)."""
        cfg, ctrl, clock = self.fake('joint')
        cfg['execution']['web_program']['home'] = dict(enabled=True, joint_degrees=[round(v, 4) for v in self.nodes['sdk_degrees'][0]])
        validate(cfg)
        ctrl.p[:3] = [self.mm[0][i] + offset[i] for i in range(3)]
        ctrl.q = [v + tilt_joints for v in ctrl.q]
        return cfg, ctrl, clock

    def test_home_before_and_after_drawing(self):
        cfg, ctrl, clock = self.home_fake()
        result = self.run_exec(cfg, ctrl, clock)
        self.assertEqual(result['status'], 'DONE')
        events = [e['event'] for e in result['log']]
        self.assertLess(events.index('HOME_DONE'), events.index('CHUNK_START'))
        self.assertGreater(events.index('RETURN_HOME_DONE'), events.index('CHUNK_DONE'))
        home = ctrl.programs[0]['programs'][0]['codeBlock']
        self.assertEqual([b['fc'] for b in home[:3]], ['hmcLine', 'hmcLine', 'hmcRobotFree'])
        self.assertGreaterEqual(home[0]['code']['endp'][2], self.mm[0][2] - 1e-3)   # first move only rises
        self.assertEqual(home[0]['code']['endp'][:2], [round(self.mm[0][0] + 12.0, 3), round(self.mm[0][1] - 8.0, 3)])
        self.assertLess(math.dist(ctrl.p[:3], self.mm[0]), 0.6)                      # ends back at home
        self.assertEqual(ctrl.calls[-1], 'restore')

    def test_plan_not_from_home_refused_before_motion(self):
        cfg, ctrl, clock = self.home_fake()
        cfg['execution']['web_program']['home']['joint_degrees'][0] += 1.0
        with self.assertRaisesRegex(W.ExecutionError, 'PLAN_NOT_FROM_HOME'):
            self.run_exec(cfg, ctrl, clock)
        self.assertNotIn('power_auto', ctrl.calls)

    def test_home_from_low_start_draws(self):
        # user decision 2026-10-18: a low start is homed automatically, never refused
        cfg, ctrl, clock = self.home_fake(offset=(0.0, 0.0, -40.0))
        result = self.run_exec(cfg, ctrl, clock)
        events = [e['event'] for e in result['log']]
        self.assertEqual(result['status'], 'DONE')
        self.assertIn('WARN_LOW_START', events); self.assertIn('HOME_DONE', events)

    def test_deviation_only_warns_in_home_mode(self):
        cfg, ctrl, clock = self.home_fake()
        ctrl.bump = (1.0, 2.0, 6.0)   # 6 mm sideways for 1 s while drawing
        result = self.run_exec(cfg, ctrl, clock)
        events = [e['event'] for e in result['log']]
        self.assertEqual(result['status'], 'DONE')
        self.assertIn('WARN_DEVIATION', events); self.assertNotIn('stop', ctrl.calls)

    def test_pose_read_error_is_retried(self):
        cfg, ctrl, clock = self.home_fake()
        ctrl.fail_reads = {40, 41, 42}
        result = self.run_exec(cfg, ctrl, clock)
        self.assertEqual(result['status'], 'DONE')
        self.assertIn('READ_RETRY', [e['event'] for e in result['log']])

    def test_board_stop_then_goes_home(self):
        cfg, ctrl, clock = self.home_fake()
        seen = []
        def cancel():
            return any(e.get('event') == 'CHUNK_START' for e in seen) and clock() > ctrl.t0 + 1.0
        with self.assertRaises(W.CancelledByUser):
            W.execute(self.tmp.name, cfg, controller=ctrl, clock=clock, sleep=clock.sleep, cancel=cancel,
                      progress=seen.append)
        events = [e['event'] for e in seen]
        self.assertIn('stop', ctrl.calls)
        self.assertIn('HOME_AFTER_STOP_DONE', events)
        self.assertLess(math.dist(ctrl.p[:3], self.mm[0]), 0.6)   # back at home
        self.assertEqual(ctrl.calls[-1], 'restore')

    def test_home_validation(self):
        bad = copy.deepcopy(self.cfg)
        bad['execution']['web_program']['home'] = dict(enabled=True, joint_degrees=[0.0] * 6)
        with self.assertRaises(ValueError):
            validate(bad)
        bad['execution']['web_program']['home'] = dict(enabled=True, joint_degrees=[0.0] * 7)   # cartesian mode
        with self.assertRaises(ValueError):
            validate(bad)

    def test_in_memory_plan_matches_files(self):
        # 2026-10-18: real-mode plans are no longer written; memory must equal the file round trip
        import json
        result = plan(strokes(), self.cfg)
        with tempfile.TemporaryDirectory() as d:
            artifact.save(result, d, 'real'); doc_f = artifact.load(d, self.cfg, with_rows=False)
            nodes_f = artifact.load_nodes(d, doc_f)
            doc_m, nodes_m = artifact.freeze(result, 'real')
            self.assertEqual(json.dumps(nodes_m, separators=(',', ':')), json.dumps(nodes_f, separators=(',', ':')))
            for k in ('config_digest', 'model_sha256', 'q_start_rad', 'period_s', 'preview'):
                self.assertEqual(json.dumps(doc_m[k]), json.dumps(doc_f[k]))
            programs = []
            for frozen in (None, (doc_m, nodes_m)):
                cfg, ctrl, clock = self.fake('joint')
                r = W.execute(d, cfg, controller=ctrl, clock=clock, sleep=clock.sleep, frozen=frozen)
                self.assertEqual(r['status'], 'DONE'); programs.append(json.dumps(ctrl.programs))
            self.assertEqual(programs[0], programs[1])

    def test_in_memory_plan_rejects_changed_config(self):
        doc_m, nodes_m = artifact.freeze(plan(strokes(), self.cfg), 'real')
        cfg, ctrl, clock = self.fake('joint'); cfg['paper']['origin_m'][2] += 0.001
        with self.assertRaisesRegex(ValueError, '请重新规划'):
            W.execute(None, cfg, controller=ctrl, clock=clock, sleep=clock.sleep, frozen=(doc_m, nodes_m))
        self.assertEqual(ctrl.calls, [])

    def test_chunked_execution(self):
        cfg, ctrl, clock = self.fake(); cfg['execution']['web_program']['max_blocks'] = 4
        result = self.run_exec(cfg, ctrl, clock)
        self.assertGreater(result['chunks'], 1); self.assertEqual(len(ctrl.programs), result['chunks'])
        self.assertEqual(ctrl.calls.count('power_auto'), 1)

    def test_power_on_small_residual_shift_settles(self):
        cfg, ctrl, clock = self.fake(sag_mm=2.0)
        self.assertEqual(self.run_exec(cfg, ctrl, clock)['status'], 'DONE')

    def test_persistent_sag_cannot_bypass_path_watchdog(self):
        cfg, ctrl, clock = self.fake(sag_mm=6.0)
        with self.assertRaisesRegex(W.ExecutionError, '偏离'):
            self.run_exec(cfg, ctrl, clock)
        self.assertIn('stop', ctrl.calls)

    def test_large_sag_refused_without_program(self):
        cfg, ctrl, clock = self.fake(sag_mm=12.0)
        with self.assertRaisesRegex(W.ExecutionError, '上电位移'):
            self.run_exec(cfg, ctrl, clock)
        self.assertNotIn('load', ctrl.calls)

    def test_path_deviation_stops(self):
        cfg, ctrl, clock = self.fake(drift=(0, 2.0, 0))
        with self.assertRaisesRegex(W.ExecutionError, '偏离'):
            self.run_exec(cfg, ctrl, clock)
        self.assertIn('stop', ctrl.calls)

    def test_no_progress_stops(self):
        cfg, ctrl, clock = self.fake(stall_after=5.0)
        with self.assertRaisesRegex(W.ExecutionError, 'NO_PROGRESS'):
            self.run_exec(cfg, ctrl, clock)
        self.assertIn('stop', ctrl.calls)

    def test_start_mismatch_and_disabled(self):
        cfg, ctrl, clock = self.fake(); ctrl.p[0] += 5
        with self.assertRaisesRegex(W.ExecutionError, 'START_MISMATCH'):
            self.run_exec(cfg, ctrl, clock)
        self.assertNotIn('power_auto', ctrl.calls)
        cfg, ctrl, clock = self.fake(); cfg['execution']['web_program']['enabled'] = False
        with self.assertRaisesRegex(W.ExecutionError, 'WEB_PROGRAM_DISABLED'):
            self.run_exec(cfg, ctrl, clock)
        self.assertNotIn('power_auto', ctrl.calls)


if __name__ == '__main__':
    unittest.main()


class PlanningOnlyModeTests(unittest.TestCase):
    def test_web_profile_gates(self):
        from tcb705.config import load
        from tcb705.calibration import assert_model_ready
        c = load(W.__file__.replace('tcb705\web_executor.py', 'robots/tcb705/profile.armvision_web.json').replace('tcb705/web_executor.py', 'robots/tcb705/profile.armvision_web.json'))
        self.assertFalse(c['sdk_mapping_verified'])
        assert_model_ready(c)  # planning_only cartesian: paper calibration is enough
        self.assertTrue(readiness(c)['physical_ready'])
        self.assertFalse(W.mapping_required(c))
        j = copy.deepcopy(c); j['execution']['web_program']['mode'] = 'joint'
        with self.assertRaisesRegex(ValueError, 'joint'):
            validate(j)  # joint mode needs ik_role=execution
        j['execution']['web_program']['ik_role'] = 'execution'
        validate(j); self.assertTrue(W.mapping_required(j))
        self.assertFalse(readiness(j)['physical_ready'])
        with self.assertRaises(ValueError):
            assert_model_ready(j)  # local joints would drive the arm: needs mapping

    def test_current_uvw_used_for_blocks(self):
        cfg = demo_config(); cfg['execution']['web_program'] = dict(enabled=True)
        cfg['calibration_verified'] = True
        with tempfile.TemporaryDirectory() as d:
            doc = artifact.save(plan(strokes(), cfg), d, 'real'); nodes = artifact.load_nodes(d, doc)
            _, chunks = W.build(cfg, nodes, W.settings(cfg), uvw=[179.9, 4.2, 179.8])
            self.assertEqual(chunks[0]['content']['programs'][0]['codeBlock'][0]['code']['endp'][3:], [179.9, 4.2, 179.8])


class JointInterpolationTests(unittest.TestCase):
    def test_joint_lerp_between_dense_nodes_stays_on_segment(self):
        cfg = demo_config(); cfg['execution']['web_program'] = dict(enabled=True, mode='joint', ik_role='execution')
        cfg['calibration_verified'] = cfg['sdk_mapping_verified'] = True
        with tempfile.TemporaryDirectory() as d:
            doc = artifact.save(plan(strokes(), cfg), d, 'real'); nodes = artifact.load_nodes(d, doc)
            draw, air = W.joint_interpolation_error(cfg, nodes)
            self.assertLess(draw, 0.05); self.assertLess(air, 1.0)
            # sparse nodes (every 20th) must be detected as deviating more
            sparse = dict(nodes, positions_m=nodes['positions_m'][::20], sdk_degrees=nodes['sdk_degrees'][::20],
                          interval_phase=nodes['interval_phase'][::20][:len(nodes['positions_m'][::20]) - 1])
            self.assertGreater(max(W.joint_interpolation_error(cfg, sparse)), draw)


class CanvasFitTests(unittest.TestCase):
    def test_contain_keeps_aspect_and_centres(self):
        from tcb705.calibration import map_canvas
        from tcb705.config import load
        c = load(W.__file__.replace('tcb705\web_executor.py', 'robots/tcb705/profile.armvision_web.json').replace('tcb705/web_executor.py', 'robots/tcb705/profile.armvision_web.json'))
        W_, H_ = c['paper']['width_mm'], c['paper']['height_mm']
        square = dict(units='mm', width_mm=40, height_mm=30, coordinate_system='full_canvas_xy_up',
                      paths=[[[0, 0], [40, 0], [40, 30], [0, 30], [0, 0]]])
        out = map_canvas(square, c); xs = [p[0] for p in out['paths'][0]]; ys = [p[1] for p in out['paths'][0]]
        self.assertAlmostEqual((max(xs) - min(xs)) / (max(ys) - min(ys)), 40 / 30, places=9)   # aspect kept
        self.assertAlmostEqual((min(xs) + max(xs)) / 2, W_ / 2, places=9); self.assertAlmostEqual((min(ys) + max(ys)) / 2, H_ / 2, places=9)
        self.assertLessEqual(max(xs) - min(xs), W_ + 1e-9); self.assertLessEqual(max(ys) - min(ys), H_ + 1e-9)
        c2 = copy.deepcopy(c); c2['planning']['canvas_fit'] = 'stretch'
        out2 = map_canvas(square, c2); xs2 = [p[0] for p in out2['paths'][0]]; ys2 = [p[1] for p in out2['paths'][0]]
        self.assertAlmostEqual(max(xs2) - min(xs2), W_, places=9); self.assertAlmostEqual(max(ys2) - min(ys2), H_, places=9)


class ControllerDHModelTests(unittest.TestCase):
    def test_dh_model_reproduces_controller_poses(self):
        from tcb705.config import load
        from tcb705.collision import check_batch
        c = load(W.__file__.replace('tcb705\web_executor.py', 'robots/tcb705/profile.armvision_joint.json').replace('tcb705/web_executor.py', 'robots/tcb705/profile.armvision_joint.json'))
        from tcb705.model import Model
        m = Model(c)
        pairs = [([-0.008239746094, 34.43183899, -0.005493164062, 70.90026855, -0.00617980957, 78.83995056, -0.001373291016], [-439.0218506, 0.1133498251, 292.3725891]),
                 ([-0.019, 28.51, -0.037, 86.486, -0.042, 71.207, -0.002], [-388.854, 0.464, 265.994]),
                 ([-2.439, 30.328, -0.439, 82.849, -0.128, 73.748, -1.742], [-398.809, 19.952, 269.319])]
        for q, p in pairs:  # controller readings recorded 2026-10-17/18
            np.testing.assert_allclose(m.fk(m.from_sdk(q))[:3, 3] * 1000, p, atol=0.03)
            check_batch(m, np.atleast_2d(m.from_sdk(q)))  # real drawing poses are collision-free
        self.assertTrue(np.allclose(m.data[:, 16:19], [0, 0, 1]))       # FPGA core: local +Z axes
        self.assertTrue(np.allclose(m.data[:, 12:16], [0, 0, 0, 1]))     # FPGA core: rigid rows


class JointMergeTests(unittest.TestCase):
    def test_offline_diagnostic_merge_reduces_blocks_within_tolerance(self):
        cfg = demo_config(); cfg['execution']['web_program'] = dict(enabled=True, mode='joint', ik_role='execution')
        cfg['calibration_verified'] = cfg['sdk_mapping_verified'] = True
        with tempfile.TemporaryDirectory() as d:
            doc = artifact.save(plan(strokes(), cfg), d, 'real'); nodes = artifact.load_nodes(d, doc)
            s = W.settings(cfg); keep = W._joint_merge_candidates(cfg, nodes, s)
            self.assertLess(len(keep), len(nodes['positions_m']) / 3)
            near, air = W.joint_block_error(cfg, nodes, keep)
            self.assertLessEqual(near, s['joint_merge_tolerance_mm'] * 1.5); self.assertLessEqual(air, s['joint_air_merge_tolerance_mm'] * 1.5)
            ph = nodes['interval_phase']   # never merges across a phase change
            for a, b in zip(keep[:-1], keep[1:]):
                self.assertEqual(len(set(ph[a:b])), 1)


class SmoothAssignmentTests(unittest.TestCase):
    def test_smooth_only_at_gentle_vertices(self):
        cfg = demo_config(); cfg['execution']['web_program'] = dict(enabled=True, smooth=3)
        cfg['calibration_verified'] = True
        sq = dict(units='mm', width_mm=100, height_mm=100, coordinate_system='full_canvas_xy_up',
                  paths=[[[40, 40], [60, 40], [60, 60], [40, 60], [40, 40]]])
        with tempfile.TemporaryDirectory() as d:
            doc = artifact.save(plan(sq, cfg), d, 'real'); nodes = artifact.load_nodes(d, doc)
            _, chunks = W.build(cfg, nodes, W.settings(cfg))
            ph = nodes['interval_phase']; stops = set(nodes['stops'])
            for c in chunks:
                for i, b in zip(c['node_index'], c['content']['programs'][0]['codeBlock']):
                    gentle = i < len(nodes['positions_m']) - 1 and i not in stops and ph[i] == ph[i - 1]
                    self.assertEqual(b['code']['smooth'], 3.0 if gentle else 0)
            self.assertGreaterEqual(len(stops - {0}), 3)   # square corners are exact stops


class TrackerTests(unittest.TestCase):
    def test_lagging_arm_is_not_reported_as_deviation(self):
        path = np.array([[0.0, 0.0, 0.0], [1.0, 0, 0], [2.0, 0, 0], [3.0, 0, 0]])
        tr = W.Tracker(path)
        tr.update([0.6, 0.0, 0.0]); tr.update([1.6, 0.0, 0.0])      # tracker reaches node 2 (within 0.5 mm)
        self.assertGreaterEqual(tr.k, 2)
        self.assertLess(tr.update([1.45, 0.0, 0.0]), 1e-9)         # arm slightly behind node 2, on the path
        self.assertAlmostEqual(tr.update([1.45, 0.3, 0.0]), 0.3, places=9)   # true perpendicular deviation
        self.assertGreaterEqual(tr.k, 2)                            # progress never goes backwards

    def test_lift_and_land_again_at_same_point_is_not_deviation(self):
        # 2026-10-25 草书 page: the brush lifts at a paper point and, 17 mm of path later,
        # lands at the same point again. The tracker jumped to the later landing and
        # reported the still-lifting arm as 5.86 mm off the path.
        lift = [[0.0, 0.0, z] for z in np.linspace(0, 6, 13)]
        air = [[x, 0.0, 6.0] for x in (1.0, 2.0)] + [[x, 0.0, 6.0] for x in (1.0, 0.0)]
        land = [[0.0, 0.0, z] for z in np.linspace(6, 0, 13)[1:]]
        tr = W.Tracker(np.array(lift + air + land))
        devs = [tr.update([0.0, 0.0, z]) for z in np.linspace(0, 6, 25)]   # arm lifting
        self.assertLess(max(devs), 1e-9)
        self.assertLess(tr.k, 13)                                   # still on the lift, not the landing
        self.assertAlmostEqual(tr.update([0.0, 0.0, 9.0]), 3.0, places=9)  # a real departure is still caught


class PostRestoreTests(unittest.TestCase):
    def test_post_restore_transient_is_recorded(self):
        t = WebExecutorTests; t.setUpClass()
        try:
            cfg, ctrl, clock = WebExecutorTests.fake(t(), )
            ctrl.restore_dip = 15.0
            result = W.execute(t.tmp.name, cfg, controller=ctrl, clock=clock, sleep=clock.sleep)
            pr = result['post_restore']
            self.assertAlmostEqual(pr['max_dip_mm'], 15.0, places=3)
            self.assertLess(pr['settled_offset_mm'], 0.01)
        finally:
            t.tearDownClass()


class ModeSwitchSafetyTests(unittest.TestCase):
    def test_low_start_refuses_before_power_or_program(self):
        from unittest.mock import patch
        t = WebExecutorTests; t.setUpClass()
        try:
            cfg, ctrl, clock = t.fake(t())
            nodes = copy.deepcopy(t.nodes)
            nodes['positions_m'][0][2] = cfg['paper']['origin_m'][2] + 0.059
            ctrl.p[2] = nodes['positions_m'][0][2] * 1000
            with patch.object(W, 'load_nodes', return_value=nodes):
                with self.assertRaisesRegex(W.ExecutionError, 'MODE_SWITCH_CLEARANCE'):
                    W.execute(t.tmp.name, cfg, controller=ctrl, clock=clock, sleep=clock.sleep)
            self.assertNotIn('power_auto', ctrl.calls)
            self.assertNotIn('load', ctrl.calls)
            self.assertNotIn('restore', ctrl.calls)
        finally:
            t.tearDownClass()

    def test_low_stop_never_switches_mode_or_lifts(self):
        cfg = demo_config(); clock = Clock()
        ctrl = FakeController(clock, [350, 0, cfg['paper']['origin_m'][2] * 1000 + 5], [0] * 7)
        ctrl.mode = 'auto'; ctrl.running = True
        ref, steps = W.restore_safe(ctrl, cfg, clock=clock, sleep=clock.sleep)
        self.assertIsNone(ref); self.assertFalse(steps[0][1])
        self.assertFalse(ctrl.running); self.assertEqual(ctrl.mode, 'auto')
        self.assertNotIn('restore', ctrl.calls); self.assertNotIn('load', ctrl.calls)

    def test_unreadable_pose_never_switches_mode(self):
        from unittest.mock import Mock
        ctrl = Mock(); ctrl.pose.side_effect = OSError('feedback lost')
        ref, _ = W.restore_safe(ctrl, demo_config())
        self.assertIsNone(ref); ctrl.run_key.assert_called_once_with(False)
        ctrl.restore.assert_not_called()

    def test_air_plane_does_not_change_physical_clearance(self):
        cfg = demo_config(); cfg['calibration_source'] = {'contact_z_mm': 219.3}
        cfg['paper']['origin_m'][2] = 0.2343
        self.assertAlmostEqual(W.mode_switch_min_z(cfg, [350, 0, 280]), 279.3)
        W.require_mode_switch_clearance(cfg, [350, 0, 280])
        with self.assertRaises(W.ExecutionError):
            W.require_mode_switch_clearance(cfg, [350, 0, 279])
