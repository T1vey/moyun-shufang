"""Longer SDK acceleration ramp for start/home moves (offline; no controller, no motion)."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_handwriting import config                                   # noqa: E402
from handwriting.recognizer import recognize                           # noqa: E402
from handwriting.planner import compile_stroke                         # noqa: E402
from tcb705.model import Model                                          # noqa: E402
from tcb705.planner import PHASE                                        # noqa: E402
from tcb705.sdk_motion import SdkMotion, sdk_settings                   # noqa: E402
from tcb705.web_executor import build, settings, home_program, ProgramMotion  # noqa: E402


class RecordingSdk:
    def __init__(self):
        self.moves = []
    def move(self, kind, values, smooth=0, acc=0.0, dec=0.0, ratio=0.0):
        self.moves.append(dict(kind=kind, smooth=smooth, acc=acc, dec=dec))
        return 0                                   # completed synchronously
    def finished(self, seq):
        return True


def program(blocks):
    return {'name': 'm', 'programs': [{'codeBlock': blocks + [{'fc': 'end'}]}]}


class RampTests(unittest.TestCase):
    def setUp(self):
        self.c = config()

    def test_defaults_and_validation(self):
        s = sdk_settings(self.c)
        self.assertEqual((s['air_acc_time'], s['air_dec_time']), (0.6, 0.6))
        self.assertEqual((s['acc_time'], s['dec_time']), (0.0, 0.0))
        for bad in (0.05, 1.2, -1):
            c = copy.deepcopy(self.c); c['execution']['sdk']['air_acc_time'] = bad
            with self.assertRaises(ValueError):
                sdk_settings(c)
        c = copy.deepcopy(self.c); c['execution']['sdk'].update(air_acc_time=0, air_dec_time=1.0)
        self.assertEqual(sdk_settings(c)['air_acc_time'], 0)

    def test_only_marked_moves_get_the_ramp(self):
        blocks = [{'fc': 'hmcRobotFree', 'code': {'endp': [0] * 7, 'smooth': 0}, 'sdk_ramp': 'air'},
                  {'fc': 'hmcRobotFree', 'code': {'endp': [0] * 7, 'smooth': 0}},
                  {'fc': 'hmcLine', 'code': {'endp': [0] * 6, 'smooth': 0}, 'sdk_ramp': 'air'}]
        sdk = RecordingSdk(); m = SdkMotion(sdk, None, self.c, queue_depth=4)
        m.start(program(blocks), lambda: False)
        while m.pending:
            m.pump()
        self.assertEqual([(x['acc'], x['dec']) for x in sdk.moves], [(0.6, 0.6), (0.0, 0.0), (0.6, 0.6)])

    def test_home_program_is_marked_only_for_sdk(self):
        s = settings(self.c); here = [-430.0, 0.0, 330.0, 180.0, 0.0, 180.0]
        content, _, _ = home_program(self.c, s, here)
        blocks = [b for b in content['programs'][0]['codeBlock'] if b['fc'] != 'end']
        self.assertTrue(blocks and all(b.get('sdk_ramp') == 'air' for b in blocks))
        c = copy.deepcopy(self.c); c['execution']['sdk']['enabled'] = False
        content, _, _ = home_program(c, settings(c), here)
        self.assertFalse(any('sdk_ramp' in b for b in content['programs'][0]['codeBlock']))

    def test_drawing_marks_only_approach_and_finish(self):
        m = Model(self.c); q = m.from_sdk(self.c['execution']['web_program']['home']['joint_degrees'])
        raw = [[.12, .3], [.3, .29], [.62, .31], [.86, .28]]
        p = compile_stroke(recognize(raw), raw, 60, self.c, m, q, 'ready', lambda: False)
        _, chunks = build(self.c, p.nodes, settings(self.c), joint_keep=p.prepared.keep)
        phase = p.nodes['interval_phase']; seen = set()
        for ch in chunks:
            body = [b for b in ch['content']['programs'][0]['codeBlock'] if b['fc'] != 'end']
            for i, b in zip(ch['node_index'], body):
                ph = phase[i - 1]; seen.add(ph)
                self.assertEqual(b.get('sdk_ramp') == 'air', ph in (PHASE['APPROACH'], PHASE['FINISH']))
        self.assertIn(PHASE['DRAW'], seen)

    def test_controller_program_never_receives_the_marker(self):
        sent = []
        class Ctrl:
            def load_program(self, name, content): sent.append(content)
            def run_key(self, on): pass
        content = program([{'fc': 'hmcLine', 'code': {'endp': [0] * 6}, 'sdk_ramp': 'air'}])
        ProgramMotion(Ctrl(), dict(mold='m'), lambda s: None).start(content, lambda: False)
        self.assertFalse(any('sdk_ramp' in b for b in sent[0]['programs'][0]['codeBlock']))
        self.assertIn('sdk_ramp', content['programs'][0]['codeBlock'][0])     # caller's copy untouched


class PausingSdk:
    """Records stop-related calls; pause settles after `settle_polls` STATE reads."""
    def __init__(self, settle_polls=2, pause_fails=False, clear_fails=False):
        self.calls = []; self.polls = 0; self.settle = settle_polls
        self.pause_fails, self.clear_fails = pause_fails, clear_fails
    def pause(self, on):
        self.calls.append(('pause', on))
        if self.pause_fails and on:
            raise RuntimeError('pause refused')
    def state(self):
        self.polls += 1
        return dict(move=1, paused=self.polls >= self.settle, link=True)
    def stop(self, emergency=True):
        self.calls.append(('clear', emergency))
        if self.clear_fails:
            raise RuntimeError('clear refused')


class Ctrl:
    def stop(self):
        return [('web_stop', True, '')]


class SoftStopTests(unittest.TestCase):
    def motion(self, sdk):
        return SdkMotion(sdk, Ctrl(), config(), sleep=lambda s: None)

    def test_user_stop_decelerates_then_clears(self):
        sdk = PausingSdk()
        out = self.motion(sdk).stop(soft=True)
        self.assertEqual(sdk.calls, [('pause', True), ('clear', True), ('pause', False)])
        self.assertTrue(all(r[1] is True for r in out))
        self.assertEqual([r[0] for r in out], ['sdk_soft_pause', 'sdk_clear_route', 'sdk_unpause', 'web_stop'])

    def test_fault_stop_is_immediate(self):
        sdk = PausingSdk()
        self.motion(sdk).stop()
        self.assertEqual(sdk.calls, [('clear', True)])

    def test_pause_not_settling_falls_back_to_immediate_clear(self):
        sdk = PausingSdk(settle_polls=10 ** 9); m = self.motion(sdk)
        out = m.stop(soft=True, settle_s=0.0)
        # Cleared at once, and the pause request is released so later moves are not stuck.
        self.assertEqual(sdk.calls, [('pause', True), ('clear', True), ('pause', False)])
        self.assertTrue(all(r[1] is True for r in out))          # stop confirmed by the clear
        self.assertIn('SDK_PAUSE_TIMEOUT', m.soft_stop_detail)

    def test_refused_pause_still_clears_and_confirms(self):
        sdk = PausingSdk(pause_fails=True); m = self.motion(sdk)
        out = m.stop(soft=True)
        self.assertEqual(sdk.calls[:2], [('pause', True), ('clear', True)])
        self.assertTrue(all(r[1] is True for r in out))
        self.assertEqual(m.soft_stop_detail, 'pause refused')

    def test_sdk_without_pause_support_behaves_like_before(self):
        class OldSdk:
            def __init__(self): self.calls = []
            def stop(self, emergency=True): self.calls.append(('clear', emergency))
        sdk = OldSdk(); out = self.motion(sdk).stop(soft=True)
        self.assertEqual(sdk.calls, [('clear', True)])
        self.assertEqual([r[0] for r in out], ['sdk_clear_route', 'web_stop'])

    def test_failed_clear_keeps_the_arm_paused(self):
        sdk = PausingSdk(clear_fails=True)
        out = self.motion(sdk).stop(soft=True)
        self.assertNotIn(('pause', False), sdk.calls)
        self.assertIn(('sdk_clear_route', False, 'clear refused'), out)

    def test_stop_motion_helper(self):
        from tcb705.web_executor import stop_motion
        sdk = PausingSdk(); m = self.motion(sdk)
        stop_motion(m, True); self.assertEqual(sdk.calls[0], ('pause', True))
        sdk.calls.clear(); stop_motion(m, False); self.assertEqual(sdk.calls, [('clear', True)])
        class Legacy:
            def stop(self):
                return ['legacy']
        self.assertEqual(stop_motion(Legacy(), True), ['legacy'])


if __name__ == '__main__':
    unittest.main()
