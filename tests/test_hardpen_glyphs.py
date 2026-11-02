"""硬笔正楷 library (tools/build_hardpen_glyphs.py): format, pen rules, stroke families."""
import json
import sqlite3
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/calligraphy/hardpen/glyphs.sqlite'
sys.path.insert(0, str(ROOT / 'tools'))


def library():
    with sqlite3.connect(DB.resolve().as_uri() + '?mode=ro', uri=True) as con:
        rows = dict(con.execute('SELECT character, payload FROM glyphs').fetchall())
        meta = json.loads(con.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
    return {k: json.loads(v) for k, v in rows.items()}, meta


@unittest.skipUnless(DB.exists(), 'hard-pen library not built')
class LibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.glyphs, cls.meta = library()

    def test_manifest_and_test_set(self):
        import build_hardpen_glyphs as B
        self.assertEqual(self.meta['schema'], 'brush-glyphs-v1'); self.assertEqual(self.meta['style'], 'hardpen')
        self.assertEqual(self.meta['count'], len(self.glyphs))
        self.assertTrue(set(B.TEST100) <= set(self.glyphs)); self.assertEqual(len(set(B.TEST100)), 100)

    def test_every_stroke_is_a_valid_pen_curve(self):
        from calligraphy.curves import BrushCurve
        for ch, g in self.glyphs.items():
            for i, s in enumerate(g['strokes']):
                with self.subTest(char=ch, stroke=i + 1):
                    p = np.asarray(s['points'])
                    self.assertEqual((p[0, 2], p[-1, 2]), (0, 0))                 # lands and lifts
                    self.assertTrue(((p[:, :2] >= 0) & (p[:, :2] <= 50)).all())
                    self.assertTrue(((p[:, 2] <= 1) & (p[:, 3] > 0) & (p[:, 3] <= 1)).all())
                    self.assertGreater(len(BrushCurve(s['points']).sample(15 / 50.)), 1)   # 1.5 cm

    def test_horizontals_rise_and_verticals_stay_upright(self):
        yi = np.asarray(self.glyphs['一']['strokes'][0]['points'])
        self.assertLess(yi[-2, 1], yi[1, 1])                                        # 横: right end higher
        rise = np.degrees(np.arctan2(yi[1, 1] - yi[-2, 1], yi[-2, 0] - yi[1, 0]))
        self.assertTrue(1.0 < rise < 8.0, rise)
        shu = np.asarray(self.glyphs['十']['strokes'][1]['points'])
        self.assertLess(abs(shu[-1, 0] - shu[1, 0]), 1.0)                            # 竖: still vertical

    def test_stroke_families_and_endings(self):
        kinds = lambda ch: [s['kind'] for s in self.glyphs[ch]['strokes']]
        self.assertEqual(kinds('一'), ['横']); self.assertEqual(kinds('十'), ['横', '悬针竖'])
        self.assertEqual(kinds('口'), ['竖', '横折', '横']); self.assertEqual(kinds('人'), ['撇', '捺'])
        self.assertEqual(kinds('田'), ['竖', '横折', '横', '竖', '横'])
        self.assertEqual(kinds('小')[0], '竖钩'); self.assertEqual(kinds('门')[-1], '横钩')
        for g in self.glyphs.values():
            for s in g['strokes']:
                tail = np.asarray(s['points'])[-3:]
                if s['ending'] == 'stop':      # pressed to the end, then lifted on the spot
                    self.assertGreater(tail[-2, 2], 0.5); self.assertLess(np.hypot(*(tail[-1, :2] - tail[-2, :2])), 1e-6)
                else:                          # lifts while still moving: a sharp tail
                    self.assertLess(tail[-2, 2], 0.8)                                  # already lifting
                    self.assertGreater(np.hypot(*(tail[-1, :2] - tail[-2, :2])), 0.05)


@unittest.skipUnless(DB.exists(), 'hard-pen library not built')
class SourceTests(unittest.TestCase):
    def test_stroke_count_and_order_follow_the_source(self):
        import build_hardpen_glyphs as B
        if not B.GRAPHICS.exists():
            self.skipTest('makemeahanzi source not on this machine')
        glyphs, _ = library()
        items = B.load(B.TEST100)
        for ch in B.TEST100:
            src = [B.to_cell(m) for m in items[ch]['medians']]
            self.assertEqual(len(glyphs[ch]['strokes']), len(src), ch)
            for s, m in zip(glyphs[ch]['strokes'], src):        # same direction as the standard stroke
                p = np.asarray(s['points'])[:, :2]
                self.assertGreater(np.dot(p[-1] - p[0], m[-1] - m[0]), 0, ch)


if __name__ == '__main__':
    unittest.main()
