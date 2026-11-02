"""硬笔 as the third tool: calibration, test-write task, plan identity and execution gates (no hardware)."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import State
from calligraphy import couplets, hardpen
from calligraphy.presets import binding, tool_of, validate_task
from tcb705 import web_executor as W
from tests.test_masterpiece_store import board_config
from tests.test_text_calligraphy import config as text_config


def pen_config(contact=225.0, press=0.5):
    c = board_config()
    c['hardpen'] = dict(contact_z_mm=contact, press_mm=press, verified=True)
    c['hardpen']['calibration_binding'] = binding(c)
    c['mounted_tool'] = 'hardpen'
    return c


@unittest.skipUnless(hardpen.DB.exists(), 'hard-pen library not built')
class TaskTests(unittest.TestCase):
    def test_test_write_is_centred_and_checked_on_the_server(self):
        c = pen_config()
        for size in hardpen.SIZES:
            t = hardpen.task('永', size, c)
            xs = [x for p in t['paths'] for x, _ in p]; ys = [y for p in t['paths'] for _, y in p]
            self.assertAlmostEqual((min(xs) + max(xs)) / 2, c['paper']['width_mm'] / 2, delta=size * 0.15)
            self.assertLess(max(ys) - min(ys), size * 1.05)
            self.assertTrue(all(0 <= d <= 0.5 for depths in t['calligraphy']['depth_mm'] for d in depths))
            validate_task(t, c)
        for bad in (('永', 12), ('', 10), ('永' * 21, 10)):
            with self.assertRaises(ValueError):
                hardpen.task(bad[0], bad[1], c)
        self.assertEqual(hardpen.missing('永A永'), ['A'])

    def test_surface_and_tool(self):
        c = pen_config()
        meta = hardpen.task('永', 15, c)['calligraphy']
        self.assertEqual(tool_of(meta), 'hardpen'); self.assertEqual(tool_of(None), 'pen')
        self.assertEqual(tool_of({'schema': 'brush-text-v1'}), 'brush')
        self.assertAlmostEqual(couplets.surface(c, meta)['origin_m'][2], 0.225)
        self.assertEqual(couplets.surface(c, None), c['paper'])
        del c['hardpen']['contact_z_mm']
        with self.assertRaises(ValueError):
            couplets.surface(c, meta)

    def test_profile_and_revision_follow_the_calibration(self):
        c = pen_config()
        r = hardpen.revision(c)
        moved = pen_config(contact=226.0)
        self.assertNotEqual(hardpen.revision(moved), r)
        self.assertTrue(hardpen.profile(c, require_verified=True)['verified'])
        stale = copy.deepcopy(c); stale['paper'] = dict(c['paper'], width_mm=200.)
        with self.assertRaises(ValueError):
            hardpen.profile(stale, require_verified=True)          # paper changed: confirm again
        with self.assertRaises(ValueError):
            hardpen.profile(pen_config(press=2.5))


@unittest.skipUnless(hardpen.DB.exists(), 'hard-pen library not built')
class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        from tcb705.workbench import TCBWorkbench
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p = patch('tcb705.accel_runtime.platform_health', return_value={'faulted': True}); p.start(); self.addCleanup(p.stop)
        profile = Path(self.tmp.name) / 'board.json'
        profile.write_text(json.dumps(board_config(), ensure_ascii=False), encoding='utf-8')
        self.w = TCBWorkbench(State(self.tmp.name), simulation=True, profile=profile)

    def run_job(self, kind, data):
        job = self.w.start(kind, data); self.w.worker.join(120)
        return self.w.jobs[job['id']]

    def test_calibrate_switch_and_plan(self):
        with self.assertRaisesRegex(ValueError, '硬笔'):
            self.w.set_tool({'tool': 'hardpen'})                           # not calibrated yet
        with self.assertRaises(ValueError):
            self.w.configure_hardpen({'contact_z_mm': 225.0, 'verified': False})
        with self.assertRaises(ValueError):
            self.w.configure_hardpen({'contact_z_mm': 150.0, 'verified': True})    # far below the pen paper
        out = self.w.configure_hardpen({'contact_z_mm': 225.0, 'press_mm': 0.4, 'verified': True})
        self.assertEqual(out['profile']['max_press_mm'], 0.4); self.assertTrue(out['profile']['verified'])
        self.assertEqual(self.w.set_tool({'tool': 'hardpen'}), {'mounted_tool': 'hardpen'})
        rev = self.w.hardpen_catalog()['revision']
        src = self.run_job('calligraphy', {'schema': 'hardpen-text-v1', 'text': '永', 'font_size_mm': 15, 'revision': rev})
        self.assertEqual(src['status'], 'DONE', src.get('detail'))
        plan = self.run_job('plan', {'image_job': src['id'], 'mode': 'demo'})
        self.assertEqual(plan['status'], 'DONE', plan.get('detail'))
        stale = self.run_job('calligraphy', {'schema': 'hardpen-text-v1', 'text': '永', 'font_size_mm': 15, 'revision': 'old'})
        self.assertEqual(stale['status'], 'FAILED')


@unittest.skipUnless(hardpen.DB.exists(), 'hard-pen library not built')
class GateTests(unittest.TestCase):
    def gate(self, cfg, meta):
        original = W.check_frozen
        W.check_frozen = lambda doc, nodes, config: None
        try:
            W.execute(None, cfg, frozen=({}, dict(calligraphy=meta)))
        finally:
            W.check_frozen = original

    def test_tool_and_calibration_gates(self):
        meta = {'schema': 'hardpen-text-v1'}
        brush = pen_config(); brush['mounted_tool'] = 'brush'
        with self.assertRaisesRegex(W.ExecutionError, 'TOOL_MISMATCH.*硬笔'):
            self.gate(brush, meta)
        with self.assertRaisesRegex(W.ExecutionError, 'TOOL_MISMATCH'):
            self.gate(pen_config(), {'schema': 'brush-text-v1'})
        same_pen = pen_config(); same_pen['mounted_tool'] = 'pen'         # 画笔 and 硬笔 are one pen
        try:
            self.gate(same_pen, meta)
        except Exception as exc:                                          # later checks may stop it
            self.assertNotIn('TOOL_MISMATCH', str(exc))
        bare = pen_config(); del bare['hardpen']['contact_z_mm']
        with self.assertRaisesRegex(W.ExecutionError, 'HARDPEN_NOT_CALIBRATED'):
            self.gate(bare, meta)

    def test_performance_blend_setting(self):
        from tcb705.workbench import PERFORMANCE_BLEND, PERFORMANCE_QUEUE_DEPTH
        from tcb705.sdk_motion import sdk_settings
        c = pen_config(); c['execution']['web_program']['brush_blend'] = dict(PERFORMANCE_BLEND)
        self.assertEqual(W.settings(c)['brush_blend'], PERFORMANCE_BLEND)
        # A blend only reaches the controller with more than one queued move (sdk_motion.pump).
        self.assertGreater(PERFORMANCE_QUEUE_DEPTH, 1)
        self.assertEqual(sdk_settings(dict(c, execution=dict(c['execution'], sdk=dict(enabled=True, queue_depth=PERFORMANCE_QUEUE_DEPTH))))['queue_depth'], 4)
        for bad in (dict(smooth=0, corner_deg=20), dict(smooth=3, corner_deg=90), 'yes'):
            c['execution']['web_program']['brush_blend'] = bad
            with self.assertRaises(ValueError):
                W.settings(c)

    def test_high_travel_deviation_limit(self):
        # 2026-10-28: 3.11 mm off a travel move 70 mm above the paper stopped a poem at 100 %.
        from tcb705.planner import PHASE
        T, D, L = PHASE['TRAVEL'], PHASE['DRAW'], PHASE['LIFT']
        nodes = {'interval_phase': [T, T, D, D, L, T, T]}
        mm = [[0, 0, z] for z in (319.3, 319.3, 249.4, 244.4, 244.4, 249.9, 257.4, 319.3)]
        s = {'path_deviation_mm': 3.0}
        high = W.high_air_z(nodes, mm)
        self.assertAlmostEqual(high, 279.4)
        self.assertEqual(W.deviation_limit(s, nodes, mm, 0, high), 8.0)      # high travel from home
        self.assertEqual(W.deviation_limit(s, nodes, mm, 1, high), 3.0)      # travel coming down to the paper
        for node in (2, 3, 4, 5):                                             # on / near the paper
            self.assertEqual(W.deviation_limit(s, nodes, mm, node, high), 3.0)
        self.assertEqual(W.deviation_limit(s, nodes, mm, 6, high), 3.0)      # low travel end
        self.assertEqual(W.deviation_limit(s, nodes, mm, 0, None), 3.0)      # sketches: unchanged
        self.assertIsNone(W.high_air_z({'interval_phase': [T, T]}, mm))

    def test_hard_pen_floor_margin(self):
        s = {'below_paper_mm': 0.5}
        self.assertEqual(W.paper_margin(s, 'hardpen'), 1.0)              # spring-held pen
        self.assertEqual(W.paper_margin(s, 'brush'), 0.5); self.assertEqual(W.paper_margin(s, 'pen'), 0.5)
        self.assertEqual(W.paper_margin({'below_paper_mm': 1.5}, 'hardpen'), 1.5)
        blended = {'below_paper_mm': 0.5, 'brush_blend': {'smooth': 3, 'corner_deg': 45.0}}
        self.assertEqual(W.paper_margin(blended, 'brush'), 1.0)              # 100 % blended brush (2026-10-28)
        self.assertEqual(W.paper_margin(blended, 'pen'), 0.5)

    def test_clearance_from_the_mounted_pen(self):
        c = pen_config(contact=260.0)
        paper_only = copy.deepcopy(c); paper_only['mounted_tool'] = 'pen'
        self.assertAlmostEqual(W.mode_switch_min_z(c, [0, 0, 0]) - W.mode_switch_min_z(paper_only, [0, 0, 0]),
                               260.0 - c['paper']['origin_m'][2] * 1000, places=3)


@unittest.skipUnless(hardpen.DB.exists(), 'hard-pen library not built')
class ScreenFlowTests(unittest.TestCase):
    def test_confirm_then_plan_and_write_at_the_chosen_speed(self):
        from user_gui.workflow import Workflow
        from tests.test_text_calligraphy import FakePipeline
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        pipe = FakePipeline(); pipe.config = pen_config()
        w = Workflow(pipe, tmp.name)
        for bad in (('永', 15, 70, False), ('永', 12, 70, True), ('永', 15, 60, True), ('永A', 15, 70, True)):
            with self.assertRaises(ValueError):
                w.submit_hardpen(bad[0], bad[1], bad[2], 'hp000000', bad[3])
        self.assertEqual(pipe.calls, [])
        w.submit_hardpen('书 法', 15, 85, 'hp000001', True); w.worker.join(10)
        self.assertEqual(w.state['phase'], 'completed', w.state['message'])
        self.assertEqual(pipe.calls[0], ('hardpen_plan', '书法', 15))
        self.assertIn(('speed', 'hp_plan', 85), pipe.calls)
        self.assertEqual(hardpen.presets()[0], '永'); self.assertTrue(all(not hardpen.missing(p) for p in hardpen.presets()))
        self.assertIn(b'<polyline', hardpen.preview_svg('永', 20, pen_config()))


@unittest.skipUnless(hardpen.DB.exists(), 'hard-pen library not built')
class SavedWorksTests(unittest.TestCase):
    """Real-mode planning only reads the calibrated home joints: no controller, no motion."""
    def setUp(self):
        from tcb705.workbench import TCBWorkbench
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p = patch('tcb705.accel_runtime.platform_health', return_value={'faulted': True}); p.start(); self.addCleanup(p.stop)
        profile = Path(self.tmp.name) / 'board.json'
        c = pen_config(contact=219.3); c['mounted_tool'] = 'pen'                     # the same pen
        profile.write_text(json.dumps(c, ensure_ascii=False), encoding='utf-8')
        self.w = TCBWorkbench(State(self.tmp.name, allow_real=True), simulation=False, profile=profile)

    def run_job(self, kind, data):
        job = self.w.start(kind, data); self.w.worker.join(600)
        return self.w.jobs[job['id']]

    def test_saved_once_then_written_again_without_planning(self):
        first = self.run_job('hardpen_line', {'text': '永', 'font_size_mm': 15, 'mode': 'real'})
        self.assertEqual(first['status'], 'DONE', first.get('detail')); self.assertFalse(first['result']['cached'])
        again = self.run_job('hardpen_line', {'text': '永', 'font_size_mm': 15, 'mode': 'real'})
        self.assertTrue(again['result']['cached'])
        self.assertEqual(self.w.plans[again['id']]['nodes'], self.w.plans[first['id']]['nodes'])
        other = self.run_job('hardpen_line', {'text': '永', 'font_size_mm': 10, 'mode': 'real'})
        self.assertFalse(other['result']['cached'])                                  # another size, another piece
        works = self.w.hardpen_works()['works']
        self.assertEqual(sorted((x['text'], x['font_size_mm'], x['ready']) for x in works), [('永', 10, True), ('永', 15, True)])
        c = copy.deepcopy(self.w.machine); c['hardpen']['press_mm'] = 0.4; c['hardpen']['calibration_binding'] = binding(c)
        self.w.configure(c)
        self.assertFalse(any(x['ready'] for x in self.w.hardpen_works()['works']))   # stale after calibration

    def test_same_photo_strokes_are_planned_once(self):
        # 照片绘画 (2026-10-28): the same strokes at the same size read the saved commands back.
        strokes = dict(units='mm', width_mm=100, height_mm=100, coordinate_system='full_canvas_xy_down',
                       paths=[[[40, 45], [60, 45]], [[40, 55], [60, 55]]])
        ids = []
        for size in ([100., 100.], [100., 100.], [80., 80.]):
            src = self.run_job('strokes', {'paths': strokes})
            self.assertEqual(src['status'], 'DONE', src.get('detail'))
            plan = self.run_job('plan', {'image_job': src['id'], 'mode': 'real', 'store': True, 'drawing_size_mm': size})
            self.assertEqual(plan['status'], 'DONE', plan.get('detail')); ids.append(plan)
        self.assertEqual([p['result']['cached'] for p in ids], [False, True, False])
        self.assertEqual(self.w.plans[ids[1]['id']]['nodes'], self.w.plans[ids[0]['id']]['nodes'])
        self.assertTrue(ids[1]['result']['metrics']['memory_ready'])


class PlanMetadataTests(unittest.TestCase):
    def test_poem_plans_keep_their_identity(self):
        # 2026-10-27: every brush schema keeps schema and revision in the frozen nodes.
        from calligraphy import poems
        from tcb705.planner import _add_brush_metadata
        c = text_config(); c['paper'].update(width_mm=260., height_mm=250.)
        c['calligraphy'] = dict(c['calligraphy'], contact_z_mm=c['paper']['origin_m'][2] * 1000 + 30)
        t = poems.task('p01', 70, 0, 0, c)
        result = {}; _add_brush_metadata(result, t['calligraphy'], [1.0])
        self.assertEqual(result['calligraphy']['schema'], 'brush-poem-v1')
        self.assertEqual(result['calligraphy']['revision'], poems.revision(c))
        self.assertAlmostEqual(couplets.surface(c, result['calligraphy'])['origin_m'][2], c['paper']['origin_m'][2] + .03)


if __name__ == '__main__':
    unittest.main()
