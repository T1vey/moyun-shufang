"""手机硬笔 (2026-10-29): several lines, 横排 / 竖排, pages, saved per line, phone and screen flows (no motion)."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import State
from calligraphy import hardpen
from calligraphy.presets import validate_task
from user_gui.workflow import Workflow
from tests.test_hardpen_tool import pen_config
from tests.test_text_calligraphy import FakePipeline

PAPER = dict(width_mm=260., height_mm=250.)
POEM = '床前明月光，疑是地上霜。\n举头望明月，低头思故乡。'


@unittest.skipUnless(hardpen.DB.exists(), 'hard-pen library not built')
class LayoutTests(unittest.TestCase):
    def test_rows_left_to_right_top_down(self):
        d = hardpen.doc_layout(POEM, 10, 'h', PAPER)
        self.assertEqual([l['text'] for l in d['lines']], ['床前明月光 疑是地上霜', '举头望明月 低头思故乡'])
        self.assertEqual(d['characters'], 20); self.assertEqual(d['page_count'], 1); self.assertEqual(d['per_line'], 20)
        a, b = d['lines']
        self.assertEqual([c['character'] for c in a['cells']][5], '疑')                   # the comma is a blank cell
        self.assertAlmostEqual(a['cells'][5]['x_mm'] - a['cells'][4]['x_mm'], 24.)
        self.assertTrue(all(q['x_mm'] > p['x_mm'] for p, q in zip(a['cells'], a['cells'][1:])))
        self.assertAlmostEqual(b['cells'][0]['y_mm'] - a['cells'][0]['y_mm'], 16.)
        self.assertEqual(b['cells'][0]['text_index'], 10)

    def test_columns_top_down_right_to_left(self):
        d = hardpen.doc_layout(POEM, 20, 'v', PAPER)
        self.assertEqual([l['text'] for l in d['lines']], ['床前明月光 疑是地', '上霜', '举头望明月 低头思', '故乡'])
        first, second = d['lines'][0]['cells'], d['lines'][1]['cells']
        self.assertTrue(all(q['y_mm'] > p['y_mm'] and q['x_mm'] == p['x_mm'] for p, q in zip(first, first[1:])))
        self.assertGreater(first[0]['x_mm'], second[0]['x_mm'])                          # next column on the left
        self.assertEqual(second[0]['y_mm'], first[0]['y_mm'])

    def test_pages_and_limits(self):
        d = hardpen.doc_layout('\n'.join('永' * 3 for _ in range(9)), 20, 'h', PAPER)
        self.assertEqual(d['per_page'], 7); self.assertEqual(d['page_count'], 2); self.assertEqual(d['pages'][1], [7, 8])
        d = hardpen.doc_layout('永\n\n\n永', 15, 'h', PAPER)
        self.assertEqual(d['line_count'], 4)                                                    # blank lines kept, not planned
        self.assertEqual([(u['line'], len(u['cells'])) for u in d['units']], [(0, 1), (3, 1)])
        for bad in (('', 10, 'h'), ('，。', 10, 'h'), ('永' * 301, 10, 'h'), ('永A', 10, 'h'), ('永', 12, 'h'), ('永', 10, 'x')):
            with self.assertRaises(ValueError, msg=bad):
                hardpen.doc_layout(bad[0], bad[1], bad[2], PAPER)
        with self.assertRaisesRegex(ValueError, '最多'):
            hardpen.doc_layout('\n'.join('永' for _ in range(100)), 10, 'h', PAPER)
        self.assertEqual(hardpen.normalize_doc('\n 永，\r\n'), ' 永')                       # an indent is kept
        self.assertEqual(hardpen.doc_key('永', 10, 'h'), hardpen.doc_key(hardpen.normalize_doc('永。\r\n'), 10, 'h'))
        self.assertNotEqual(hardpen.doc_key('永', 10, 'h'), hardpen.doc_key('永', 10, 'v'))
        self.assertRegex(hardpen.doc_key('永', 10, 'h'), r'^hp_[a-z0-9_]{1,40}$')

    def test_units_stay_inside_the_node_budget(self):
        # A full line of complex characters is cut into units of consecutive characters.
        heavy = sorted(hardpen.manifest()['characters'], key=lambda ch: -hardpen.char_cost(ch, 10))
        d = hardpen.doc_layout(''.join(heavy[:20]), 10, 'h', PAPER)
        self.assertEqual(d['line_count'], 1); self.assertGreater(d['unit_count'], 1)
        self.assertEqual([c['text_index'] for u in d['units'] for c in u['cells']], list(range(20)))
        for u in d['units']:
            self.assertLessEqual(sum(hardpen.char_cost(c['character'], 10) for c in u['cells']), hardpen.UNIT_NODES)
        self.assertEqual(hardpen.doc_layout('永' * 5, 10, 'h', PAPER)['unit_count'], 1)
        with self.assertRaisesRegex(ValueError, '内容太多'):
            hardpen.doc_layout(''.join(heavy[:300]), 20, 'h', PAPER)

    def test_unit_task_is_rebuilt_on_the_server(self):
        c = pen_config()
        d = hardpen.doc_layout(POEM, 15, 'v', c['paper'])
        t = hardpen.unit_task(POEM, 15, 'v', 1, c)
        m = t['calligraphy']
        self.assertEqual((m['schema'], m['unit_index'], m['layout'], m['revision']), ('hardpen-doc-v1', 1, 'v', hardpen.revision(c)))
        self.assertEqual([x['character'] for x in m['stroke_map'] if x['stroke_index'] == 0], [x['character'] for x in d['units'][1]['cells']])
        validate_task(t, c)
        bad = copy.deepcopy(t); bad['paths'][0][0][0] += 1
        with self.assertRaises(ValueError):
            validate_task(bad, c)
        with self.assertRaises(ValueError):
            hardpen.unit_task(POEM, 15, 'v', d['unit_count'], c)
        page = hardpen.doc_preview_svg(POEM, 15, 'h', c, 0)
        self.assertTrue(page.startswith(b'<svg') and b'<polyline' in page)


class DocPipeline(FakePipeline):
    def __init__(self):
        super().__init__(); self.config = pen_config()

    def hardpen_doc_plan(self, text, size_mm, layout, unit_index, cancelled, progress=None):
        hardpen.unit_task(text, size_mm, layout, unit_index, self.config)
        self.calls.append(('doc_plan', unit_index)); return 'hd%d' % unit_index, False

    def hardpen_works(self):
        return []


@unittest.skipUnless(hardpen.DB.exists(), 'hard-pen library not built')
class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.p = DocPipeline(); self.w = Workflow(self.p, self.tmp.name)

    def finish(self):
        self.w.worker.join(20); self.assertFalse(self.w.worker.is_alive())

    def test_phone_piece_page_by_page_at_the_chosen_speed(self):
        text = '\n'.join(['春眠不觉晓', '处处闻啼鸟', '夜来风雨声', '花落知多少', '', '永', '永', '永'])   # 8 lines, 2 pages at 2 cm
        doc = self.w.hardpen_preview('phone01', text, 20, 'h')
        self.assertEqual(doc['page_count'], 2); self.assertFalse(doc['saved']); self.assertEqual(self.p.calls, [])
        base = dict(text=text, font_size_mm=20, layout='h', speed_pct=70, preview_id=doc['preview_id'], revision=doc['revision'],
                    request_id='hp_req_0001', start_requested=True)
        for bad in (dict(start_requested=False), dict(speed_pct=60), dict(layout='v'), dict(font_size_mm=15), dict(preview_id='nope')):
            with self.assertRaises(ValueError, msg=bad):
                self.w.submit_hardpen_text('phone01', dict(base, **bad))
        s = self.w.submit_hardpen_text('phone01', base); jid = s['job_id']; self.finish()
        units = hardpen.doc_layout(text, 20, 'h', self.p.config['paper'])['page_units']
        self.assertGreater(len(units[0]), 3)
        # Every unit of the page planned and saved first; then each read back just before it is written.
        expected = [('doc_plan', u) for u in units[0]]
        for u in units[0]:
            expected += [('doc_plan', u), ('execute',), ('speed', 'hd%d' % u, 70)]
        self.assertEqual(self.p.calls, expected)
        st = self.w.text_status('phone01', jid)
        self.assertEqual((st['phase'], st['page_index'], st['page_count']), ('awaiting_paper', 0, 2))
        self.assertIn(b'<polyline', self.w.preview(jid))
        self.assertEqual(self.w.submit_hardpen_text('phone01', base)['job_id'], jid)            # a retried submit does not start again
        self.w.next_text_page('phone01', jid, 0); self.finish()
        u = units[1]                                                                        # up to three units: planned once
        self.assertEqual(self.p.calls[-3 * len(u):], [('doc_plan', x) for x in u] + sum([[('execute',), ('speed', 'hd%d' % x, 70)] for x in u], []))
        self.assertEqual(self.w.text_status('phone01', jid)['phase'], 'completed')
        self.assertEqual(self.w.state['message'], '硬笔作品写完了，已归位')

    def test_brush_mounted_is_refused_before_reserving(self):
        self.p.config['mounted_tool'] = 'brush'
        doc = self.w.hardpen_preview('phone02', '永', 10, 'v')
        with self.assertRaisesRegex(ValueError, '切换为硬笔'):
            self.w.submit_hardpen_text('phone02', dict(text='永', font_size_mm=10, layout='v', speed_pct=85, preview_id=doc['preview_id'],
                                                       revision=doc['revision'], request_id='hp_req_0002', start_requested=True))
        self.assertEqual(self.w.state['phase'], 'idle'); self.assertEqual(self.p.calls, [])

    def test_screen_writes_a_saved_piece_again(self):
        with self.assertRaises(ValueError):
            self.w.submit_hardpen_doc('永', 10, 'v', 85, 'hpd_000001')                      # not confirmed
        self.w.submit_hardpen_doc('永 书', 10, 'v', 100, 'hpd_000002', True); self.finish()
        self.assertEqual(self.p.calls, [('doc_plan', 0), ('execute',), ('speed', 'hd0', 100)])
        self.assertEqual((self.w.state['module'], self.w.state['phase']), ('hardpen', 'completed'))


@unittest.skipUnless(hardpen.DB.exists(), 'hard-pen library not built')
class SavedDocTests(unittest.TestCase):
    """Real-mode planning only reads the calibrated home joints: no controller, no motion."""
    def setUp(self):
        from tcb705.workbench import TCBWorkbench
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p = patch('tcb705.accel_runtime.platform_health', return_value={'faulted': True}); p.start(); self.addCleanup(p.stop)
        profile = Path(self.tmp.name) / 'board.json'
        c = pen_config(contact=219.3); c['mounted_tool'] = 'pen'
        profile.write_text(json.dumps(c, ensure_ascii=False), encoding='utf-8')
        self.w = TCBWorkbench(State(self.tmp.name, allow_real=True), simulation=False, profile=profile)

    def run_job(self, data):
        job = self.w.start('hardpen_doc', dict(data, mode='real')); self.w.worker.join(600)
        return self.w.jobs[job['id']]

    def test_lines_saved_once_then_read_back(self):
        piece = dict(text='永和\n九年', font_size_mm=15, layout='v')
        first = [self.run_job(dict(piece, unit_index=i)) for i in (0, 1)]
        for j in first:
            self.assertEqual(j['status'], 'DONE', j.get('detail')); self.assertFalse(j['result']['cached'])
        again = self.run_job(dict(piece, unit_index=1))
        self.assertTrue(again['result']['cached'])
        self.assertEqual(self.w.plans[again['id']]['nodes'], self.w.plans[first[1]['id']]['nodes'])
        self.assertEqual(self.run_job(dict(piece, unit_index=2))['status'], 'FAILED')        # no such unit
        works = self.w.hardpen_works()['works']
        self.assertEqual([(w['text'], w['layout'], w['line_count'], w['page_count'], w['ready']) for w in works],
                         [('永和\n九年', 'v', 2, 1, True)])


if __name__ == '__main__':
    unittest.main()
