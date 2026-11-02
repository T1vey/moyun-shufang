"""书法百科: read-only content, screen limits and figure glyphs; no motion anywhere."""
import unittest

from calligraphy import glyph_store
from user_gui import encyclopedia


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.doc = encyclopedia.content()
        self.entries = [e for c in self.doc['categories'] for e in c['entries']]

    def test_structure_and_screen_limits(self):
        self.assertEqual(len(self.doc['categories']), 8)
        self.assertGreaterEqual(len(self.entries), 80)
        ids = [(c['id'], e['id']) for c in self.doc['categories'] for e in c['entries']]
        self.assertEqual(len(ids), len(set(ids)))
        for c in self.doc['categories']:
            self.assertEqual(len(c['seal']), 1)
        for e in self.entries:
            self.assertTrue(2 <= len(e['screens']) <= 4, e['title'])
            self.assertEqual(len(e['seal']), 1, e['title'])
            for s in e['screens']:
                self.assertTrue(70 <= len(s['text']) <= encyclopedia.MAX_SCREEN_CHARS, (e['title'], len(s['text'])))
                self.assertIn('figure', s, e['title'])                     # every screen has a picture

    def test_pure_reading_material(self):
        # The encyclopedia is popular-science text only: it never mentions or drives the arm.
        for e in self.entries:
            text = e['title'] + ''.join(s['text'] for s in e['screens'])
            for word in ('机械臂', '机器人', '本机', '演示'):
                self.assertNotIn(word, text, e['title'])
            self.assertFalse(set(e) - {'id', 'title', 'seal', 'screens'}, e['title'])
            for s in e['screens']:
                self.assertFalse(set(s) - {'text', 'figure'}, e['title'])

    def test_every_figure_can_be_drawn(self):
        for e, f in ((e, s['figure']) for e in self.entries for s in e['screens']):
            with self.subTest(entry=e['title'], figure=f):
                if f['type'] in ('grid', 'order'):
                    self.assertEqual(encyclopedia.glyphs(f.get('style', 'kai'), f['char'])['chars'], f['char'])
                elif f['type'] == 'column':
                    self.assertTrue(len(f['chars']) <= 10)
                    self.assertEqual(encyclopedia.glyphs('kai', f['chars'] + '印')['chars'], f['chars'] + '印')
                elif f['type'] == 'couplet':
                    text = f['upper'] + f['lower'] + f['banner']
                    self.assertEqual(len(f['upper']), len(f['lower'])); self.assertEqual(len(f['banner']), 4)
                    self.assertEqual(encyclopedia.glyphs('kai', text)['chars'], text)
                elif f['type'] == 'stroke':
                    self.assertEqual(len(encyclopedia.strokes(','.join(f['modules']))['strokes']), len(f['modules']))
                elif f['type'] == 'timeline':
                    self.assertTrue(set([f['era']] if isinstance(f['era'], str) else f['era']) <= set(encyclopedia.ERAS))
                elif f['type'] == 'seals':
                    self.assertTrue(2 <= len(f['chars']) <= 3)
                    self.assertEqual(encyclopedia.glyphs('kai', f['chars'])['chars'], f['chars'])
                elif f['type'] == 'tool':
                    self.assertIn(f['item'], encyclopedia.TOOLS)
                elif f['type'] == 'styles':
                    self.assertGreaterEqual(len(encyclopedia.styles_of(f['char'])), 3)
                elif f['type'] == 'masterpiece':
                    d = encyclopedia.glyphs(f['style'])
                    self.assertEqual(len(d['glyphs']), len(d['chars']))
                else:
                    self.assertEqual(f['type'], 'glyph')
                    d = encyclopedia.glyphs(f['style'], f['chars'])
                    self.assertEqual(d['chars'], f['chars'])       # every figure character exists in that style
                    self.assertTrue(all(d['glyphs']))

    def test_glyph_requests_are_validated(self):
        for style, chars in (('kai', ''), ('kai', '一' * 21), ('nope', '一'), ('mp_nothing', '')):
            with self.assertRaises(ValueError):
                encyclopedia.glyphs(style, chars)
        self.assertEqual(encyclopedia.glyphs('kai', '永𠀀')['chars'], '永')   # unknown characters are skipped
        self.assertEqual(encyclopedia.styles_of('山'), ['kai', 'xing', 'cao', 'li', 'zhuan'])
        with self.assertRaises(ValueError):
            encyclopedia.strokes('heng,nope')

    def test_masterpiece_figures_match_library(self):
        used = {s['figure']['style'] for e in self.entries for s in e['screens'] if s['figure']['type'] == 'masterpiece'}
        self.assertTrue(used <= set(glyph_store.masterpieces()))


if __name__ == '__main__':
    unittest.main()
