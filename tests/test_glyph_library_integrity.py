"""Reject inconsistent libraries, and keep runtime glyph memory bounded."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from calligraphy import glyph_store
from calligraphy.text_layout import normalize


class LibraryIntegrityTests(unittest.TestCase):
    def test_new_common_characters_and_missing_character(self):
        text='机械臂智能科技书法程序控制墨韵春江花月夜'
        self.assertEqual(normalize(text),text)
        with self.assertRaisesRegex(ValueError,'3500.*龘'):
            normalize('龘')

    def test_runtime_cache_stays_bounded(self):
        glyph_store._glyph.cache_clear()
        for ch in glyph_store.manifest()['characters'][:180]:glyph_store.glyph(ch)
        self.assertEqual(glyph_store._glyph.cache_info().currsize,128)

    def test_corrupt_manifest_or_missing_database_row_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'bad.sqlite'
            with closing(sqlite3.connect(db)) as c, c:
                c.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)')
                c.execute('CREATE TABLE glyphs(character TEXT PRIMARY KEY,payload TEXT)')
                c.execute('INSERT INTO glyphs VALUES (?,?)',('一','{}'))
            for count,chars in [(2,'一二'),(2,'一一'),(True,'一'),(3500,'一')]:
                with closing(sqlite3.connect(db)) as c, c:
                    c.execute('DELETE FROM metadata')
                    c.execute('INSERT INTO metadata VALUES (?,?)',('manifest',json.dumps(dict(schema='brush-glyphs-v1',count=count,characters=chars))))
                glyph_store._manifest.cache_clear()
                try:
                    with patch.object(glyph_store,'DATABASE',db):
                        with self.assertRaises(ValueError):glyph_store.manifest()
                finally:glyph_store._manifest.cache_clear()


if __name__=='__main__':unittest.main()
