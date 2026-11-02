"""SDK queue boundaries against documented smooth=0 interruption semantics.

No socket, vendor library or hardware is used. Unlike an always-successful fake,
this fake aborts unfinished paths when a smooth=0 command is sent too early.
"""
import unittest

from tcb705.sdk_motion import SdkError, SdkMotion


class InterruptingSDK:
    def __init__(self, synchronous_moves=()):
        self.next_sequence = 10
        self.moves = []
        self.ends = {}
        self.inflight = []
        self.interrupted = []
        self.synchronous_moves = set(synchronous_moves)
        self.speed_updates = []

    def move(self, kind, values, smooth=0, acc=0.0, dec=0.0, ratio=0.0):
        if smooth == 0 and self.inflight:
            self.interrupted.extend(self.inflight)
            for sequence in self.inflight:
                self.ends[sequence] = False
            self.inflight.clear()
        index = len(self.moves)
        sequence = 0 if index in self.synchronous_moves else self.next_sequence
        self.moves.append(dict(kind=kind, values=list(values), smooth=smooth, acc=acc,
                               dec=dec, ratio=ratio, sequence=sequence))
        if sequence:
            self.next_sequence += 1
            self.inflight.append(sequence)
        return sequence

    def finished(self, sequence):
        return self.ends.get(sequence)

    def complete(self, sequence=None, success=True):
        sequence = self.inflight[0] if sequence is None else sequence
        if sequence not in self.inflight:
            raise AssertionError('Cannot finish an inactive fake move')
        self.ends[sequence] = success
        self.inflight.remove(sequence)

    def complete_all(self):
        for sequence in self.inflight[:]:
            self.complete(sequence)

    def set_speed(self, percent):
        self.speed_updates.append(percent)
        return percent


def config():
    return dict(execution=dict(
        sdk=dict(enabled=True, queue_depth=1, acc_time=.2, dec_time=.3),
        web_program=dict(mode='joint', draw_speed_pct=75, air_speed_pct=75)))


def program(smoothing, kinds=None):
    kinds = kinds or ['J'] * len(smoothing)
    blocks = []
    for index, (smooth, kind) in enumerate(zip(smoothing, kinds)):
        blocks.append(dict(fc='hmcLine' if kind == 'L' else 'hmcRobotFree',
                           code=dict(endp=[float(index)] * (6 if kind == 'L' else 7),
                                     smooth=smooth, speed=5, brush_feed_ratio=.1)))
    return dict(programs=[dict(codeBlock=blocks + [dict(fc='end')])])


class QueueBarrierTests(unittest.TestCase):
    def motion(self, sdk=None, depth=4):
        sdk = sdk or InterruptingSDK()
        return sdk, SdkMotion(sdk, None, config(), queue_depth=depth)

    def drain(self, sdk, motion):
        for _ in range(30):
            motion.pump()
            if motion.idle():
                self.assertEqual(sdk.inflight, [])
                return
            if sdk.inflight:
                sdk.complete()
        self.fail('Fake queue did not drain')

    def test_home_zero_smoothing_moves_run_one_at_a_time(self):
        sdk, motion = self.motion()
        self.assertTrue(motion.start(program([0, 0, 0], ['L', 'L', 'J']), lambda: False))
        for index, kind in enumerate(['L', 'L', 'J']):
            self.assertEqual(len(sdk.moves), index + 1)
            self.assertEqual((sdk.moves[-1]['kind'], sdk.moves[-1]['smooth']), (kind, 0))
            motion.pump()  # Waiting cannot send the next exact-stop target.
            self.assertEqual(len(sdk.moves), index + 1)
            self.assertFalse(motion.idle())
            sdk.complete()
            motion.pump()
        self.assertTrue(motion.idle())
        self.assertEqual(sdk.interrupted, [])

    def test_mixed_smoothing_waits_before_and_after_exact_stop(self):
        sdk, motion = self.motion()
        motion.start(program([3, 3, 0, 3]), lambda: False)
        self.assertEqual([move['smooth'] for move in sdk.moves], [3, 3])
        sdk.complete()
        motion.pump()
        self.assertEqual(len(sdk.moves), 2)  # One prior smooth segment still runs.
        sdk.complete()
        motion.pump()
        self.assertEqual([move['smooth'] for move in sdk.moves], [3, 3, 0])
        motion.pump()
        self.assertEqual(len(sdk.moves), 3)  # Do not blend a successor through this stop.
        sdk.complete()
        motion.pump()
        self.assertEqual([move['smooth'] for move in sdk.moves], [3, 3, 0, 3])
        self.drain(sdk, motion)
        self.assertEqual(sdk.interrupted, [])

    def test_final_zero_waits_for_all_smooth_segments(self):
        sdk, motion = self.motion()
        motion.start(program([3] * 6 + [0]), lambda: False)
        self.assertEqual(len(sdk.moves), 4)
        sdk.complete_all()
        motion.pump()
        self.assertEqual(len(sdk.moves), 6)
        self.assertEqual(len(sdk.inflight), 2)
        motion.pump()
        self.assertEqual(len(sdk.moves), 6)
        sdk.complete_all()
        motion.pump()
        self.assertEqual(len(sdk.moves), 7)
        self.assertEqual(sdk.moves[-1]['smooth'], 0)
        self.drain(sdk, motion)
        self.assertEqual(sdk.interrupted, [])

    def test_failed_callback_is_not_success_or_a_motion_retry(self):
        sdk, motion = self.motion()
        motion.start(program([3, 3, 0, 3]), lambda: False)
        failed = sdk.inflight[0]
        sdk.complete(failed, success=False)
        self.assertFalse(motion.idle())
        before = list(sdk.moves)
        for _ in range(2):
            with self.assertRaisesRegex(SdkError, r'SDK_MOTION_FAILED.*sequence %d' % failed):
                motion.pump()
            self.assertEqual(sdk.moves, before)

    def test_failed_final_callback_does_not_count_as_idle(self):
        sdk, motion = self.motion()
        motion.start(program([0]), lambda: False)
        sdk.complete(success=False)
        self.assertFalse(motion.idle())
        with self.assertRaisesRegex(SdkError, 'SDK_MOTION_FAILED'):
            motion.pump()
        self.assertEqual(len(sdk.moves), 1)

    def test_synchronous_zero_sequence_needs_no_callback_barrier(self):
        sdk, motion = self.motion(InterruptingSDK(synchronous_moves={0, 2}))
        motion.start(program([0, 3, 0, 3]), lambda: False)
        self.drain(sdk, motion)
        self.assertEqual([move['smooth'] for move in sdk.moves], [0, 3, 0, 3])
        self.assertEqual([move['sequence'] for move in sdk.moves], [0, 10, 0, 11])
        self.assertNotIn(0, motion.sent)
        self.assertEqual(sdk.interrupted, [])

    def test_cancelled_start_does_not_send_any_move(self):
        sdk, motion = self.motion()
        self.assertFalse(motion.start(program([0, 3, 0]), lambda: True))
        self.assertEqual(sdk.moves, [])
        self.assertEqual(sdk.inflight, [])

    def test_smooth_run_still_uses_four_outstanding_commands(self):
        sdk, motion = self.motion()
        motion.start(program([3] * 9), lambda: False)
        self.assertEqual(len(sdk.moves), 4)
        self.assertEqual(len(sdk.inflight), 4)
        sdk.complete()
        motion.pump()
        self.assertEqual(len(sdk.moves), 5)
        self.assertEqual(len(sdk.inflight), 4)
        self.drain(sdk, motion)
        self.assertEqual([move['smooth'] for move in sdk.moves], [3] * 9)

    def test_immediate_async_callbacks_keep_each_pump_bounded(self):
        class ImmediateCallbackSDK(InterruptingSDK):
            def move(self, *args, **kwargs):
                sequence = super().move(*args, **kwargs)
                self.complete(sequence)
                return sequence

        sdk, motion = self.motion(ImmediateCallbackSDK())
        motion.start(program([3] * 13), lambda: False)
        self.assertEqual(len(sdk.moves), 4)
        self.assertTrue(all(move['sequence'] >= 10 for move in sdk.moves))
        self.assertFalse(motion.idle())
        for expected in (8, 12, 13):
            before = len(sdk.moves)
            motion.pump()
            self.assertEqual(len(sdk.moves), expected)
            self.assertLessEqual(len(sdk.moves) - before, 4)
        self.assertTrue(motion.idle())
        self.assertEqual(sdk.interrupted, [])

    def test_synchronous_successes_keep_each_pump_bounded(self):
        sdk, motion = self.motion(InterruptingSDK(synchronous_moves=range(13)))
        motion.start(program([3] * 13), lambda: False)
        self.assertEqual(len(sdk.moves), 4)
        self.assertFalse(motion.idle())
        for expected in (8, 12, 13):
            before = len(sdk.moves)
            motion.pump()
            self.assertEqual(len(sdk.moves), expected)
            self.assertLessEqual(len(sdk.moves) - before, 4)
        self.assertEqual([move['sequence'] for move in sdk.moves], [0] * 13)
        self.assertEqual(motion.sent, [])
        self.assertTrue(motion.idle())
        self.assertEqual(sdk.interrupted, [])

    def test_speed_acceleration_and_default_ratio_are_unchanged(self):
        sdk, motion = self.motion()
        self.assertEqual(motion.set_speed(75), 75)
        motion.start(program([3, 3, 0, 3]), lambda: False)
        self.drain(sdk, motion)
        self.assertEqual(sdk.speed_updates, [75])
        self.assertEqual(motion.speed_pct, 75)
        self.assertTrue(all(move['acc'] == .2 and move['dec'] == .3 and move['ratio'] == 0
                            for move in sdk.moves))
        self.assertEqual([move['values'][0] for move in sdk.moves], [0, 1, 2, 3])

    def test_default_depth_one_keeps_existing_exact_stop_behavior(self):
        sdk = InterruptingSDK()
        motion = SdkMotion(sdk, None, config())
        motion.start(program([3, 3, 0]), lambda: False)
        self.assertEqual(len(sdk.moves), 1)
        self.drain(sdk, motion)
        self.assertEqual([move['smooth'] for move in sdk.moves], [0, 0, 0])
        self.assertEqual(sdk.interrupted, [])


if __name__ == '__main__':
    unittest.main()
