"""诗词库: library + supplement glyphs, vertical right-to-left layout, segments, workflow; no motion."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from calligraphy import poems, glyph_store
from calligraphy.presets import validate_task, BRUSH, binding
from user_gui.workflow import Workflow
from tests.test_text_calligraphy import FakePipeline

ROOT = Path(__file__).resolve().parents[1]
PAPER = dict(width_mm=260., height_mm=250.)


class LibraryTests(unittest.TestCase):
    def test_forty_quatrains_all_writable(self):
        items = poems.library()['items']
        self.assertEqual(len(items), 40)
        self.assertEqual({p['form'] for p in items}, {'五言绝句', '七言绝句'})
        for p in items:
            self.assertTrue(all(poems.has_glyph(c) for c in ''.join(p['lines'])), p['title'])

    def test_supplement_leaves_the_3500_library_alone(self):
        self.assertEqual(glyph_store.manifest('kai')['count'], 3500)
        rows, meta = poems._supplement()
        self.assertFalse(set(rows) & set(glyph_store.manifest('kai')['characters']))
        self.assertTrue(set('蓑笠琵琶茱萸') <= set(rows))
        self.assertEqual(len(poems.glyph('蓑')['strokes']), len(json.loads(rows['蓑'])['strokes']))


class LayoutTests(unittest.TestCase):
    def test_vertical_right_to_left(self):
        d = poems.layout('p01', 40, PAPER)      # 静夜思
        self.assertEqual((d['rows'], d['columns'], d['page_count']), (5, 5, 1))
        cells = d['pages'][0]
        first = [c['character'] for c in cells if c['column'] == 0]
        self.assertEqual(''.join(first), '床前明月光')
        self.assertTrue(all(a['x_mm'] > b['x_mm'] for a, b in zip(cells[::5], cells[5::5])))    # columns move left
        self.assertTrue(all(a['y_mm'] < b['y_mm'] for a, b in zip(cells[:4], cells[1:5])))     # top to bottom

    def test_sheet_counts_match_the_plan(self):
        five = next(p['id'] for p in poems.library()['items'] if p['form'] == '五言绝句')
        seven = next(p['id'] for p in poems.library()['items'] if p['form'] == '七言绝句')
        self.assertEqual(poems.sheets(five, PAPER), {'40': 1, '50': 2, '60': 3, '70': 3})
        self.assertEqual(poems.sheets(seven, PAPER), {'40': 2, '50': 2, '60': 4, '70': 4})

    def test_segments_are_whole_columns_within_budget(self):
        for p in poems.library()['items']:
            for size in poems.SIZES:
                d = poems.layout(p['id'], size, PAPER)
                for page, segs in zip(d['pages'], d['segments']):
                    self.assertEqual(sum(segs, []), [c['text_index'] for c in page])
                    for seg in segs:
                        self.assertLessEqual(len(seg), poems.SEGMENT_CHARS[size])
                        cols = {page[[c['text_index'] for c in page].index(i)]['column'] for i in seg}
                        self.assertEqual(len(seg), sum(1 for c in page if c['column'] in cols))

    def test_only_four_sizes(self):
        for bad in (45, 30, 80, '40', None):
            with self.assertRaises(ValueError):
                poems.layout('p01', bad, PAPER)

    def test_task_revalidates_and_tracks_calibration(self):
        c = FakePipeline().config; c['paper'].update(PAPER)
        t = poems.task('p20', 50, 0, 1, c)
        self.assertEqual(t['calligraphy']['schema'], poems.SCHEMA)
        validate_task(t, c)
        pts = np.asarray([p for path in t['paths'] for p in path])
        self.assertTrue((pts >= 0).all() and (pts[:, 0] <= 260).all() and (pts[:, 1] <= 250).all())
        moved = copy.deepcopy(c); moved['paper']['width_mm'] = 261.
        self.assertNotEqual(poems.revision(moved), poems.revision(c))
        self.assertIn(b'<svg', poems.preview_svg('p20', 50, c, 1))


class PoemPipeline(FakePipeline):
    def __init__(self):
        super().__init__(); self.config['paper'].update(PAPER)

    def poem_plan(self, poem_id, page, segment, cancelled, progress=None):
        poems.task(poem_id, poems.POEM_SIZE_MM, page, segment, self.config)
        self.calls.append(('poem_plan', page, segment)); return 'pp%d%d' % (page, segment), True


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.p = PoemPipeline(); self.w = Workflow(self.p, self.tmp.name)

    def finish(self):
        self.w.worker.join(20); self.assertFalse(self.w.worker.is_alive())

    def test_sheet_by_sheet_at_fixed_size_and_speed(self):
        # 2026-10-27: confirmed -> each sheet's saved (or newly planned) segments -> written at 100 %.
        seven = next(p['id'] for p in poems.library()['items'] if p['form'] == '七言绝句')
        doc = poems.layout(seven, poems.POEM_SIZE_MM, PAPER)
        s = self.w.submit_poem(seven, 'pm_request1', True); jid = s['job_id']; self.finish()
        self.assertEqual(self.w.state['font_size_mm'], 70); self.assertEqual(self.w.state['page_count'], doc['page_count'])
        for page in range(doc['page_count']):
            planned = [c for c in self.p.calls if c[0] == 'poem_plan' and c[1] == page]
            self.assertEqual(planned, [('poem_plan', page, k) for k in range(len(doc['segments'][page]))])
            if page + 1 < doc['page_count']:
                self.assertEqual(self.w.state['phase'], 'awaiting_paper')
                self.w.next_text_page(self.w._owner, jid, page); self.finish()
        self.assertEqual(self.w.state['phase'], 'completed'); self.assertEqual(self.w.state['message'], '这首诗写完了，已归位')
        writes = [c for c in self.p.calls if c[0] == 'speed']
        self.assertEqual(len(writes), sum(len(x) for x in doc['segments'])); self.assertTrue(all(c[2] == 100 for c in writes))
        self.assertFalse([c for c in self.p.calls if c[0] in ('register', 'plan')])        # no ordinary planning

    def test_invalid_requests_do_not_reserve(self):
        for pid, confirmed in (('nope', True), ('p01', False)):
            with self.assertRaises(ValueError):
                self.w.submit_poem(pid, 'pm_request2', confirmed)
        self.assertEqual(self.w.state['phase'], 'idle'); self.assertEqual(self.p.calls, [])


@unittest.skipUnless((ROOT / 'build/tcb705/tcb_core.dll').is_file() or (ROOT / 'build/tcb705/libtcb_core.so').is_file(),
                     'native seven-axis core not built')
class OfflinePlanTests(unittest.TestCase):
    """Every segment of every poem at every size plans on the controller-DH model (no motion)."""
    def test_all_poems_plan(self):
        from tcb705.calibration import apply_armvision
        from tcb705.model import Model
        from tcb705.planner import plan
        c = json.loads((ROOT / 'robots/tcb705/profile.armvision_joint.json').read_text(encoding='utf-8'))
        c.update(calibration_verified=True, sdk_mapping_verified=True)
        c = apply_armvision(c, dict(c['armvision'], a_mm=[-560., -125.], b_mm=[-310., 135.]), reset_verified=False)
        c['calligraphy'] = dict(BRUSH, max_press_mm=2., verified=True, calibration_binding=binding(c))
        model = Model(c); p = c['paper']; g = np.eye(4); g[:3, :3] = c['tool_rotation']
        g[:3, 3] = np.asarray(p['origin_m']) + (np.asarray(p['x_axis']) * p['width_mm'] / 2 +
                                                 np.asarray(p['y_axis']) * p['height_mm'] / 2) * .001 + [0, 0, .06]
        seed = np.asarray(c['q_start_rad'])
        for _ in range(4):
            r = model.solve(g, seed, seed); seed = r['q']
            if r['ok']:
                break
        self.assertTrue(r['ok'])
        for item in poems.library()['items']:
            for size in poems.SIZES:
                d = poems.layout(item['id'], size, c['paper'])
                for page, segs in enumerate(d['segments']):
                    for segment in range(len(segs)):
                        with self.subTest(poem=item['title'], size=size, page=page, segment=segment):
                            plan(poems.task(item['id'], size, page, segment, c), c, q_start=r['q'])


if __name__ == '__main__':
    unittest.main()
