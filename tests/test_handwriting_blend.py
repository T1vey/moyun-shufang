"""Live-handwriting blending and queue depth (offline; no controller, no motion)."""
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_handwriting import config                      # noqa: E402
from handwriting.recognizer import recognize              # noqa: E402
from handwriting.planner import compile_stroke            # noqa: E402
from handwriting import executor as hx                    # noqa: E402
from tcb705.model import Model                             # noqa: E402
from tcb705.planner import PHASE                           # noqa: E402
from tcb705.sdk_motion import SdkMotion                    # noqa: E402
from tcb705.web_executor import build, settings, controller_points, _turn_deg  # noqa: E402


class FakeSdk:
    def __init__(self):
        self.moves = []
    def move(self, kind, values, smooth=0, acc=0.0, dec=0.0, ratio=0.0):
        self.moves.append((kind, smooth)); return 10 + len(self.moves)
    def finished(self, seq):
        return None


class BlendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = config(); m = Model(cls.c)
        q = m.from_sdk(cls.c['execution']['web_program']['home']['joint_degrees'])
        raw = [[.13, .18], [.4, .17], [.78, .18], [.79, .47], [.77, .84]]          # 横折
        cls.p = compile_stroke(recognize(raw), raw, 60, cls.c, m, q, 'ready', lambda: False)

    def blocks(self, blend):
        _, chunks = build(self.c, self.p.nodes, settings(self.c), joint_keep=self.p.prepared.keep, brush_blend=blend)
        out = []
        for ch in chunks:
            body = [b for b in ch['content']['programs'][0]['codeBlock'] if b['fc'] != 'end']
            out += list(zip(ch['node_index'], (b['code']['smooth'] for b in body)))
        return out

    def test_pages_keep_exact_stops(self):
        self.assertTrue(all(s == 0 for _, s in self.blocks(None)))

    def test_blend_only_at_gentle_draw_vertices(self):
        blocks = self.blocks(hx.BLEND)
        keep = list(self.p.prepared.keep)[1:]
        phase = self.p.nodes['interval_phase']; stops = set(self.p.nodes['stops'])
        mm, _ = controller_points(self.c, self.p.nodes)
        smoothed = [i for i, s in blocks if s]
        self.assertGreater(len(smoothed), len(blocks) // 3)     # most of the stroke flows
        self.assertEqual(blocks[-1][1], 0)                      # stroke end is exact
        full = [0] + keep
        for k, (i, s) in enumerate(blocks):
            if not s:
                continue
            self.assertEqual(s, hx.BLEND['smooth'])
            self.assertNotIn(i, stops)
            self.assertEqual(phase[i - 1], phase[i])            # no pen up/down transition
            turn = _turn_deg(mm, full[k], i, full[k + 2])
            self.assertLessEqual(turn, hx.BLEND['corner_deg'])
        # The 折 corner itself must stop: the sharpest kept vertex is never blended.
        turns = [(_turn_deg(mm, full[k], i, full[k + 2]), s) for k, (i, s) in enumerate(blocks[:-1])]
        self.assertEqual(max(turns)[1], 0)
        self.assertGreater(max(turns)[0], 60)

    def test_performance_blend_keeps_air_moves_exact(self):
        # 2026-10-28: a blended approach from home cut 23.75 mm off the planned path in the air.
        from tcb705.web_executor import AIR
        phase = self.p.nodes['interval_phase']
        blend = dict(hx.BLEND, draw_only=True)
        blocks = self.blocks(blend)
        self.assertTrue(any(s for _, s in blocks))
        self.assertFalse([i for i, s in blocks if s and phase[i - 1] in AIR])
        draw = [(i, s) for i, s in self.blocks(hx.BLEND) if phase[i - 1] not in AIR]
        self.assertEqual(draw, [(i, s) for i, s in blocks if phase[i - 1] not in AIR])   # on paper unchanged

    def test_handwriting_never_blends_air_moves(self):
        from tcb705.web_executor import AIR
        self.assertTrue(hx.BLEND.get('draw_only'))
        phase = self.p.nodes['interval_phase']
        self.assertFalse([i for i, s in self.blocks(hx.BLEND) if s and phase[i - 1] in AIR])

    def test_merged_stroke_is_far_fewer_moves(self):
        self.assertLess(self.p.metrics['blocks'], len(self.p.nodes['positions_m']) / 4)

    def test_queue_depth_override_passes_smooth(self):
        self.assertEqual(self.c['execution']['sdk'].get('queue_depth', 1), 1)
        content = {'programs': [{'codeBlock': [
            {'fc': 'hmcRobotFree', 'code': {'endp': [0] * 7, 'smooth': 3}} for _ in range(6)] + [{'fc': 'end'}]}]}
        sdk = FakeSdk(); SdkMotion(sdk, None, self.c, queue_depth=hx.QUEUE_DEPTH).start(content, lambda: False)
        self.assertEqual(sdk.moves, [('J', 3)] * hx.QUEUE_DEPTH)
        sdk = FakeSdk(); SdkMotion(sdk, None, self.c).start(content, lambda: False)
        self.assertEqual(sdk.moves, [('J', 0)])                 # global depth 1: no blending
        with self.assertRaises(ValueError):
            SdkMotion(FakeSdk(), None, self.c, queue_depth=0)


if __name__ == '__main__':
    unittest.main()
