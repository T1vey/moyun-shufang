"""春联模式: library, 70 mm lines (one row each) across 名帖 sheets, rotation and the workflow; no motion."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from calligraphy import couplets, glyph_store
from calligraphy.presets import validate_task, BRUSH, binding
from tcb705.calibration import apply_armvision, check_consistency, couplet_frame
from user_gui.workflow import Workflow
from tests.test_text_calligraphy import FakePipeline, config as text_config

ROOT = Path(__file__).resolve().parents[1]
TABLE = dict(origin_m=[-.244, -.31, .2193], x_axis=[0, 1, 0], y_axis=[-1, 0, 0], width_mm=620., height_mm=240.)
PAPER = dict(origin_m=[-.309498, -.123594, .2193], x_axis=[0, 1, 0], y_axis=[-1, 0, 0], width_mm=260., height_mm=250.)


def config():
    """The 名帖 paper size (260 x 250 mm); couplets are written on the paper since 2026-10-29."""
    c = text_config(); c['paper'] = copy.deepcopy(PAPER)
    return c


class LibraryTests(unittest.TestCase):
    def test_every_couplet_is_writable(self):
        items = couplets.catalog(); known = set(glyph_store.manifest('kai')['characters'])
        self.assertGreaterEqual(len(items), 20)
        self.assertEqual(len({c['id'] for c in items}), len(items))
        for c in items:
            self.assertEqual(len(c['upper']), len(c['lower']), c['id'])
            self.assertEqual(len(c['banner']), 4, c['id'])
            self.assertIn(c['chars'], (4, 5, 7))
            self.assertTrue(set(c['upper'] + c['lower'] + c['banner']) <= known, c['id'])


class LayoutTests(unittest.TestCase):
    def test_one_row_per_line_across_sheets(self):
        # 2026-10-29: 70 mm like 名帖; 上联 bottom row, 下联 middle, 横批 top; three characters of
        # each line per sheet, the line continuing on the same row of the next sheet.
        d = couplets.layout('c01', PAPER)
        self.assertEqual(d['font_size_mm'], 70.); self.assertEqual(d['sheet_count'], 3)
        self.assertEqual(d['sheets'], [[0, 1, 2], [3, 4, 5], [6, 7]])
        rows = [''.join(c['character'] for c in p) for p in d['pages']]
        self.assertEqual(rows, ['天增岁', '春满乾', '福满人', '月人增', '坤福满', '间', '寿', '门'])
        for part, text in (('upper', '天增岁月人增寿'), ('lower', '春满乾坤福满门'), ('banner', '福满人间')):
            cells = [c for p in d['pages'] for c in p if c['part'] == part]
            self.assertEqual(''.join(c['character'] for c in cells), text)
            self.assertEqual(len({c['row'] for c in cells}), 1)                    # one row per line
        first = d['pages'][0]; second = d['pages'][1]; third = d['pages'][2]
        self.assertGreater(first[0]['y_mm'], second[0]['y_mm']); self.assertGreater(second[0]['y_mm'], third[0]['y_mm'])
        self.assertTrue(all(b['x_mm'] - a['x_mm'] == 80.5 for a, b in zip(first, first[1:])))   # left to right
        self.assertAlmostEqual(first[0]['x_mm'] * 2 + 3 * 70 + 2 * 10.5, 260)                  # centred
        self.assertEqual({c['rotate'] for p in d['pages'] for c in p}, {'ccw90'})
        self.assertEqual(d['pages'][3][0]['y_mm'], first[0]['y_mm'])          # 上联 stays on the bottom row
        self.assertEqual(d['pages'][3][0]['x_mm'], first[0]['x_mm'])          # and starts at the left again
        self.assertEqual(couplets.layout('c18', PAPER)['sheet_count'], 2)
        self.assertEqual([len(p) for p in couplets.layout('c24', PAPER)['pages']], [3, 3, 3, 1, 1, 1])
        self.assertEqual(couplets.needed_mm(), (251., 244.))

    def test_paper_too_small_names_the_problem(self):
        with self.assertRaisesRegex(ValueError, '251×244'):
            couplets.layout('c01', dict(PAPER, width_mm=240.))

    def test_rotation(self):
        self.assertEqual(couplets.rotated([[25., 0., .5, 1.]], 'ccw90'), [[0., 25., .5, 1.]])   # top -> left
        self.assertEqual(couplets.rotated([[25., 50., 0., 1.]], 'ccw90'), [[50., 25., 0., 1.]])
        self.assertEqual(couplets.rotated([[25., 0., .5, 1.]], 'cw90'), [[50., 25., .5, 1.]])
        self.assertEqual(couplets.rotated([[1., 2., 0., 1.]], 'none'), [[1., 2., 0., 1.]])

    def test_task_stays_on_table_and_revalidates(self):
        c = config()
        for page in range(3):
            t = couplets.task('c17', page, c)
            self.assertEqual(t['calligraphy']['schema'], couplets.SCHEMA)
            pts = np.asarray([p for path in t['paths'] for p in path])
            self.assertTrue((pts >= 0).all() and (pts[:, 0] <= 260).all() and (pts[:, 1] <= 250).all())
            self.assertEqual(t['calligraphy']['font_size_mm'], 70.)
            validate_task(t, c)
        t = couplets.task('c17', 0, c); bad = copy.deepcopy(t); bad['paths'][0][0][0] += .5
        with self.assertRaises(ValueError):
            validate_task(bad, c)
        moved = copy.deepcopy(c); moved['paper']['width_mm'] = 261.
        self.assertNotEqual(couplets.revision(moved), couplets.revision(c))
        with self.assertRaises(ValueError):
            validate_task(t, moved)

    def test_couplets_use_the_paper(self):
        c = config(); c['couplet_paper'] = copy.deepcopy(TABLE)              # a former table is ignored
        self.assertIs(couplets.surface(c, dict(schema='brush-text-v1')), c['paper'])
        self.assertIs(couplets.surface(c, dict(schema=couplets.SCHEMA)), c['paper'])

    def test_preview_svg(self):
        svg = couplets.preview_svg('c24', config(), 0).decode()
        self.assertTrue(svg.startswith('<svg') and svg.count('#c8372b') == 3)     # three rows on sheet 1
        self.assertEqual(couplets.preview_svg('c01', config(), 2).decode().count('#c8372b'), 2)   # 寿, 门


class TableCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.c = json.loads((ROOT / 'robots/tcb705/profile.armvision_joint.json').read_text(encoding='utf-8'))

    def test_table_shares_plane_and_allows_long_spans(self):
        c = dict(self.c, couplet_table=dict(a_mm=[-484., -310.], b_mm=[-244., 310.]))
        c = apply_armvision(c, c['armvision'], reset_verified=False)
        p = c['couplet_paper']
        self.assertEqual((p['width_mm'], p['height_mm']), (620., 240.))
        self.assertAlmostEqual(p['origin_m'][2], c['paper']['origin_m'][2])
        self.assertEqual((p['x_axis'], p['y_axis']), (c['paper']['x_axis'], c['paper']['y_axis']))
        check_consistency(c)
        c['couplet_paper']['width_mm'] = 600.
        with self.assertRaises(ValueError):
            check_consistency(c)
        with self.assertRaises(ValueError):
            couplet_frame(c['armvision'], dict(a_mm=[0, 0], b_mm=[700, 200]))

    def test_removing_the_table_removes_its_frame(self):
        c = dict(self.c, couplet_table=dict(a_mm=[-484., -310.], b_mm=[-244., 310.]))
        c = apply_armvision(c, c['armvision'], reset_verified=False)
        c.pop('couplet_table')
        self.assertNotIn('couplet_paper', apply_armvision(c, c['armvision'], reset_verified=False))


class CoupletPipeline(FakePipeline):
    def __init__(self):
        super().__init__(); self.config['paper'] = copy.deepcopy(PAPER)

    def couplet_plan(self, couplet_id, page_index, cancelled, progress=None):
        couplets.task(couplet_id, page_index, self.config)
        self.calls.append(('couplet_plan', page_index)); return 'cp%d' % page_index, page_index == 0


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.p = CoupletPipeline(); self.w = Workflow(self.p, self.tmp.name)

    def finish(self):
        self.w.worker.join(20); self.assertFalse(self.w.worker.is_alive())

    def test_two_sheets_with_a_paper_change(self):
        # 2026-10-29: confirmed on screen, saved rows, written at once at a fixed 100 %.
        with self.assertRaises(ValueError):
            self.w.submit_couplet('c01', 'cp_request0')
        self.assertEqual(self.p.calls, [])
        s = self.w.submit_couplet('c01', 'cp_request1', True); jid = s['job_id']; self.finish()
        self.assertEqual(self.w.state['module'], 'couplet')
        self.assertEqual(self.p.calls, [('couplet_plan', 0), ('couplet_plan', 1), ('couplet_plan', 2),
                                        ('execute',), ('speed', 'cp0', 100), ('execute',), ('speed', 'cp1', 100),
                                        ('execute',), ('speed', 'cp2', 100)])
        self.assertIn(b'#c8372b', self.w.preview(jid))
        self.assertEqual(self.w.state['phase'], 'awaiting_paper'); self.assertEqual(self.w.state['page_count'], 3)
        self.w.next_text_page(self.w._owner, jid, 0); self.finish()                 # sheet 1 done, paper changed
        self.assertEqual(self.p.calls[-9:], [('couplet_plan', 3), ('couplet_plan', 4), ('couplet_plan', 5),
                                             ('execute',), ('speed', 'cp3', 100), ('execute',), ('speed', 'cp4', 100),
                                             ('execute',), ('speed', 'cp5', 100)])
        self.assertEqual(self.w.state['phase'], 'awaiting_paper')
        self.w.next_text_page(self.w._owner, jid, 1); self.finish()
        self.assertEqual(self.p.calls[-6:], [('couplet_plan', 6), ('couplet_plan', 7),
                                             ('execute',), ('speed', 'cp6', 100), ('execute',), ('speed', 'cp7', 100)])
        self.assertEqual(self.w.state['phase'], 'completed')
        self.assertEqual(self.w.state['message'], '春联书写完成，已归位')

    def test_small_paper_is_rejected_before_reserving(self):
        self.p.config['paper']['width_mm'] = 240.
        with self.assertRaisesRegex(ValueError, '251×244'):
            self.w.submit_couplet('c01', 'cp_request2', True)
        self.assertEqual(self.w.state['phase'], 'idle'); self.assertEqual(self.p.calls, [])
        with self.assertRaises(ValueError):
            self.w.submit_couplet('nope', 'cp_request3', True)


@unittest.skipUnless((ROOT / 'build/tcb705/tcb_core.dll').is_file() or (ROOT / 'build/tcb705/libtcb_core.so').is_file(),
                     'native seven-axis core not built')
class OfflinePlanTests(unittest.TestCase):
    """Every page of every couplet plans on the controller-DH model (pen vertical, no motion)."""
    def test_all_couplets_plan(self):
        from tcb705.model import Model
        from tcb705.planner import plan
        c = json.loads((ROOT / 'robots/tcb705/profile.armvision_joint.json').read_text(encoding='utf-8'))
        c.update(calibration_verified=True, sdk_mapping_verified=True)
        # The board's 名帖 paper (2026-10-29): 260 x 250 mm.
        c['armvision'] = dict(c['armvision'], a_mm=[-559.498, -123.594], b_mm=[-309.498, 136.406])
        c = apply_armvision(c, c['armvision'], reset_verified=False)
        c['calligraphy'] = dict(BRUSH, max_press_mm=2., verified=True, calibration_binding=binding(c))
        model = Model(c)
        p = c['paper']; g = np.eye(4); g[:3, :3] = c['tool_rotation']
        g[:3, 3] = np.asarray(p['origin_m']) + (np.asarray(p['x_axis']) * p['width_mm'] / 2 +
                                                 np.asarray(p['y_axis']) * p['height_mm'] / 2) * .001 + [0, 0, .06]
        seed = np.asarray(c['q_start_rad'])
        for _ in range(4):
            r = model.solve(g, seed, seed); seed = r['q']
            if r['ok']:
                break
        self.assertTrue(r['ok'])
        for item in couplets.catalog():
            for page in range(couplets.layout(item['id'], c['paper'])['page_count']):
                with self.subTest(couplet=item['id'], page=page):
                    plan(couplets.task(item['id'], page, c), c, q_start=r['q'])


if __name__ == '__main__':
    unittest.main()
