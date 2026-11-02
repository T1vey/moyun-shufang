"""手写识字 (2026-10-28): stroke checks, rendering, the model and the screen endpoint (no robot)."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from user_gui import hwr

H = lambda y, a=.2, b=.8: [[a, y], [(a + b) / 2, y + .005], [b, y]]
V = lambda x, a=.2, b=.8: [[x, a], [x + .005, (a + b) / 2], [x, b]]
TEN = [H(.5), V(.5, .15, .85)]                                   # 十
KING = [H(.2, .25, .75), H(.5, .3, .7), V(.5, .2, .85), H(.85, .15, .85)]   # 王

try:
    import cv2  # noqa: F401
    MODEL = (hwr.MODEL_DIR / 'hccr_mbv2.onnx').is_file()
except ImportError:
    MODEL = False


class StrokeTests(unittest.TestCase):
    def test_bad_input_is_refused(self):
        for bad in (None, [], [[]], [[[0.5]]], [[[0.5, 1.2]]], [[['a', 0]]], [[[0, 0]]] * 65,
                    [[[0.1, 0.1]] * 4001]):
            with self.assertRaises(ValueError):
                hwr.check_strokes(bad)
        self.assertEqual(hwr.check_strokes([[[0, 1], [1, 0]]]), [[(0.0, 1.0), (1.0, 0.0)]])

    def test_small_and_large_writing_give_the_same_input(self):
        small = [[[.4 + x * .2, .4 + y * .2] for x, y in s] for s in TEN]
        a, b = hwr.to_input(TEN), hwr.to_input(small)
        self.assertEqual(a.shape, (1, 1, 64, 64))
        self.assertLess(float(np.abs(a - b).mean()), 0.02)

    def test_normalize_matches_the_training_rule(self):
        src = np.full((100, 80), 255, dtype=np.uint8); src[20:80, 15:65] = 50
        out = hwr.normalize(src)
        ys, xs = np.where(out < 220)
        self.assertEqual(max(ys.max() - ys.min(), xs.max() - xs.min()) + 1, 56)   # long side 56
        self.assertTrue((hwr.normalize(np.full((10, 10), 255, np.uint8)) == 255).all())


@unittest.skipUnless(MODEL, 'OpenCV or the hand-writing model is not installed')
class ModelTests(unittest.TestCase):
    def test_simple_characters(self):
        r = hwr.Recognizer()
        for strokes, ch in ((TEN, '十'), (KING, '王')):
            out = r.recognize(strokes)
            self.assertEqual(out['candidates'][0]['char'], ch)
            self.assertEqual(len(out['candidates']), hwr.TOP_K)
            self.assertEqual(out['classes'], 3755)

    def test_damaged_model_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('hccr_mbv2.onnx', 'charset.json'):
                Path(tmp, name).write_bytes((hwr.MODEL_DIR / name).read_bytes()[:1000])
            with self.assertRaisesRegex(ValueError, '校验失败'):
                hwr.Recognizer(tmp).recognize(TEN)
        with self.assertRaisesRegex(ValueError, '未安装'):
            hwr.Recognizer('/nonexistent').recognize(TEN)


@unittest.skipUnless(MODEL, 'OpenCV or the hand-writing model is not installed')
class EndpointTests(unittest.TestCase):
    def setUp(self):
        from user_gui.display_server import DisplayServer, Hub
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        hub = Hub(Path(self.tmp.name) / 'uploads', token='phone-token')
        self.server = DisplayServer(('127.0.0.1', 0), hub, interfaces=[])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.close)
        self.url = 'http://127.0.0.1:%d/api/hwr/recognize' % self.server.server_port

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def post(self, data):
        req = urllib.request.Request(self.url, data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_recognize_from_the_screen(self):
        code, body = self.post({'strokes': TEN})
        self.assertEqual(code, 200, body); self.assertEqual(body['candidates'][0]['char'], '十')
        code, body = self.post({'strokes': []})
        self.assertEqual(code, 400); self.assertIn('请先写一个字', body['error'])
        code, _ = self.post(['not', 'an', 'object'])
        self.assertEqual(code, 400)


if __name__ == '__main__':
    unittest.main()
