"""名帖指令库: masterpiece commands computed in advance, valid only for the calibration they were made for."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app import State
from calligraphy import composer, glyph_store
from calligraphy.presets import BRUSH, binding
from tcb705 import plan_store
from tcb705.artifact import freeze
from tcb705.calibration import apply_armvision
from tcb705.config import load
from tcb705.model import ROOT, Model
from tcb705.planner import plan
from tcb705.workbench import TCBWorkbench

MASTER = glyph_store.masterpieces()


def board_config():
    """The joint profile with the 2026-10-26 paper (260 x 250 mm) and brush calibration."""
    c = load(ROOT / 'robots/tcb705/profile.armvision_joint.json')
    av = dict(c['armvision'], a_mm=[-559.498, -123.594], b_mm=[-309.498, 136.406])
    av.pop('table', None); av.pop('image', None)
    c = apply_armvision(c, av, reset_verified=False)
    c['calibration_verified'] = True
    c['calligraphy'] = dict(BRUSH, hair_length_mm=12., max_diameter_mm=4., max_press_mm=6., verified=True, contact_z_mm=249.356)
    c['calligraphy']['calibration_binding'] = binding(c)
    c['mounted_tool'] = 'brush'
    c['q_start_rad'] = home(c)     # simulation plans from q_start; the board plans from home
    return c


def home(c):
    return Model(c).from_sdk(c['execution']['web_program']['home']['joint_degrees']).tolist()


@unittest.skipUnless(MASTER, 'no masterpiece library installed')
class ColumnTests(unittest.TestCase):
    def test_columns_partition_the_sentence(self):
        c = board_config()
        for style in MASTER:
            m = glyph_store.manifest(style)
            full = composer.task(m['characters'], 70, 0, c, style)
            parts = [composer.task(m['characters'], 70, 0, c, style, column=k) for k in range(-(-m['count'] // 3))]
            self.assertEqual([p for t in parts for p in t['paths']], full['paths'])
            self.assertEqual([t['calligraphy']['column'] for t in parts], list(range(len(parts))))
            self.assertTrue(all(s['text_index'] // 3 == k for k, t in enumerate(parts) for s in t['calligraphy']['stroke_map']))
            with self.assertRaises(ValueError):
                composer.task(m['characters'], 70, 0, c, style, column=len(parts))
        with self.assertRaises(ValueError):
            composer.task('中国', 40, 0, c, 'kai', column=0)

    def test_hand_traced_libraries(self):
        for style in MASTER:
            m = glyph_store.manifest(style)
            for i in range(m['count']):
                g = glyph_store.glyph_at(style, i)
                self.assertEqual(g['stats']['method'], 'hand-traced')
                for s in g['strokes']:
                    p = s['points']
                    self.assertEqual((p[0][2], p[-1][2]), (0, 0))
                    self.assertTrue(all(0 <= q[2] <= 1 and 0 < q[3] <= 1 and 0 <= q[0] <= 50 and 0 <= q[1] <= 50 for q in p))


@unittest.skipUnless(MASTER, 'no masterpiece library installed')
class StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = board_config(); cls.style = MASTER[0]
        m = glyph_store.manifest(cls.style)
        result = plan(composer.task(m['characters'], 70, 0, cls.cfg, cls.style, column=0), copy.deepcopy(cls.cfg), home(cls.cfg))
        cls.doc, cls.nodes = freeze(result, 'real')
        cls.revision = composer.revision(cls.cfg, cls.style)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        plan_store.save(self.tmp.name, self.style, 0, self.doc, self.nodes, self.revision)

    def test_round_trip(self):
        doc, nodes = plan_store.load(self.tmp.name, self.style, 0, self.cfg, self.revision)
        self.assertEqual(nodes, self.nodes); self.assertEqual(doc['config_digest'], self.doc['config_digest'])
        self.assertIsNone(plan_store.load(self.tmp.name, self.style, 1, self.cfg, self.revision))   # never saved

    def test_stale_after_calibration_or_library_change(self):
        self.assertIsNone(plan_store.load(self.tmp.name, self.style, 0, self.cfg, 'other-revision'))
        moved = copy.deepcopy(self.cfg); moved['calligraphy']['contact_z_mm'] = 250.0
        self.assertIsNone(plan_store.load(self.tmp.name, self.style, 0, moved, composer.revision(moved, self.style)))
        sped = copy.deepcopy(self.cfg); sped['execution']['web_program']['draw_speed_pct'] = 70
        self.assertIsNotNone(plan_store.load(self.tmp.name, self.style, 0, sped, self.revision))   # speed is not geometry

    def test_damaged_entry_is_not_used(self):
        folder = plan_store.entry(self.tmp.name, self.style, 0)
        (folder / 'nodes.json.gz').write_bytes(b'not gzip')
        self.assertIsNone(plan_store.load(self.tmp.name, self.style, 0, self.cfg, self.revision))
        for bad in (('../x', 0), (self.style, -1), (self.style, '0'), ('kai', 0)):
            with self.assertRaises(ValueError):
                plan_store.entry(self.tmp.name, *bad)


@unittest.skipUnless(MASTER, 'no masterpiece library installed')
class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p = patch('tcb705.accel_runtime.platform_health', return_value={'faulted': True}); p.start(); self.addCleanup(p.stop)
        profile = Path(self.tmp.name) / 'board.json'
        profile.write_text(json.dumps(board_config(), ensure_ascii=False), encoding='utf-8')
        self.w = TCBWorkbench(State(self.tmp.name), simulation=True, profile=profile)

    def run_job(self, kind, data):
        job = self.w.start(kind, data); self.w.worker.join(120)
        return self.w.jobs[job['id']]

    def test_column_job_then_execute_at_fixed_speed(self):
        job = self.run_job('masterpiece', {'style': MASTER[0], 'column': 0, 'mode': 'demo'})
        self.assertEqual(job['status'], 'DONE', job.get('detail'))
        self.assertFalse(job['result']['cached'])                 # simulation never uses the store
        self.assertIn(job['id'], self.w.plans)
        done = self.run_job('execute', {'plan_job': job['id'], 'mode': 'demo', 'confirm_physical': True, 'speed_pct': 70})
        self.assertEqual(done['status'], 'DONE', done.get('detail'))
        self.assertIsNone(self.w._fixed_speed)
        self.assertNotEqual(self.w.machine['execution']['web_program']['draw_speed_pct'], 70)   # saved speed untouched

    def test_bad_requests_and_simulation_store(self):
        self.assertEqual(self.run_job('masterpiece', {'style': 'mp_nosuch', 'column': 0})['status'], 'FAILED')
        self.assertEqual(self.run_job('masterpiece', {'style': MASTER[0], 'column': 9})['status'], 'FAILED')
        self.assertEqual(self.run_job('masterpiece_all', {})['status'], 'FAILED')
        store = self.w.masterpiece_store()
        self.assertEqual([w['style'] for w in store['works']], MASTER); self.assertFalse(store['ready'])

    def test_poem_segment_job(self):
        from calligraphy import poems
        job = self.run_job('poem_segment', {'poem_id': 'p01', 'page_index': 0, 'segment_index': 0, 'mode': 'demo'})
        self.assertEqual(job['status'], 'DONE', job.get('detail')); self.assertIn(job['id'], self.w.plans)
        self.assertEqual(poems.POEM_SIZE_MM, 70); self.assertEqual(poems.SPEED_PCT, 100)
        for bad in ({'poem_id': 'nope', 'page_index': 0, 'segment_index': 0}, {'poem_id': 'p01', 'page_index': 9, 'segment_index': 0},
                    {'poem_id': 'p01', 'page_index': 0, 'segment_index': 9}):
            self.assertEqual(self.run_job('poem_segment', bad)['status'], 'FAILED')

    def test_speed_change_refused_during_fixed_speed_run(self):
        self.w._fixed_speed = 70
        with self.assertRaisesRegex(ValueError, '固定为 70%'):
            self.w.set_speed({'speed_pct': 30})
        self.w._fixed_speed = None
        self.assertEqual(self.w.set_speed({'speed_pct': 30})['speed_pct'], 30)


@unittest.skipUnless(MASTER, 'no masterpiece library installed')
class RealModeStoreTests(unittest.TestCase):
    """Real-mode planning only reads the calibrated home joints: no controller, no motion."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p = patch('tcb705.accel_runtime.platform_health', return_value={'faulted': True}); p.start(); self.addCleanup(p.stop)
        profile = Path(self.tmp.name) / 'board.json'
        profile.write_text(json.dumps(board_config(), ensure_ascii=False), encoding='utf-8')
        self.w = TCBWorkbench(State(self.tmp.name, allow_real=True), simulation=False, profile=profile)

    def run_job(self, kind, data):
        job = self.w.start(kind, data); self.w.worker.join(1800)
        return self.w.jobs[job['id']]

    def test_saved_then_read_and_every_column_fits(self):
        first = self.run_job('masterpiece', {'style': MASTER[0], 'column': 0, 'mode': 'real'})
        self.assertEqual(first['status'], 'DONE', first.get('detail')); self.assertFalse(first['result']['cached'])
        again = self.run_job('masterpiece', {'style': MASTER[0], 'column': 0, 'mode': 'real'})
        self.assertEqual(again['status'], 'DONE', again.get('detail')); self.assertTrue(again['result']['cached'])
        self.assertEqual(self.w.plans[again['id']]['nodes'], self.w.plans[first['id']]['nodes'])
        self.assertIsNotNone(self.w.plans[again['id']]['prepared'])
        poem = [self.run_job('poem_segment', {'poem_id': 'p01', 'page_index': 0, 'segment_index': 0, 'mode': 'real'}) for _ in range(2)]
        self.assertEqual([j['status'] for j in poem], ['DONE', 'DONE'], poem[0].get('detail'))
        self.assertEqual([j['result']['cached'] for j in poem], [False, True])               # planned once, then read back
        everything = self.run_job('masterpiece_all', {'mode': 'real'})
        self.assertEqual(everything['status'], 'DONE', everything.get('detail'))
        self.assertEqual(everything['result']['reused'], 1)
        self.assertTrue(self.w.masterpiece_store()['ready'])
        # A calibration change makes every entry stale.
        c = copy.deepcopy(self.w.machine); c['calligraphy']['contact_z_mm'] = 250.0
        c['calligraphy']['calibration_binding'] = binding(c)
        self.w.configure(c)
        self.assertFalse(any(col['ready'] for w in self.w.masterpiece_store()['works'] for col in w['columns']))


if __name__ == '__main__':
    unittest.main()
