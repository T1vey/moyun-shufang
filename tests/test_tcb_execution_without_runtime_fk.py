"""Live handwriting keeps every IK knot without another FK acceptance pass; full
brush plans merge FK-verified blocks so execution follows the GUI speed."""
import copy
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import numpy as np

from calligraphy.presets import task
from handwriting.planner import compile_stroke
from handwriting.recognizer import recognize
from test_handwriting import config
from tcb705.artifact import nodes_of
from tcb705.model import Model
from tcb705.planner import _plan
from tcb705.short_stroke import rounded_sdk_nodes, validate_segments
from tcb705 import web_executor as W
from tcb705.sdk_motion import SdkMotion


class ExecutionPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = config(); cls.m = Model(cls.c)
        cls.q = cls.m.from_sdk(cls.c['execution']['web_program']['home']['joint_degrees'])
        cls.result = _plan(task('heng', 40, cls.c), cls.c, cls.q, _geometry_only=True)
        cls.nodes = rounded_sdk_nodes(nodes_of(cls.result))

    def no_verification(self):
        stack = ExitStack()
        for owner, name in [(W, '_joint_merge_candidates'), (W, 'joint_block_error'),
                            (Model, 'fk_batch')]:
            stack.enter_context(patch.object(owner, name, side_effect=AssertionError('runtime FK check')))
        stack.enter_context(patch('calligraphy.execution.refine_merged', side_effect=AssertionError('brush recheck')))
        return stack

    def test_brush_prepare_merges_verified_blocks_at_gui_speed(self):
        # 2026-10-25: one SDK move per IK knot kept the arm far below the GUI
        # speed, so brush pages are merged again (FK-checked, 0.02 mm near paper).
        before = copy.deepcopy(self.nodes)
        prepared = W.prepare_joint(self.c, self.nodes)
        _, chunks = W.build(self.c, self.nodes, W.settings(self.c), joint_keep=prepared.keep)
        self.assertEqual(self.nodes, before)
        n = len(self.nodes['positions_m']); keep = list(prepared.keep)
        self.assertEqual((keep[0], keep[-1]), (0, n - 1)); self.assertEqual(keep, sorted(set(keep)))
        self.assertLess(len(keep), n / 2)
        blocks = [b for chunk in chunks for b in chunk['content']['programs'][0]['codeBlock'] if b['fc'] != 'end']
        np.testing.assert_allclose([b['code']['endp'] for b in blocks], np.round(np.asarray(self.nodes['sdk_degrees'])[keep[1:]],4), rtol=0, atol=1e-12)
        self.assertTrue(all(b['code']['speed'] == W.settings(self.c)['draw_speed_pct'] and b['code']['delay'] == 0 for b in blocks))

    def test_unmerged_preparation_keeps_all_rounded_nodes_without_fk(self):
        with self.no_verification():
            prepared = W.prepare_joint(self.c, self.nodes, merge=False)
            probes = validate_segments(self.c, self.nodes, prepared.keep, self.m)
        self.assertEqual(prepared.keep, tuple(range(len(self.nodes['positions_m']))))
        self.assertEqual(prepared.error_mm, (None, None)); self.assertEqual(probes, 0)

    def test_actual_handwriting_compiler_does_not_recheck_ik_geometry(self):
        raw = [[.2,.3],[.8,.3]]
        with self.no_verification():
            result = compile_stroke(recognize(raw), raw, 60, self.c, self.m, self.q, 'ready', lambda:False)
        self.assertEqual(result.prepared.keep, tuple(range(len(result.nodes['sdk_degrees']))))
        self.assertIsNone(result.metrics['near_error_mm'])
        self.assertEqual(result.metrics['collision_probes'], 0)

    def test_invalid_node_limits_cancellation_and_shortcuts_still_rejected(self):
        for bad in (float('nan'), float('inf'), 100000.):
            nodes = copy.deepcopy(self.nodes); nodes['sdk_degrees'][5][2] = bad
            with self.subTest(bad=bad), self.assertRaises(W.ExecutionError):
                W.prepare_joint(self.c, nodes)
        with self.assertRaises(W.CancelledByUser):W.prepare_joint(self.c, self.nodes, lambda:True)
        with self.assertRaisesRegex(ValueError, 'JOINT_NODES_REQUIRED'):
            validate_segments(self.c, self.nodes, [0,len(self.nodes['positions_m'])-1], self.m)

    def test_exact_moves_wait_without_per_block_speed_or_sleep(self):
        c = copy.deepcopy(self.c); c['execution']['sdk']['queue_depth'] = 4
        ready = W.prepare_joint(c, self.nodes)
        _, chunks = W.build(c, self.nodes, W.settings(c), joint_keep=ready.keep)
        content = chunks[0]['content']
        blocks = [b for b in content['programs'][0]['codeBlock'] if b['fc'] != 'end']
        self.assertTrue(all(b['code']['smooth'] == 0 for b in blocks))
        sdk = Mock(); sdk.move.side_effect = range(10, 10000)
        completed = set()
        sdk.finished.side_effect = lambda seq: True if seq in completed else None
        sdk.set_speed.side_effect = lambda p:p
        sleep = Mock(side_effect=AssertionError('new per-block sleep'))
        motion = SdkMotion(sdk, Mock(), c, sleep=sleep)
        motion.set_speed(40); self.assertTrue(motion.start(content, lambda:False))
        # smooth=0 is interrupting in the SDK, so these exact moves must be
        # isolated. Blended lookahead is covered in test_sdk_queue_barrier.
        for count in range(1, len(blocks) + 1):
            self.assertEqual(sdk.move.call_count, count)
            self.assertFalse(motion.idle())
            motion.pump()
            self.assertEqual(sdk.move.call_count, count)
            completed.add(9 + count)
            motion.pump()
        self.assertTrue(motion.idle())
        sdk.set_speed.assert_called_once_with(40); sleep.assert_not_called()



if __name__ == '__main__':unittest.main()
