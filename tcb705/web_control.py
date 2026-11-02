"""Controller Web client for the ArmVision auto-mode program path (port 8010).

Verified on the real TCB705 (firmware 1.9.71) on 2026-10-17: hmcLine programs
(1 mm lift, 50 mm line, 30 mm circle) and one hmcRobotFree joint block (J7 +1 deg).
Flow: login -> /api/power auto -> servo check -> /api/mold/download -> shift ->
_phc_key 200 -> 100 -> feedback watch -> _phc_key 200, original mold, manual.
Credentials follow armvision_feedback.py (TCB_WEB_USER / TCB_WEB_PASSWORD).
"""
import hashlib
import ipaddress
import json
import math
import os
import time
import urllib.parse
import urllib.request

STATE_VARS = ('_phc_ctrlkey', '_phc_key', 'g_servo_statero_', '_phc_alarm_', 'g_state_')
HOME_MOLD = 'ArmVision_Draw'


class ControllerError(RuntimeError):
    pass


class Controller:
    def __init__(self, controller, robot_id, timeout=4.0):
        ip = ipaddress.ip_address(controller['remote_ip'])
        if ip.version != 4:
            raise ValueError('控制器地址需为 IPv4')
        port = controller.get('web_port', 8010)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('无效控制器 Web 端口')
        if type(robot_id) is not int or not 1 <= robot_id <= 32:
            raise ValueError('无效机器人 ID')
        self.base = 'http://%s:%d' % (ip, port)
        self.robot = robot_id
        self.timeout = timeout
        self.token = None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._vid = {}

    # ---- transport ----
    def request(self, path, data=None, timeout=None, check=True):
        headers = {'Content-Type': 'application/json', 'Connection': 'close'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        body = None if data is None else json.dumps(data).encode('utf-8')
        req = urllib.request.Request(self.base + path, data=body, headers=headers,
                                     method='GET' if data is None else 'POST')
        with self.opener.open(req, timeout=timeout or self.timeout) as response:
            raw = response.read(4 * 1048576 + 1)
        if len(raw) > 4 * 1048576:
            raise ControllerError('控制器返回数据过大')
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('gb18030')
        result = json.loads(text)
        if not isinstance(result, dict):
            raise ControllerError('控制器返回格式错误 ' + path.split('?')[0])
        if check and result.get('code') != 0:
            raise ControllerError('控制器拒绝 %s: %s' % (path.split('?')[0], json.dumps(result, ensure_ascii=False)[:300]))
        return result

    def login(self):
        user = os.environ.get('TCB_WEB_USER', 'szhc')
        password = os.environ.get('TCB_WEB_PASSWORD', 'szhcszhc')
        result = self.request('/api/user/login', {'name': user, 'password': hashlib.md5(password.encode('utf-8')).hexdigest()})
        data = result.get('data') if isinstance(result.get('data'), dict) else {}
        token = result.get('token') or data.get('token')
        if not isinstance(token, str) or not token:
            raise ControllerError('控制器登录未返回令牌')
        self.token = token
        return data

    # ---- variables ----
    def var(self, name):
        item = self.request('/api/var/byname?name=' + urllib.parse.quote(name)).get('data')
        if not isinstance(item, dict):
            raise ControllerError('控制器缺少变量 ' + name)
        if 'vid' in item:
            self._vid[name] = item['vid']
        return item

    def value(self, name):
        return str(self.var(name).get('value', ''))

    def number(self, name):
        v = self.var(name).get('value')
        if v in (None, '') or isinstance(v, bool):
            raise ControllerError('无效反馈 ' + name)
        v = float(v)
        if not math.isfinite(v):
            raise ControllerError('反馈不是有限数 ' + name)
        return v

    def set_var(self, name, value):
        vid = self._vid.get(name)
        if vid is None:
            vid = self.var(name)['vid']
        return self.request('/api/var/update', {'vid': vid, 'value': value})

    def state(self):
        return {n: self.value(n) for n in STATE_VARS}

    def axis_count(self):
        return int(self.number('r_axis_num_%d_' % self.robot))

    def pose(self):
        return [self.number('r_world_fb_pos_%d_%d_' % (self.robot, i)) for i in range(6)]

    def joints(self, n=7):
        return [self.number('r_joint_fb_pos_%d_%d_' % (self.robot, i)) for i in range(n)]

    def active_alarms(self):
        rows = self.request('/api/log/alarm').get('data', [])
        if not isinstance(rows, list):
            return []
        return [{k: r.get(k) for k in ('number', 'desc', 'detail')} for r in rows
                if isinstance(r, dict) and str(r.get('history', '')) == '0']

    def strict_active_alarms(self):
        """Homing must distinguish an empty alarm list from an unreadable/malformed response."""
        response = self.request('/api/log/alarm')
        if not isinstance(response, dict) or not isinstance(response.get('data'), list):
            raise ControllerError('报警反馈格式无效，无法确认归位条件')
        rows = response['data']
        if any(not isinstance(row, dict) or type(row.get('history')) not in (int, str) or
               str(row['history']) not in ('0', '1') for row in rows):
            raise ControllerError('报警记录状态不完整，无法确认归位条件')
        return [{k: row.get(k) for k in ('number', 'desc', 'detail')} for row in rows
                if str(row['history']) == '0']

    # ---- program path ----
    def power(self, mode):
        if mode not in ('auto', 'manual'):
            raise ValueError('mode must be auto/manual')
        return self.request('/api/power', {'mode': mode})

    def load_program(self, mold, content):
        self.request('/api/mold/download', {'mold': mold, 'content': content}, timeout=30)
        self.request('/api/mold/shift', {'mold': mold}, timeout=12)
        for path, data in (('/api/mold/cache', {'name': mold, 'data': content}), ('/api/mold/reset-ended', {})):
            try:
                self.request(path, data, timeout=20, check=False)
            except (OSError, ValueError):
                pass

    def run_key(self, running):
        return self.set_var('_phc_key', '100' if running else '200')

    def stop(self):
        """Stop request; returns list of (name, ok, error). Physical E-stop remains primary."""
        out = []
        for name, fn in (('run_key_200', lambda: self.run_key(False)),
                         ('robot_clear', lambda: self.request('/api/robot/clear', {'robot': self.robot, 'emergency_stop': True}))):
            try:
                fn(); out.append((name, True, ''))
            except Exception as exc:  # noqa: BLE001 - every stop path is attempted
                out.append((name, False, str(exc)))
        return out

    def restore(self, mold=HOME_MOLD, manual=True):
        """manual=False leaves the controller in auto: the auto->manual switch drops the arm 7-15 mm."""
        out = []
        steps = [('run_key_200', lambda: self.run_key(False)),
                 ('mold_' + mold, lambda: self.request('/api/mold/shift', {'mold': mold}, timeout=12))]
        if manual:
            steps.append(('power_manual', lambda: self.power('manual')))
        for name, fn in steps:
            try:
                fn(); out.append((name, True, ''))
            except Exception as exc:  # noqa: BLE001
                out.append((name, False, str(exc)))
        return out


def dist3(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def settle_pose(ctrl, n=5, tol_mm=0.05, timeout=6.0, interval=0.25, clock=time.monotonic, sleep=time.sleep,
                observe=None, context='机械臂'):
    hist = []; t0 = clock(); samples = 0; last_report = -math.inf
    while True:
        read_started = clock(); pose = ctrl.pose(); now = clock()
        if len(pose) < 6 or not all(math.isfinite(float(v)) for v in pose):
            raise ControllerError('%s静止确认失败：位置反馈无效' % context)
        hist = (hist + [pose])[-n:]; samples += 1
        spread = max(dist3(h, hist[-1]) for h in hist)
        elapsed = now - t0
        timed_out = elapsed >= timeout
        settled = len(hist) == n and spread < tol_mm and not timed_out
        if observe and (settled or timed_out or now - last_report >= 1.0):
            sample = dict(elapsed_s=round(elapsed, 3), timeout_s=timeout, samples=samples,
                          window_max_mm=round(spread, 6), tolerance_mm=tol_mm,
                          xyz_samples_mm=[list(h[:3]) for h in hist],
                          read_s=round(now-read_started, 3), settled=settled, timed_out=timed_out)
            observe(sample)
            # Observers may read controller health. A slow HTTP reply must not
            # turn feedback obtained before the deadline into late permission.
            elapsed = clock() - t0
            if elapsed >= timeout and not timed_out:
                timed_out = True; settled = False
                observe(dict(sample, elapsed_s=round(elapsed, 3), settled=False, timed_out=True))
            last_report = clock()
        if settled:
            return hist[-1]
        if timed_out:
            raise ControllerError('%s静止确认超时（%.1f 秒，最近 %d 点最大偏差 %.3f mm，要求小于 %.3f mm）' %
                                  (context, elapsed, len(hist), spread, tol_mm))
        sleep(min(interval, timeout-elapsed))
