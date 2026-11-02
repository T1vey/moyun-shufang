"""Two tools, two calibrations: brush contact height, mounted-tool gate (fake controller, no hardware)."""
import copy
import unittest

import numpy as np

from calligraphy import couplets
from calligraphy.presets import profile, binding, BRUSH, mounted_tool
from tcb705 import web_executor as W
from tests import test_tcb705_web as web
from tests.test_text_calligraphy import config as text_config


def brush_config(contact=259.3):
    c = text_config()
    c['calligraphy'].update(hair_length_mm=13., max_diameter_mm=4., max_press_mm=6., contact_z_mm=contact)
    c['calligraphy']['calibration_binding'] = binding(c)
    return c


class ProfileTests(unittest.TestCase):
    def test_profile_carries_the_new_brush(self):
        p = profile(brush_config())
        self.assertEqual((p['hair_length_mm'], p['max_diameter_mm'], p['max_press_mm'], p['contact_z_mm']), (13., 4., 6., 259.3))
        self.assertTrue(p['verified'])

    def test_press_cannot_exceed_hair_or_six_mm(self):
        c = brush_config(); c['calligraphy']['hair_length_mm'] = 5.
        with self.assertRaises(ValueError):
            profile(c)
        c = brush_config(); c['calligraphy']['max_press_mm'] = 6.5
        with self.assertRaises(ValueError):
            profile(c)

    def test_old_profile_without_brush_height_still_loads(self):
        p = profile(text_config())
        self.assertNotIn('contact_z_mm', p); self.assertEqual(p['hair_length_mm'], BRUSH['hair_length_mm'])

    def test_mounted_tool(self):
        c = brush_config(); self.assertEqual(mounted_tool(c), 'pen')
        c['mounted_tool'] = 'brush'; self.assertEqual(mounted_tool(c), 'brush')
        c['mounted_tool'] = 'knife'
        with self.assertRaises(ValueError):
            mounted_tool(c)


class SurfaceTests(unittest.TestCase):
    def test_brush_tasks_use_the_brush_height(self):
        c = brush_config()
        for schema in ('brush-text-v1', 'brush-preset-v1', 'brush-poem-v1', 'brush-handwriting-v1'):
            self.assertAlmostEqual(couplets.surface(c, dict(schema=schema))['origin_m'][2], .2593)
        self.assertEqual(couplets.surface(c, None), c['paper'])              # sketches keep the pen height
        self.assertEqual(c['paper']['origin_m'][2], text_config()['paper']['origin_m'][2])

    def test_couplets_on_the_paper_at_brush_height(self):
        c = brush_config()
        s = couplets.surface(c, dict(schema=couplets.SCHEMA))
        self.assertEqual(s['width_mm'], c['paper']['width_mm']); self.assertAlmostEqual(s['origin_m'][2], .2593)


class GateTests(unittest.TestCase):
    fake = web.WebExecutorTests.fake

    @classmethod
    def setUpClass(cls):
        import tempfile
        from tcb705 import artifact
        from tcb705.planner import plan
        web.WebExecutorTests.__dict__['setUpClass'].__func__(cls)
        # The same sketch planned while the brush is declared mounted (the tool is part of the config).
        cls.brush_cfg = copy.deepcopy(cls.cfg); cls.brush_cfg['mounted_tool'] = 'brush'
        cls.brush_tmp = tempfile.TemporaryDirectory()
        artifact.save(plan(web.strokes(), cls.brush_cfg), cls.brush_tmp.name, 'real')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup(); cls.brush_tmp.cleanup()

    def test_sketch_plan_refused_with_brush_mounted(self):
        _, ctrl, clock = self.fake()
        cfg = copy.deepcopy(self.brush_cfg); cfg['execution']['web_program']['mode'] = 'cartesian'
        with self.assertRaisesRegex(W.ExecutionError, 'TOOL_MISMATCH'):
            W.execute(self.brush_tmp.name, cfg, controller=ctrl, clock=clock, sleep=clock.sleep)
        self.assertEqual(ctrl.calls, [])                                    # refused before touching the controller

    def test_sketch_plan_runs_with_pen(self):
        cfg, ctrl, clock = self.fake()                                      # no mounted_tool: the drawing pen
        self.assertEqual(W.execute(self.tmp.name, cfg, controller=ctrl, clock=clock, sleep=clock.sleep)['status'], 'DONE')

    def test_brush_run_needs_brush_height(self):
        cfg = copy.deepcopy(self.brush_cfg)              # brush mounted, no brush contact height saved
        with self.assertRaisesRegex(W.ExecutionError, 'BRUSH_NOT_CALIBRATED'):
            self._brush_gate(cfg)

    def _brush_gate(self, cfg):
        # The gate runs before any plan or controller access; patch the loader to hand it brush nodes.
        original = W.check_frozen
        W.check_frozen = lambda doc, nodes, config: None
        try:
            W.execute(None, cfg, frozen=({}, dict(calligraphy={'schema': 'brush-text-v1'})))
        finally:
            W.check_frozen = original

    def test_clearance_from_mounted_brush_tip(self):
        cfg = copy.deepcopy(self.cfg)
        pen = W.mode_switch_min_z(cfg, [0, 0, 0])
        cfg['calligraphy'] = dict(cfg.get('calligraphy', {}), contact_z_mm=cfg['paper']['origin_m'][2] * 1000 + 40.)
        self.assertAlmostEqual(W.mode_switch_min_z(cfg, [0, 0, 0]), pen)    # pen mounted: unchanged
        cfg['mounted_tool'] = 'brush'
        self.assertAlmostEqual(W.mode_switch_min_z(cfg, [0, 0, 0]), pen + 40.)


if __name__ == '__main__':
    unittest.main()
