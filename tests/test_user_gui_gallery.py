import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from PIL import Image
from user_gui.lineart_library import LineartLibrary
from user_gui.display_server import Hub, DisplayServer
from user_gui.workflow import Workflow


def artwork(size=(160, 80), color='white'):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, 'PNG')
    return buf.getvalue()


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.library = LineartLibrary(self.root / 'art', [self.root / 'cloud'])

    def test_saved_and_cloud_images_are_discoverable_without_duplicates(self):
        cloud = self.root / 'cloud'; cloud.mkdir()
        (cloud / 'duck.png').write_bytes(artwork())
        saved = self.library.save(artwork(), 'image/png', 'duck.png')
        self.assertEqual(len(self.library.records()), 1)
        self.assertEqual(saved['width'], 160)
        self.assertNotIn('path', saved)
        self.assertEqual(self.library.read(saved['id'])[0], artwork())

    def test_import_persists_and_keeps_name_and_aspect(self):
        self.library.save(artwork(), 'image/png', '../画稿.png')
        fresh = LineartLibrary(self.root / 'art')
        item = fresh.records()[0]
        self.assertEqual(item['name'], '画稿.png')
        self.assertEqual((item['width'], item['height']), (160, 80))
        thumb, kind = fresh.read(item['id'], thumbnail=True)
        with Image.open(io.BytesIO(thumb)) as image:
            self.assertEqual(image.width / image.height, 2)
            self.assertLessEqual(image.width, 280)
        self.assertEqual(kind, 'image/png')

    def test_invalid_and_non_art_files_are_not_exposed(self):
        folder = self.root / 'art'; folder.mkdir()
        (folder / 'broken.png').write_bytes(b'not-image')
        (folder / 'secret.txt').write_text('private')
        self.assertEqual(self.library.records(), [])
        for identity in ('../secret.txt', '/etc/passwd', '', None, 'f'*64):
            with self.assertRaises(ValueError):
                self.library.read(identity)

    def test_legacy_label_uses_china_time_even_when_board_uses_utc(self):
        folder = self.root / 'cloud'; folder.mkdir()
        (folder/'old.png').write_bytes(artwork())
        (folder/'old.json').write_text(json.dumps({'source_name':'lineart.png',
            'created_at':'2026-10-04T00:39:00+08:00'}))
        self.assertEqual(self.library.records()[0]['name'], '线稿 · 10-04 00:39')

    def test_changed_image_cannot_be_selected_by_old_id(self):
        item = self.library.save(artwork(), 'image/png', 'one.png')
        path = next((self.root / 'art').glob('*.png'))
        path.write_bytes(artwork(color='black'))
        with self.assertRaises(ValueError):
            self.library.read(item['id'])

    def test_truncated_and_animated_imports_are_rejected(self):
        for raw, kind in ((artwork()[:30], 'image/png'), (artwork(), 'image/jpeg')):
            with self.assertRaises(ValueError):
                self.library.save(raw, kind, 'bad.png')
        buf = io.BytesIO()
        Image.new('RGB', (20, 20), 'white').save(buf, 'WEBP', save_all=True,
            append_images=[Image.new('RGB', (20, 20), 'black')], duration=100, loop=0)
        with self.assertRaises(ValueError):
            self.library.save(buf.getvalue(), 'image/webp', 'animated.webp')


class FakePipeline:
    def __init__(self): self.calls = []
    def busy(self): return False
    def extract_local(self, *args): self.calls.append('local'); return {}
    def register(self, *args): return 'image'
    def plan(self, *args, **kw): self.calls.append('plan'); return 'plan'
    def preview(self, *args): return b'<svg xmlns="http://www.w3.org/2000/svg"/>'
    def execute(self, *args): self.calls.append('execute')
    def generate(self, *args): self.calls.append('cloud'); raise AssertionError('No cloud')


class GalleryHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.library = LineartLibrary(self.root / 'art')
        self.pipeline = FakePipeline()
        self.workflow = Workflow(self.pipeline, self.root)
        self.server = DisplayServer(('127.0.0.1', 0), Hub(self.root / 'uploads'),
            interfaces=[], workflow=self.workflow, lineart_library=self.library)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.close)
        self.base = 'http://127.0.0.1:%d' % self.server.server_port
        self.token = self.server.hub.control_token

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def req(self, path, data=None, headers=None):
        headers = dict(headers or {})
        if isinstance(data, dict):
            data = json.dumps(data).encode(); headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.base+path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=4) as r: return r.status, r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_listing_and_thumbnail_do_not_run_pipeline(self):
        item = self.library.save(artwork(), 'image/png', 'duck.png')
        code, raw = self.req('/api/lineart-library')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)['total'], 1)
        self.assertEqual(self.req(item['thumbnail'])[0], 200)
        self.assertEqual(self.pipeline.calls, [])

    def test_import_requires_token_and_same_origin_and_survives_restart(self):
        path = '/api/lineart-library/import?name=duck.png'
        headers = {'Content-Type': 'image/png', 'X-Screen-Token': self.token}
        self.assertEqual(self.req(path, artwork(), {'Content-Type':'image/png'})[0], 403)
        self.assertEqual(self.req(path, artwork(), dict(headers, Origin='http://evil.invalid'))[0], 403)
        self.assertEqual(self.req(path, b'broken', headers)[0], 400)
        self.assertEqual(self.req(path, artwork(), headers)[0], 200)
        self.assertEqual(len(LineartLibrary(self.root/'art').records()), 1)
        self.assertEqual(self.pipeline.calls, [])

    def test_prepare_skips_cloud_and_waits_for_motion_confirmation(self):
        item = self.library.save(artwork(), 'image/png', 'duck.png')
        body = dict(id=item['id'], cid='desktop001', rid='request001')
        path = '/api/lineart-library/prepare'
        self.assertEqual(self.req(path, body)[0], 403)
        code, raw = self.req(path, body, {'X-Screen-Token':self.token})
        self.assertEqual(code, 200, raw)
        self.workflow.worker.join(3)
        self.assertEqual(self.workflow.snapshot()['phase'], 'ready')
        self.assertEqual(self.pipeline.calls, ['local', 'plan'])
        self.assertEqual(self.req(path, body, {'X-Screen-Token':self.token})[0], 409)

    def test_remote_clients_and_host_rebinding_cannot_browse_library(self):
        self.assertEqual(self.req('/api/lineart-library', headers={'Host':'evil.invalid'})[0], 403)
        with patch('user_gui.display_server.Handler.is_local', return_value=False):
            self.assertEqual(self.req('/api/lineart-library')[0], 403)

    def test_missing_selection_does_not_occupy_workflow(self):
        code, _ = self.req('/api/lineart-library/prepare',
            dict(id='f'*64, cid='desktop001', rid='request001'), {'X-Screen-Token': self.token})
        self.assertEqual(code, 400)
        self.assertEqual(self.workflow.snapshot()['phase'], 'idle')
        self.assertEqual(self.pipeline.calls, [])


if __name__ == '__main__':
    unittest.main()
