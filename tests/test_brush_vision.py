import tempfile
import unittest
from pathlib import Path
import numpy as np
from brush_vision import contract as c, model as m, segment, templates
from brush_vision.service import VisionService


def photo(text, seed=3):
    import cv2
    from calligraphy import glyph_store as g
    rng = np.random.default_rng(seed)
    img = (np.full((m.H, m.W), 215, np.int16) + rng.integers(-6, 7, (m.H, m.W))).astype(np.uint8)
    cell = 400 // len(text)
    for i, ch in enumerate(text):
        page = templates.render(g.glyph(ch)['strokes'], 1.1, 0.03, 1.5)
        size = int(cell * 0.8)
        glyph = cv2.resize(page.astype(np.uint8) * 255, (size, size), interpolation=cv2.INTER_AREA)
        x, y = 120 + i * cell + (cell - size) // 2, 40 + (400 - size) // 2
        img[y:y + size, x:x + size][glyph > 127] = 35
    return img


class FakeCamera:
    def __init__(self, img):
        self.img = img

    def latest(self, max_age=1.0, timeout=1.0):
        return m.gray_to_yuyv(self.img)

    def status(self):
        return {}


class BrushVisionTest(unittest.TestCase):
    def test_rect_and_projection_round_trip(self):
        rng = np.random.default_rng(1)
        rect = rng.random((97, 97)) > .7
        self.assertTrue(np.array_equal(c.unpack_rect(c.pack_rect(rect), 97), rect))
        col, row = m.projections(rect)
        words = np.zeros(2048, np.uint64)
        words[c.PROJ_COL:c.PROJ_COL + 160] = c.pack_proj(col, row)
        got = c.unpack_proj(words, 97)
        self.assertTrue(np.array_equal(got[0], col) and np.array_equal(got[1], row))

    def test_fixed_homography_identity(self):
        frame = np.random.default_rng(2).random((m.H, m.W)) > .5
        hq = m.homography_fixed(np.array([[1., 0, 30], [0, 1., 20], [0, 0, 1.]]))
        rect = m.rectify(frame, hq, 64)
        self.assertTrue(np.array_equal(rect, frame[20:84, 30:94]))

    def test_segment_splits_two_glyphs(self):
        rect = np.zeros((320, 320), bool)
        rect[100:200, 20:120] = True
        rect[100:200, 180:300] = True
        boxes = segment.boxes(rect, rect.sum(axis=1))
        self.assertEqual(len(boxes), 2)
        self.assertLess(boxes[0][0], boxes[1][0])

    def test_service_recognises_and_scores(self):
        with tempfile.TemporaryDirectory() as folder:
            svc = VisionService(folder, camera=FakeCamera(photo('永王')))
            svc.configure({'mode': 'auto'})
            result = svc.recognise({})
            chars = [ch['char'] for ch in result['chars'] if not ch['empty']]
            self.assertEqual(chars, ['永', '王'])
            for ch in result['chars']:
                self.assertTrue(0 <= ch['total'] <= 100)
                self.assertEqual(set(ch['subs']), {'shape', 'stroke', 'structure', 'ink'})
            self.assertEqual(result['backend'], 'CPU')

    @unittest.skipUnless(Path(__file__).resolve().parents[1].joinpath('data/hwr/hccr_mbv2.onnx').is_file(),
                         'hand-writing model not installed')
    def test_local_model_names_the_character(self):
        # 本地模型 (2026-10-28): the 手写识字 model names it; templates still give style and score.
        with tempfile.TemporaryDirectory() as folder:
            svc = VisionService(folder, camera=FakeCamera(photo('永王')))
            with self.assertRaises(ValueError):
                svc.configure({'engine': 'cloud'})
            svc.configure({'mode': 'auto', 'engine': 'model'})
            self.assertEqual(svc.settings['engine'], 'model')
            result = svc.recognise({})
            got = [ch for ch in result['chars'] if not ch['empty']]
            self.assertEqual([ch['char'] for ch in got], ['永', '王'])
            self.assertEqual(result['engine'], 'model')
            for ch in got:
                self.assertEqual(ch['engine'], 'model')
                self.assertTrue(0 < ch['top5'][0]['p'] <= 1)
                self.assertIn(ch['category'], ('楷书', '行书', '草书', '隶书', '魏碑'))
                self.assertTrue(0 <= ch['total'] <= 100)
            self.assertGreater(result['timing_ms']['model'], 0)
            svc.configure({'engine': 'template'})
            self.assertEqual(svc.recognise({})['engine'], 'template')

    def test_thin_strokes_with_shadow_and_dark_table(self):
        import cv2
        from calligraphy import glyph_store as g
        rng = np.random.default_rng(4)
        yy, xx = np.mgrid[0:m.H, 0:m.W]
        img = (170 - 60 * (xx / m.W) + 25 * (yy / m.H)).astype(np.float32)
        img[:, :100] = 45
        img[:, 560:] = 55
        img += rng.normal(0, 4, img.shape)
        old = (templates.BASE_WIDTH, templates.PRESSURE_WIDTH)
        templates.BASE_WIDTH, templates.PRESSURE_WIDTH = 2.0, 0.0
        try:
            for i, ch in enumerate('书法'):
                page = templates.render(g.glyph(ch)['strokes'], 1.0, 0.04, 2.0)
                gl = cv2.resize(page.astype(np.uint8) * 255, (160, 160), interpolation=cv2.INTER_AREA)
                x = 140 + i * 200
                img[160:320, x:x + 160][gl > 100] *= 0.35
        finally:
            templates.BASE_WIDTH, templates.PRESSURE_WIDTH = old
        with tempfile.TemporaryDirectory() as folder:
            svc = VisionService(folder, camera=FakeCamera(np.clip(img, 0, 255).astype(np.uint8)))
            svc.configure({'mode': 'auto'})
            self.assertEqual([c['char'] for c in svc.recognise({})['chars'] if not c['empty']], ['书', '法'])

    def test_pl_driver_path_with_emulated_core(self):
        """Service through VisionPL: DMA buffer sizes and word layouts of all three modes."""
        from brush_vision import hardware

        class Buf(np.ndarray):
            physical_address = 0x10000000
            def flush(self): pass
            def invalidate(self): pass
            def freebuffer(self): pass

        class Emulated(hardware.VisionPL):
            def __init__(self):
                regs = dict(abi=c.RECOG_ABI, top=c.RECOG_TOP, mode=0x18, params=0x20, src=0x2c, dst=0x38,
                            tpl=0x44, identity=0x50, **{'return': 0x10})
                super().__init__(None, regs, lambda shape, dtype: np.zeros(shape, dtype).view(Buf))

            def _run(self, mode, src, dst, tpl):
                p = self.buffers['params']
                if mode == c.MODE_PREPROCESS:
                    gray = m.yuyv_gray(np.asarray(src).view(np.uint8))
                    roi = (int(p[1]) & 0xffff, int(p[1]) >> 16 & 0xffff, int(p[1]) >> 32 & 0xffff, int(p[1]) >> 48)
                    ops = [int(p[0]) >> (24 + 2 * k) & 3 for k in range(4)]
                    b, st = m.preprocess(gray, roi, bool(int(p[0]) & 1), int(p[0]) >> 8 & 0xff, 0, ops)
                    dst[:4800] = c.frame_u64(m.pack_frame(b))
                    dst[4800:4802] = c.preprocess_stats_words(st)
                elif mode == c.MODE_RECTIFY:
                    size = int(p[0])
                    hq = [int(np.int64(v)) for v in np.asarray(p[1:10]).view(np.int64)]
                    rect = m.rectify(m.unpack_frame(np.asarray(src[:4800]).view('<u4')), hq, size)
                    dst[:1600] = c.pack_rect(rect)
                else:
                    size, nb = int(p[0]) & 0xffffffff, int(p[0]) >> 32
                    rect = c.unpack_rect(np.asarray(src), size)
                    for i in range(nb):
                        w = int(p[c.PARAM_BOXES + i])
                        box = (w & 0xffff, w >> 16 & 0xffff, w >> 32 & 0xffff, w >> 48)
                        feats, bitmaps = next((f, b) for f, b, buf in self.sets.values() if buf is tpl)
                        r = m.recognise_box(rect, size, box, feats, bitmaps, int(p[c.PARAM_EXPECT + i]) & 0x7fffffff
                                            if int(p[c.PARAM_EXPECT + i]) < 0x80000000 else -1)
                        dst[i * 128:(i + 1) * 128] = c.result_words(r)
                return 0.001

            def load_templates(self, blob_u64, count, name='default', feats=None, bitmaps=None):
                buf = np.asarray(blob_u64).view(Buf)
                self.sets = getattr(self, 'sets', {})
                self.sets[name] = (feats, bitmaps, buf)
                self.tpls[name] = (buf, count)

        with tempfile.TemporaryDirectory() as folder:
            svc = VisionService(folder, hardware=Emulated(), camera=FakeCamera(photo('永王')))
            for st in svc.styles:
                svc._hardware.load_templates(st['match'], len(svc.chars), name=st['style'], feats=st['feats'],
                                             bitmaps=np.zeros((1, 512), np.uint8))
            svc.configure({'mode': 'auto'})
            result = svc.recognise({})
            self.assertEqual(result['backend'], 'PL')
            self.assertEqual([ch['char'] for ch in result['chars'] if not ch['empty']], ['永', '王'])

if __name__ == '__main__':
    unittest.main()
