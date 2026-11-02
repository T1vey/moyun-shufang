"""Huacheng SDK V2.4.1 motion path (2026-10-20, controller host >= 1.9.82).

The board's ARM32 libxoip.so has no Python binding, so motion goes through the small C++
server native/huacheng_bridge/sdk_server.cpp (build/tcb705/tcb_sdk_server), one text line
per request. The drawing plan, home sequence and every watchdog stay in web_executor:
SdkMotion only replaces "download a controller program + press run" by SDK commands.

  hmcRobotFree block -> RobotManager::moveJoints (local 7-axis IK joint angles, degrees)
  hmcLine block      -> RobotManager::moveLine   (controller world XYZUVW)
  speed              -> RobotManager::setGlobalSpeed(0..100), changeable while drawing
  stop               -> RobotManager::clearRobotRoute(emergency) + the Web stop as backup

At most `queue_depth` commands are outstanding (end callbacks count them down); a refused
command stops the drawing, it is never re-sent. Pose/state/alarm feedback and the
manual/auto switch still use the controller Web API (SDK getJoints returned no data on
this controller, 2026-10-20).
"""
import math
import os
import queue
import subprocess
import threading
import time
from .model import ROOT

DEFAULTS = dict(enabled=False, server='build/tcb705/tcb_sdk_server', local_ip='192.168.4.23', port=8001,
                queue_depth=1, acc_time=0.0, dec_time=0.0, reply_timeout_s=10.0, connect_timeout_s=20.0,
                # Start/home moves (blocks marked sdk_ramp='air'): a longer acceleration and
                # deceleration ramp so the arm does not jolt into motion.  The SDK exposes no
                # jerk or S-curve setting; accTime/decTime (0.1..1.0 s) is the supported knob.
                air_acc_time=0.6, air_dec_time=0.6)


class SdkError(RuntimeError):
    pass


def sdk_settings(config):
    s = dict(DEFAULTS); s.update(config.get('execution', {}).get('sdk', {}))
    if type(s['enabled']) is not bool:
        raise ValueError('execution.sdk.enabled 必须为布尔值')
    if not isinstance(s['server'], str) or not s['server']:
        raise ValueError('execution.sdk.server 必须为可执行文件路径')
    if not isinstance(s['local_ip'], str) or not s['local_ip']:
        raise ValueError('execution.sdk.local_ip 必须填写板子连控制器网口的地址')
    if type(s['port']) is not int or not 0 < s['port'] <= 65535:
        raise ValueError('execution.sdk.port 必须为 1..65535')
    if type(s['queue_depth']) is not int or not 1 <= s['queue_depth'] <= 50:
        raise ValueError('execution.sdk.queue_depth 必须为 1..50')
    for k in ('acc_time', 'dec_time', 'air_acc_time', 'air_dec_time'):
        v = float(s[k])
        if not (v == 0 or 0.1 <= v <= 1.0):
            raise ValueError('execution.sdk.%s 必须为 0（沿用控制器）或 0.1..1.0 秒' % k)
    for k in ('reply_timeout_s', 'connect_timeout_s'):
        if not 0 < float(s[k]) <= 120:
            raise ValueError('execution.sdk.%s 超出范围' % k)
    if s['enabled']:
        web = config.get('execution', {}).get('web_program', {})
        if web.get('mode') != 'joint':
            raise ValueError('SDK 执行需要 execution.web_program.mode=joint（下发本地 IK 关节角）')
    return s


def sdk_enabled(config):
    return config.get('execution', {}).get('sdk', {}).get('enabled') is True


def check_speed(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError('速度必须是 0..100 的数') from None
    if not math.isfinite(v) or not 0 < v <= 100:
        raise ValueError('速度必须在 1..100 之间（0 时机械臂不会运动）')
    return round(v, 1)


class SdkClient:
    """Line protocol client for tcb_sdk_server (or any process speaking the same protocol)."""

    def __init__(self, command, reply_timeout_s=10.0, env=None):
        self.timeout = float(reply_timeout_s)
        self.replies = queue.Queue(); self.done = {}; self.lock = threading.Lock()
        self.cond = threading.Condition(); self.closed = False
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                                     errors='replace', bufsize=1, env=env)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            if line.startswith('EVT DONE '):
                bits = line.split()
                with self.cond:
                    self.done[int(bits[2])] = bits[3] == '1'; self.cond.notify_all()
            elif line.startswith(('OK', 'ERR')):
                self.replies.put(line)
        self.replies.put('ERR SDK_SERVER_EXITED')

    def call(self, line, timeout=None):
        with self.lock:
            if self.proc.poll() is not None:
                raise SdkError('SDK_SERVER_EXITED: SDK 服务进程已退出')
            self.proc.stdin.write(line + '\n'); self.proc.stdin.flush()
            try:
                answer = self.replies.get(timeout=timeout or self.timeout)
            except queue.Empty:
                raise SdkError('SDK_TIMEOUT: %s 无应答' % line.split()[0]) from None
        if answer.startswith('ERR'):
            raise SdkError('SDK_' + line.split()[0] + ': ' + answer[4:])
        return answer[3:].split()

    def connect(self, local_ip, remote_ip, port, robot, timeout=20.0):
        bits = self.call('CONNECT %s %s %d %d' % (local_ip, remote_ip, port, robot), timeout=timeout)
        return dict(lib_version=bits[0] if bits else '', host_version=bits[1] if len(bits) > 1 else '')

    def set_speed(self, pct):
        return float(self.call('SPEED %.1f' % check_speed(pct))[0])

    def speed(self):
        return float(self.call('GETSPEED')[0])

    def move(self, kind, values, smooth=0, acc=0.0, dec=0.0, ratio=0.0):
        if kind not in ('J', 'L') or not all(math.isfinite(float(v)) for v in values):
            raise SdkError('SDK_TARGET: 目标无效')
        line = 'MOVE%s %d %.3f %.3f %.6f %s' % (kind, int(smooth), acc, dec, ratio, ' '.join('%.4f' % float(v) for v in values))
        return int(self.call(line)[0])

    def finished(self, seq):
        with self.cond:
            return self.done.get(seq)

    def state(self):
        m, paused, link = self.call('STATE')
        return dict(move=int(m), paused=paused == '1', link=link == '1')

    def pause(self, on):
        self.call('PAUSE %d' % (1 if on else 0))

    def stop(self, emergency=True):
        self.call('STOP %d' % (1 if emergency else 0))

    def alarms(self):
        bits = self.call('ALARM')
        return [] if bits[0] == '0' else ' '.join(bits[1:]).split('|')

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.proc.poll() is None:
                self.call('QUIT', timeout=5)
        except (SdkError, OSError, ValueError):
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill(); self.proc.wait(timeout=5)


def open_client(config, command=None):
    """Start tcb_sdk_server and connect to the controller (no motion, no enable)."""
    s = sdk_settings(config)
    if command is None:
        exe = ROOT / s['server']
        if not exe.is_file():
            raise SdkError('SDK_SERVER_MISSING: 找不到 %s，请先在板子上运行 scripts/build_tcb705.py --sdk' % s['server'])
        command = [str(exe)]
    env = dict(os.environ)
    lib = str(ROOT / 'vendor/huacheng/armhf')
    env['LD_LIBRARY_PATH'] = lib + (':' + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    client = SdkClient(command, s['reply_timeout_s'], env=env)
    try:
        info = client.connect(s['local_ip'], config['controller']['remote_ip'], s['port'], config['robot_id'],
                              timeout=s['connect_timeout_s'])
    except Exception:
        client.close(); raise
    return client, info


# ---- live speed: the settings page / drawing page changes the speed while a drawing runs ----
_active = None
_active_lock = threading.Lock()


def live_speed(pct):
    """Apply a new global speed to the drawing that is running now. Returns the value read back,
    or None when no SDK drawing is running (the saved config is then used next time)."""
    v = check_speed(pct)
    with _active_lock:
        motion = _active
    if motion is None:
        return None
    return motion.set_speed(v)


class SdkMotion:
    """Executes web_executor's program blocks through the SDK; web_executor keeps watching the pose."""

    def __init__(self, sdk, ctrl, config, sleep=time.sleep, queue_depth=None):
        """queue_depth overrides execution.sdk.queue_depth for this motion only (live handwriting);
        blocks are blended (smooth > 0) only when more than one move is queued."""
        self.sdk = sdk; self.ctrl = ctrl; self.config = config; self.sleep = sleep
        self.s = sdk_settings(config); self.pending = []; self.sent = []; self.speed_pct = None
        self._barrier_seq = None
        self.soft_stop_detail = None
        if queue_depth is not None:
            if type(queue_depth) is not int or not 1 <= queue_depth <= 50:
                raise ValueError('queue_depth 必须为 1..50')
            self.s = dict(self.s, queue_depth=queue_depth)

    # web_executor calls these instead of load_program / run_key / stop
    def start(self, content, cancel):
        blocks = [b for b in content['programs'][0]['codeBlock'] if b['fc'] != 'end']
        cmds = []
        for b in blocks:
            code = b['code']
            # All drawing and home moves share the GUI's global speed. Legacy
            # brush_feed_ratio metadata must not override it with a slower ratio.
            air = b.get('sdk_ramp') == 'air'
            acc = float(self.s['air_acc_time'] if air else self.s['acc_time'])
            dec = float(self.s['air_dec_time'] if air else self.s['dec_time'])
            if b['fc'] == 'hmcRobotFree':
                cmds.append(('J', code['endp'], int(code.get('smooth', 0)), acc, dec))
            elif b['fc'] == 'hmcLine':
                cmds.append(('L', code['endp'], int(code.get('smooth', 0)), acc, dec))
            else:
                raise SdkError('SDK_BLOCK: 不支持的程序块 %s' % b['fc'])
        self.pending = cmds; self.sent = []; self._barrier_seq = None
        if cancel():
            return False
        self.pump()
        return True

    def pump(self):
        """Queue blended moves, but isolate exact moves before and after their callback.

        robot.h documents smooth=0 as interrupting the previous path. It is not
        a queued end marker: drain earlier moves before sending it, then wait
        for it to finish before allowing any later move. No extra dwell or speed
        override is added; smooth>0 moves retain the configured lookahead depth.
        """
        dispatched = 0
        while True:
            outstanding = 0
            for seq in self.sent:
                end = self.sdk.finished(seq)
                if end is None:
                    outstanding += 1
                elif end is False:
                    raise SdkError('SDK_MOTION_FAILED: 控制器报告运动未完成（sequence %d）' % seq)
            if self._barrier_seq is not None:
                if self.sdk.finished(self._barrier_seq) is not True:
                    return
                self._barrier_seq = None
            # Return to the owner's cancel/pose/watchdog checks even when the
            # controller finishes targets immediately (including seq=0).
            if (not self.pending or outstanding >= self.s['queue_depth'] or
                    dispatched >= self.s['queue_depth']):
                return
            kind, values, smooth, acc, dec = self.pending[0]
            smooth = smooth if self.s['queue_depth'] > 1 else 0
            if smooth == 0 and outstanding:
                return
            # Consume once only: a refused/failed request must never be replayed.
            self.pending.pop(0)
            seq = self.sdk.move(kind, values, smooth=smooth, acc=acc, dec=dec)
            dispatched += 1
            if seq >= 10:
                self.sent.append(seq)
                if smooth == 0:
                    self._barrier_seq = seq
            elif seq != 0:
                raise SdkError('SDK_REFUSED: 控制器拒绝运动指令（返回 %d）' % seq)
            # seq=0 completed synchronously; asynchronous failures and barriers
            # are checked again before sending anything else in this pump.

    def idle(self):
        return not self.pending and all(self.sdk.finished(seq) is True for seq in self.sent)

    def finish(self):
        self.pending = []

    supports_soft_stop = True

    def stop(self, soft=False, settle_s=2.0):
        """Clear the controller path.  soft=True (a user's stop) first decelerates with
        pauseRobot and waits until the controller reports standstill, so clearing the
        route no longer jolts the arm; on any failure or after settle_s it falls back to
        the immediate clear.  Faults call stop() and still stop at once."""
        self.pending = []
        out = []
        requested = False
        self.soft_stop_detail = None
        if soft:
            try:
                self.sdk.pause(True)
                requested = True        # unpause later only if the pause was accepted
                deadline = time.monotonic() + settle_s
                while not self.sdk.state()['paused']:
                    if time.monotonic() > deadline:
                        raise SdkError('SDK_PAUSE_TIMEOUT: 减速停未在 %.1f 秒内停稳' % settle_s)
                    self.sleep(0.02)
                out.append(('sdk_soft_pause', True, ''))
            except Exception as exc:  # noqa: BLE001 - fall back to the immediate clear
                # Only the deceleration is lost; the clear below is what confirms the stop,
                # so this is a note, not an unconfirmed stop step.
                self.soft_stop_detail = str(exc)[:200]
        cleared = False
        try:
            # Already at standstill when paused, so this immediate clear cannot jolt it.
            self.sdk.stop(True); cleared = True; out.append(('sdk_clear_route', True, ''))
        except Exception as exc:  # noqa: BLE001 - every stop path is attempted
            out.append(('sdk_clear_route', False, str(exc)))
        if requested and cleared:
            # Release any pause request once the route is gone, so later moves are not
            # left paused; nothing remains to resume.
            try:
                self.sdk.pause(False); out.append(('sdk_unpause', True, ''))
            except Exception as exc:  # noqa: BLE001
                out.append(('sdk_unpause', False, str(exc)))
        return out + self.ctrl.stop()

    def set_speed(self, pct):
        self.speed_pct = check_speed(pct)
        return self.sdk.set_speed(self.speed_pct)

    # registry for live_speed()
    def __enter__(self):
        global _active
        with _active_lock:
            _active = self
        return self

    def __exit__(self, *exc):
        global _active
        with _active_lock:
            if _active is self:
                _active = None
        return False
