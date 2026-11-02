"""趣味测验: question bank tied to the encyclopedia, generated rounds, read-only."""
import re
import unittest
from pathlib import Path

from user_gui import quiz, encyclopedia

ROOT = Path(__file__).resolve().parents[1]


class BankTests(unittest.TestCase):
    def test_answers_come_from_the_encyclopedia(self):
        doc = encyclopedia.content()
        text = {c['id'] + '/' + e['id']: e['title'] + ''.join(s['text'] for s in e['screens'])
                for c in doc['categories'] for e in c['entries']}
        items = quiz.bank()['items']
        self.assertGreaterEqual(len(items), 40)
        self.assertEqual(len({k['id'] for k in items}), len(items))
        for k in items:
            with self.subTest(question=k['question']):
                self.assertEqual(len(set(k['options'])), 4)
                self.assertIn(k['entry'], text)
                self.assertIn(k['options'][k['answer']], text[k['entry']])


class RoundTests(unittest.TestCase):
    def test_many_rounds_are_well_formed(self):
        entries = {c['id'] + '/' + e['id'] for c in encyclopedia.content()['categories'] for e in c['entries']}
        prompts = set()
        for seed in range(300):
            r = quiz.round_(seed)
            self.assertEqual(len(r['questions']), 10)
            for q in r['questions']:
                self.assertEqual(len(q['options']), 4); self.assertEqual(len(set(q['options'])), 4)
                self.assertIn(q['answer'], range(4))
                self.assertTrue(q['entry'] is None or q['entry'] in entries, q['entry'])
                if q['figure']:
                    self.assertTrue(q['figure']['glyphs'] and all(q['figure']['glyphs']))
                prompts.add(re.sub('「.*」', '「」', q['prompt']))
        for kind in ('这个字是什么书体？', '「」的下一句是？', '「」是哪位诗人的诗句？', '上联「」，下联是哪一句？'):
            self.assertIn(kind, prompts)

    def test_style_question_answer_matches_its_glyph(self):
        from calligraphy import glyph_store
        for seed in range(50):
            import random
            q = quiz.style_question(random.Random(seed))
            label = q['options'][q['answer']]
            style = next(s for s, v in quiz.STYLES.items() if v == label)
            ch = re.search('「(.)」', q['explain']).group(1)
            self.assertEqual(q['figure']['glyphs'][0], quiz._keyframes(glyph_store.glyph(ch, style)))

    def test_never_touches_the_arm(self):
        source = (ROOT / 'user_gui/quiz.py').read_text(encoding='utf-8') + (ROOT / 'user_gui/static/quiz.js').read_text(encoding='utf-8')
        for word in ('tcb705', 'workflow', '/api/workflow', 'execute', 'plan('):
            self.assertNotIn(word, source)


if __name__ == '__main__':
    unittest.main()
