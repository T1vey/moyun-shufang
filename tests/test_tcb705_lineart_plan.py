"""Local gallery line art (GUI "选择本地线条图") must plan with the profiles the UI starts with."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tcb705.config import load  # noqa: E402
from tcb705.planner import plan  # noqa: E402

PATHS = json.loads((ROOT / 'tests/fixtures/gallery_duck_paths.json').read_text('utf-8'))


class GalleryLineartPlan(unittest.TestCase):
    def test_demo_profile_matches_real_sampling(self):
        demo = load(ROOT / 'robots/tcb705/profile.demo.json')['planning']['sample_step_m']
        real = load(ROOT / 'robots/tcb705/profile.armvision_joint.json')['planning']['sample_step_m']
        self.assertLessEqual(demo, real)

    def test_duck_from_gallery_plans_in_demo(self):
        # Failed with CURVE_GEOMETRY (0.141 mm > 0.1 mm) at the old 1 mm demo sampling.
        cfg = load(ROOT / 'robots/tcb705/profile.demo.json')
        m = plan(PATHS, cfg, cfg['q_start_rad'])['metrics']
        self.assertIsNone(m['max_path_error_m'])
        self.assertFalse(m['runtime_geometry_verification'])
        self.assertGreater(m['nodes'], 1000)


if __name__ == '__main__':
    unittest.main()


class BoardKioskCss(unittest.TestCase):
    """The board screen is WebKitGTK 2.28: no `inset`, `:has()` or flex `gap` outside fallbacks."""

    def test_desktop_page_css_has_no_inset_shorthand(self):
        import re
        html = (ROOT / 'user_gui/static/desktop.html').read_text('utf-8')
        for name in re.findall(r'href="/static/([\w.-]+\.css)"', html):
            css = (ROOT / 'user_gui/static' / name).read_text('utf-8')
            css = re.sub(r'@supports not \(inset:0\)\{.*?\}\}', '', css, flags=re.S)
            self.assertIsNone(re.search(r'(?<![\w-])inset\s*:', css), name)


class FrameBudget(unittest.TestCase):
    """max_frames raised to 800,000 on 2026-10-18 (~0.53 KB/frame planning peak)."""

    def test_config_accepts_800k_and_rejects_more(self):
        import copy
        from tcb705.config import validate
        cfg = load(ROOT / 'robots/tcb705/profile.demo.json')
        self.assertEqual(cfg["planning"]["max_frames"], 800000)
        too_many = copy.deepcopy(cfg); too_many['planning']['max_frames'] = 800001
        with self.assertRaises(ValueError):
            validate(too_many)

    def test_long_gallery_drawing_now_plans(self):
        # 102 strokes, ~382k frames (25 min): FRAME_BUDGET at the old 150000 cap.
        paths = json.loads((ROOT / 'tests/fixtures/gallery_long_paths.json').read_text('utf-8'))
        cfg = load(ROOT / 'robots/tcb705/profile.demo.json')
        m = plan(paths, cfg, cfg['q_start_rad'])['metrics']
        self.assertGreater(m['frames'], 150000)
        self.assertLessEqual(m["frames"], 800000)


class PreviewSize(unittest.TestCase):
    """The board WebKit renders in software: a per-frame preview (2.3 MB SVG) froze the touch screen."""

    def test_preview_is_simplified_within_tolerance(self):
        import math
        from tcb705.artifact import preview_svg, simplify
        t = [i / 2000 * 2 * math.pi for i in range(2001)]
        circle = [[50 + 30 * math.cos(a), 50 + 30 * math.sin(a)] for a in t]
        line = [[10 + i * 0.01, 20.0] for i in range(5001)]
        kept = simplify(circle)
        self.assertLess(len(kept), 200)
        for x, y in circle[::5]:
            d = min(math.dist((x, y), tuple(p)) for p in kept)
            self.assertLess(d, 2.0)   # coarse sanity; the chord bound below is the real check
        r_chord = max(30 - math.hypot((a[0] + b[0]) / 2 - 50, (a[1] + b[1]) / 2 - 50) for a, b in zip(kept[:-1], kept[1:]))
        self.assertLessEqual(r_chord, 0.0201)
        self.assertEqual(len(simplify(line)), 2)
        svg = preview_svg(dict(width_mm=100, height_mm=100, paths=[circle, line]))
        self.assertLess(len(svg), 8000)


class PlanningThreadEventLoop(unittest.TestCase):
    """GUI plans run in worker threads; PYNQ needs an asyncio loop there or the PL falls back to CPU."""

    def test_worker_thread_gets_a_loop_before_attach(self):
        import asyncio, threading
        from tcb705.accel_runtime import ensure_event_loop, open_accelerator
        out = {}

        def work():
            try:
                asyncio.get_event_loop(); out['before'] = 'loop'
            except RuntimeError as exc:
                out['before'] = str(exc)
            ensure_event_loop()
            out['after'] = asyncio.get_event_loop() is not None
            out['reason'] = open_accelerator()[1] or ''
        t = threading.Thread(target=work); t.start(); t.join()
        self.assertIn('event loop', out['before'])
        self.assertTrue(out['after'])
        self.assertNotIn('event loop', out['reason'])


class NativeEqualsNumpy(unittest.TestCase):
    """C++ collision/sampling (2026-10-18) must give exactly what the numpy code gives."""

    @classmethod
    def setUpClass(cls):
        from tcb705.model import Model
        cls.cfg = load(ROOT / 'robots/tcb705/profile.armvision_joint.json'); cls.model = Model(cls.cfg)

    def test_sampling_bitwise(self):
        import math
        import numpy as np
        m = self.model
        if not getattr(m, 'native_sampling', False):
            self.skipTest('native core without tcb_sample_rows (rebuild with scripts/build_tcb705.py)')
        rng = np.random.default_rng(7); n = 5000
        coeff = rng.normal(0, 0.3, (40, 6, 7)); seg = rng.integers(0, 40, n); u = rng.random(n)
        sdk, rounded = m.sample_rows(coeff, seg, u)
        samples = np.zeros((n, 7))
        for power in range(5, -1, -1):
            samples = samples * u[:, None] + coeff[seg, power, :]
        ref = ((samples[:, m.order] - m.offset) * m.sign * 180 / math.pi).astype(np.float32)
        back = np.empty_like(samples); back[:, m.order] = ref.astype(float) * math.pi / 180 * m.sign + m.offset
        self.assertEqual(sdk.tobytes(), ref.tobytes()); self.assertEqual(rounded.tobytes(), back.tobytes())

    def test_collision_same_first_hit(self):
        import numpy as np
        from tcb705 import collision
        m = self.model
        if not getattr(m, 'native_collision', False):
            self.skipTest('native core without tcb_self_collision_batch')
        rng = np.random.default_rng(3)
        Q = rng.uniform(m.lower, m.upper, (3000, 7))
        def first(native):
            m.native_collision = native
            try:
                collision.check_batch(m, Q); return None
            except ValueError as exc:
                return str(exc)
            finally:
                m.native_collision = True
        self.assertEqual(first(True), first(False))
        for row in range(0, 3000, 300):   # also row by row (collision-free and colliding rows)
            Qr = Q[row:row + 1]
            m.native_collision = False
            try:
                collision.check_batch(m, Qr); a = None
            except ValueError as exc:
                a = str(exc)
            m.native_collision = True
            try:
                collision.check_batch(m, Qr); b = None
            except ValueError as exc:
                b = str(exc)
            self.assertEqual(a, b)


class SpeedSettingKeepsPlans(unittest.TestCase):
    """Settings page speed (2026-10-20): saving only the speed must not change the plan digest."""

    def test_browser_round_trip_and_speed_change_keep_digest(self):
        import copy
        from tcb705.config import digest
        from tcb705.workbench import _keep_unchanged
        cfg = load(ROOT / 'robots/tcb705/profile.armvision_joint.json')
        def browser(x):   # JSON in a browser writes 1.0 as 1
            if isinstance(x, dict): return {k: browser(v) for k, v in x.items()}
            if isinstance(x, list): return [browser(v) for v in x]
            if isinstance(x, float) and x.is_integer(): return int(x)
            return x
        sent = browser(copy.deepcopy(cfg))
        sent['execution']['web_program']['draw_speed_pct'] = sent['execution']['web_program']['air_speed_pct'] = 25
        self.assertNotEqual(digest(sent), digest(cfg))           # what used to happen
        kept = _keep_unchanged(sent, cfg)
        self.assertEqual(digest(kept), digest(cfg))
        self.assertEqual(kept['execution']['web_program']['draw_speed_pct'], 25)
        moved = copy.deepcopy(sent); moved['armvision']['z_table_mm'] += 1   # a real change still changes it
        self.assertNotEqual(digest(_keep_unchanged(moved, cfg)), digest(cfg))
