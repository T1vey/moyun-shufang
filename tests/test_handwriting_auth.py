"""Handwriting auth recovery and enable ordering; mocked transport, no robot IO."""
from contextlib import ExitStack
import io
import json
import socket
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import urlsplit

from handwriting.executor import HandwritingController, RobotSession
from tcb705.web_control import ControllerError


def response(document):
    return io.BytesIO(json.dumps(document).encode('utf-8'))


def unauthorized(path, **body):
    return HTTPError('http://192.0.2.1:8010' + path, 401, 'Unauthorized', {},
                     response(body or {'message': 'session expired'}))


class ReadAuthTests(unittest.TestCase):
    def controller(self, replies):
        ctrl = HandwritingController({'remote_ip': '192.0.2.1'}, 1)
        ctrl.token = 'expired-test-token'
        ctrl.opener = Mock()
        ctrl.opener.open.side_effect = replies
        return ctrl

    @staticmethod
    def requests(ctrl):
        return [call.args[0] for call in ctrl.opener.open.call_args_list]

    def test_known_get_401_refreshes_once_and_uses_new_token(self):
        for path in ('/api/var/byname?name=g_state_', '/api/log/alarm'):
            with self.subTest(path=path):
                expected = {'code': 0, 'data': {'value': '1'}}
                ctrl = self.controller([
                    unauthorized(path),
                    response({'code': 0, 'data': {'token': 'fresh-test-token'}}),
                    response(expected),
                ])
                self.assertEqual(ctrl.request(path), expected)
                requests = self.requests(ctrl)
                self.assertEqual([r.method for r in requests], ['GET', 'POST', 'GET'])
                self.assertEqual(urlsplit(requests[1].full_url).path, '/api/user/login')
                self.assertEqual(requests[0].full_url, requests[2].full_url)
                self.assertEqual(requests[2].get_header('Authorization'), 'Bearer fresh-test-token')
                self.assertEqual(ctrl.token, 'fresh-test-token')

    def test_persistent_401_has_one_refresh_and_bounded_diagnostic(self):
        path = '/api/var/byname?name=g_state_'
        ctrl = self.controller([
            unauthorized(path),
            response({'code': 0, 'token': 'fresh-test-token'}),
            unauthorized(path, message='access denied', token='must-not-be-logged'),
        ])
        with self.assertRaises(ControllerError) as caught:
            ctrl.request(path)
        self.assertEqual(str(caught.exception), 'HTTP 401 GET /api/var/byname: access denied')
        self.assertNotIn('must-not-be-logged', str(caught.exception))
        self.assertEqual(ctrl.opener.open.call_count, 3)

    def test_login_failure_does_not_recurse(self):
        path = '/api/log/alarm'
        ctrl = self.controller([unauthorized(path), unauthorized('/api/user/login')])
        with self.assertRaisesRegex(ControllerError, 'HTTP 401 POST /api/user/login'):
            ctrl.request(path)
        self.assertEqual(ctrl.opener.open.call_count, 2)

    def test_unknown_get_is_not_retried(self):
        ctrl = self.controller([unauthorized('/api/unknown')])
        with self.assertRaisesRegex(ControllerError, 'HTTP 401 GET /api/unknown'):
            ctrl.request('/api/unknown')
        self.assertEqual(ctrl.opener.open.call_count, 1)

    def test_power_post_401_is_never_retried(self):
        ctrl = self.controller([unauthorized('/api/power', msg='expired')])
        with self.assertRaisesRegex(ControllerError, 'HTTP 401 POST /api/power: expired'):
            ctrl.power('auto')
        requests = self.requests(ctrl)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].method, 'POST')
        self.assertEqual(json.loads(requests[0].data), {'mode': 'auto'})

    def test_power_post_timeout_is_never_retried(self):
        ctrl = self.controller([socket.timeout('response lost')])
        with self.assertRaisesRegex(socket.timeout, 'response lost'):
            ctrl.power('auto')
        self.assertEqual(ctrl.opener.open.call_count, 1)


class PreparationOrderTests(unittest.TestCase):
    def fixture(self, stack, power_error=None, enabled=False):
        events = []

        def record(name, value=None):
            def invoke(*args, **kwargs):
                events.append(name)
                return value
            return invoke

        def power(mode):
            self.assertEqual(mode, 'auto')
            events.append('power')
            if power_error is not None:
                raise power_error

        pose = [0., 0., 300., 180., 0., 0.]
        state = {'_phc_ctrlkey': '100' if enabled else '0',
                 'g_servo_statero_': '1' if enabled else '0',
                 '_phc_alarm_': '0', 'g_state_': '1'}
        ctrl = SimpleNamespace(login=Mock(side_effect=record('login')),
            axis_count=Mock(return_value=7), state=Mock(return_value=state),
            strict_active_alarms=Mock(return_value=[]), pose=Mock(return_value=pose),
            power=Mock(side_effect=power))
        motion = Mock()
        motion.__enter__ = Mock(side_effect=record('motion_owner'))
        motion.set_speed.side_effect = record('speed')
        bot = RobotSession.__new__(RobotSession)
        bot.config = {'calibration_verified': True, 'sdk_mapping_verified': True,
                      'controller': {}, 'robot_id': 1}
        bot.s = {'enabled': True, 'mode': 'joint', 'draw_speed_pct': 60,
                 'max_power_on_shift_mm': 2}
        bot.wait_feedback = Mock(side_effect=record('feedback'))
        bot.wait_enabled = Mock(side_effect=record('enabled'))
        bot.home = Mock(side_effect=record('home', 'prepared'))
        overrides = {
            'sdk_enabled': lambda c: True, 'home_enabled': lambda c: True,
            'mapping_required': lambda c: True, 'profile': lambda *a, **k: None,
            'open_client': record('connect', (object(), {})),
            'HandwritingController': lambda *a, **k: ctrl,
            'SdkMotion': lambda *a, **k: motion,
            'require_mode_switch_clearance': record('clearance'),
            'settle_pose': record('settled', pose),
            'require_home_ready': record('home_ready'),
        }
        stack.enter_context(patch.multiple('handwriting.executor', **overrides))
        return bot, ctrl, motion, events

    def test_sdk_ready_then_login_then_single_enable_then_speed_and_home(self):
        with ExitStack() as stack:
            bot, ctrl, motion, events = self.fixture(stack)
            stages = []
            self.assertEqual(bot.prepare(lambda: False, stages.append), 'prepared')
            self.assertEqual(events, ['connect', 'feedback', 'login', 'motion_owner',
                'clearance', 'power', 'enabled', 'settled', 'home_ready', 'speed', 'home'])
            ctrl.power.assert_called_once_with('auto')
            motion.set_speed.assert_called_once_with(60)
            self.assertEqual(stages, ['CONNECT', 'WAIT_FEEDBACK', 'AUTHENTICATE',
                'ENABLE_REQUEST', 'ENABLE_WAIT', 'HOME'])

    def test_power_failure_does_not_replay_or_proceed_to_home(self):
        for error in (ControllerError('HTTP 401 POST /api/power'), socket.timeout('lost response')):
            with self.subTest(error=type(error).__name__), ExitStack() as stack:
                bot, ctrl, motion, events = self.fixture(stack, power_error=error)
                with self.assertRaises(type(error)):
                    bot.prepare(lambda: False, lambda stage: None)
                ctrl.power.assert_called_once_with('auto')
                ctrl.login.assert_called_once_with()
                bot.wait_enabled.assert_not_called()
                motion.set_speed.assert_not_called()
                bot.home.assert_not_called()
                self.assertEqual(events[-1], 'power')

    def test_already_enabled_skips_power_and_keeps_ready_checks(self):
        with ExitStack() as stack:
            bot, ctrl, motion, events = self.fixture(stack, enabled=True)
            self.assertEqual(bot.prepare(lambda: False, lambda stage: None), 'prepared')
            ctrl.power.assert_not_called()
            self.assertEqual(events, ['connect', 'feedback', 'login', 'motion_owner',
                'home_ready', 'speed', 'home'])


if __name__ == '__main__':
    unittest.main()
