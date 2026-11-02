"""PS-side position-mode executor for calibrated STS3215 joints."""
import math
import time
from protocol import exchange, ProbeError


def validate_machine(machine, drawing=False):
    if not isinstance(machine, dict) or machine.get("schema") != "so101-machine-v1":
        raise ValueError("使用 machine.example.json 的配置格式")
    if drawing and 'pen_tcp_calibration' in (machine.get('model') or {}):
        raise ValueError("工具偏移标定已移除，请使用当前纸面几何配置重新规划")
    if drawing:
        from four_point_calibration import validate
        validate(machine, require_ready=True)
    joints = machine.get("joints", [])
    if len(joints) != 5:
        raise ValueError("需要按运动学顺序填写 5 个运动关节，夹爪不参与")
    ids = [j.get("id") for j in joints]
    if any(type(i) is not int or not 1 <= i <= 253 for i in ids) or len(set(ids)) != 5:
        raise ValueError("关节 ID 必须是 5 个不同的 1–253 整数")
    for j in joints:
        if j.get("direction") not in (-1, 1) or type(j.get("direction")) is not int:
            raise ValueError("方向只能为 +1 或 -1")
        if any(type(j.get(k)) is not int for k in ("zero_count", "min_count", "max_count")):
            raise ValueError("先填写各关节零位、最小和最大计数")
        if not 0 <= j['min_count'] < j['max_count'] <= 4095 or not 0 <= j['zero_count'] <= 4095:
            raise ValueError("本版使用 0–4095 的位置模式，限位区间必须有效")
    if machine.get("checks", {}).get("limits") is not True:
        raise ValueError("先完成 ID/方向/限位核对，并更新 checks.limits")
    if drawing and not all(machine.get("checks", {}).get(k) is True for k in ("kinematics", "single_joint")):
        raise ValueError("绘画前完成工具/纸面标定及单关节测试")
    return joints


def angles_from_counts(machine, counts):
    return [j['direction']*(counts[j['id']]-j['zero_count'])*2*math.pi/4096 for j in machine['joints']]


def counts_from_angles(machine, q):
    if len(q) != 5 or not all(math.isfinite(v) for v in q):
        raise ValueError("目标关节角不完整")
    result = {}
    for j, angle in zip(machine['joints'], q):
        # int() 必须显式加: 板卡 numpy 1.17 的 round(np.float64) 返回 np.float64,
        # 会让 target() 的 "type(c) is int" 校验全部失败 (舵机收不到任何指令)。
        value = int(round(j['zero_count'] + j['direction']*angle*4096/(2*math.pi)))
        if not j['min_count'] <= value <= j['max_count']:
            raise ValueError("ID %s 目标超出计数限位" % j['id'])
        result[j['id']] = value
    return result


def quantized_angles_many(machine,qs):
    """Bounded offline batches with the exact executor rounding/order.

    Returns joint angles at integer servo counts. This never writes a servo.
    Keep ties-to-even and validate count limits before converting to integers.
    """
    import numpy as np
    q=np.asarray(qs,dtype=np.float64)
    joints=machine['joints']
    if q.ndim!=2 or q.shape[1]!=5 or not np.isfinite(q).all() or len(joints)!=5:
        raise ValueError('目标关节角不完整')
    ids=[j['id'] for j in joints]
    if len(set(ids))!=5:raise ValueError('关节 ID 重复')
    zeros=np.asarray([j['zero_count'] for j in joints])
    directions=np.asarray([j['direction'] for j in joints])
    counts=np.rint(zeros+directions*q*4096/(2*math.pi))
    for i,j in enumerate(joints):
        if np.any(counts[:,i]<j['min_count']) or np.any(counts[:,i]>j['max_count']):
            raise ValueError('ID %s 目标超出计数限位'%j['id'])
    return directions*(counts-zeros)*2*math.pi/4096


def sync(port, address, values):
    size = {40: 1, 41: 7, 42: 6}.get(address)
    if address not in (40, 41, 42) or not values:
        raise ValueError("Unsupported write")
    payload = [address, size]
    for sid, data in values.items():
        if type(sid) is not int or not 1 <= sid <= 253 or len(data) != size:
            raise ValueError("Invalid sync payload")
        payload.extend([sid] + list(data))
    body = [254, len(payload)+2, 0x83] + payload
    packet = b'\xff\xff' + bytes(body + [(~sum(body)) & 255])
    if port.write(packet) != len(packet):
        raise ProbeError("SHORT_WRITE", "Incomplete motor command")


def target(port, counts, speed=100):
    # 容忍整数值的 float/numpy 标量 (板卡 numpy 1.17 的 round() 会返回 np.float64),
    # 内部统一转成 Python int 再下发。
    def _count_ok(c):
        try:
            f = float(c)
        except (TypeError, ValueError):
            return False
        return math.isfinite(f) and f == int(f) and 0 <= f <= 4095
    if not 1 <= speed <= 200 or not counts or not all(_count_ok(c) for c in counts.values()):
        raise ValueError("Invalid target/speed")
    counts = {i: int(c) for i, c in counts.items()}
    sync(port, 42, {i: [c & 255, c >> 8, 0, 0, speed & 255, speed >> 8] for i, c in counts.items()})


def sync_position_profile(port, counts, speeds, accelerations):
    """Explicit STS position profile; speed is a cap, not signed feedforward."""
    if not counts or set(counts) != set(speeds) or set(counts) != set(accelerations):
        raise ValueError('Incomplete servo profile')
    for sid in counts:
        if (type(counts[sid]) is not int or not 0 <= counts[sid] <= 4095
                or type(speeds[sid]) is not int or not 1 <= speeds[sid] <= 200
                or type(accelerations[sid]) is not int or not 1 <= accelerations[sid] <= 254):
            raise ValueError('Invalid servo profile values')
    sync(port, 41, {sid: [accelerations[sid], counts[sid] & 255, counts[sid] >> 8,
                        0, 0, speeds[sid] & 255, speeds[sid] >> 8] for sid in counts})


def read_all(port, machine, preflight=False, need_torque=True):
    counts = {}
    operations = {'ping': '通信探测（ping）', 'model': '读取型号（model）',
                  'mode': '读取工作模式（mode）', 'torque': '读取扭矩状态（torque）',
                  'position': '读取当前位置（position）'}
    def read(sid, operation):
        try:
            return exchange(port, sid, operation)
        except ProbeError as exc:
            # Keep the protocol code and original exception for callers that
            # distinguish timeout/checksum/servo faults; only add context.
            raise ProbeError(exc.code, '舵机 ID %s %s失败 [%s]：%s' %
                             (sid, operations[operation], exc.code, exc)) from exc
    for j in machine['joints']:
        sid = j['id']
        if preflight:
            read(sid, "ping")
            if read(sid, "model") != 777 or read(sid, "mode") != 0:
                raise ValueError("ID %s 不是 STS3215 位置模式" % sid)
        if need_torque and read(sid, "torque") != 1:
            raise ValueError("ID %s 尚未启用扭矩，先点击启用保持" % sid)
        c = read(sid, "position")['position_count']
        if not j['min_count'] <= c <= j['max_count']:
            raise ValueError("ID %s 当前读数超出所填限位" % sid)
        counts[sid] = c
    return counts


class Executor:
    def __init__(self, port, machine, cancelled=lambda: False, audit=lambda *args: None):
        self.port, self.machine, self.cancelled, self.audit = port, machine, cancelled, audit
        cfg = machine.get('execution', {})
        self.guard_policy = cfg.get('guard_policy', 'audit')
        if self.guard_policy not in ('audit', 'strict'):
            raise ValueError('execution.guard_policy must be audit or strict')
        self.max_feedback_s = float(cfg.get('max_feedback_s', .2))
        self.max_lateness_s = float(cfg.get('max_lateness_s', .2))
        self.settle_timeout_s = float(cfg.get('settle_timeout_s', 30))
        if not all(math.isfinite(v) and v > 0 for v in
                   (self.max_feedback_s, self.max_lateness_s, self.settle_timeout_s)):
            raise ValueError('Invalid execution time budgets')

    def _guard(self, failed, event, detail, message):
        if failed:
            self.audit(event + ('_FAIL' if self.guard_policy == 'strict' else '_OFF'), detail)
            if self.guard_policy == 'strict':
                raise RuntimeError(message)

    def hold(self):
        # Best effort current-position hold, preserving support torque.
        try:
            counts = read_all(self.port, self.machine, need_torque=False)
            target(self.port, counts)
            self.audit("HOLD", counts)
        except Exception as exc:
            self.audit("HOLD_FAILED", str(exc))

    def enable(self):
        counts = read_all(self.port, self.machine, preflight=True, need_torque=False)
        if self.cancelled():
            raise RuntimeError("STOPPED")
        target(self.port, counts)
        if self.cancelled():
            raise RuntimeError("STOPPED")
        sync(self.port, 40, {i: [1] for i in counts})
        time.sleep(.05)
        read_all(self.port, self.machine)
        return counts

    def jog(self, sid, delta):
        if type(delta) is not int or not 1 <= abs(delta) <= 20:
            raise ValueError("单次点动为 ±1–20 计数")
        current = read_all(self.port, self.machine, preflight=True)
        if type(sid) is not int or sid not in current:
            raise ValueError("选择一个运动关节")
        end = dict(current)
        end[sid] += delta
        for j in self.machine['joints']:
            if not j['min_count'] <= end[j['id']] <= j['max_count']:
                raise ValueError("点动超过限位")
        from smooth_motion import joint_move
        return joint_move(self, current, end, minimum_duration=1.)

    def move_to(self, end, steps=None, minimum_clearance_m=None):
        """平滑移动到目标计数 (end: {id: count})，用于回绘画起始位。"""
        current = read_all(self.port, self.machine, preflight=True)
        if self.cancelled():
            raise RuntimeError("STOPPED")
        from smooth_motion import joint_move
        return joint_move(self, current, end, minimum_duration=max(1., (steps or 0)*.05), settle_counts=40,
                          minimum_clearance_m=minimum_clearance_m, motion_mode='speed_priority')

    def move_pen_up_to(self,end,backend=None):
        """Return/find position through a Cartesian pen-up route."""
        import planning
        from smooth_motion import MotionCurve,SerialMotionScheduler
        current=read_all(self.port,self.machine,preflight=True)
        mode='sugar_fast' if self.machine.get('execution',{}).get('default_motion_mode')=='sugar_fast' else 'speed_priority'
        result,q0,cfg=planning.build_pen_up_transfer(self.machine,current,end,backend=backend,cancel=self.cancelled,
                                                  motion_mode=mode)
        if result.status!='OK':raise ValueError('抬笔转移轨迹规划失败：'+str(result.status))
        outcome=SerialMotionScheduler(self,MotionCurve(result,self.machine)).run(current,settle_counts=40)
        outcome.update(pen_up_transfer=True,requested_counts=end,planned_duration_s=result.metrics['duration_s'])
        return outcome

    def execute_curve(self, curve, q0, backend=None):
        """Internal handoff of a fully checked curve while the job lock is held.

        There is no API flag to skip validation. Workbench constructs this
        curve before opening the port; direct callers use execute() below.
        """
        from smooth_motion import MotionCurve, SerialMotionScheduler, align_start
        if not isinstance(curve, MotionCurve) or curve.machine != self.machine:
            raise ValueError('执行轨迹与当前标定不一致')
        expected = counts_from_angles(self.machine, curve.q0)
        if expected != counts_from_angles(self.machine, q0):
            raise ValueError('轨迹起点与保存的起点不一致')
        current = read_all(self.port, self.machine, preflight=True)
        curve, alignment = align_start(curve, current, backend=backend, cancel=self.cancelled)
        if alignment['applied']:
            self.audit('START_ALIGNMENT', alignment)
        outcome = SerialMotionScheduler(self, curve).run(current)
        outcome['start_alignment'] = alignment
        return outcome

    def execute(self, result, q0, backend=None):
        if result.status != 'OK' or not result.commands:
            raise ValueError("先生成成功的轨迹")
        if getattr(result,'metrics',{}).get('motion_algorithm_version') == 'motion-smooth-v1':
            from smooth_motion import validate_plan
            curve = validate_plan(result, self.machine)
            return self.execute_curve(curve, q0, backend=backend)
        expected = counts_from_angles(self.machine, q0)
        current = read_all(self.port, self.machine, preflight=True)
        # 带载下 8 计数太严 (实测可差 12+), 放宽到 40 避免误判
        if any(abs(current[i]-expected[i]) > 40 for i in current):
            raise ValueError("起始姿态已变化，请重新规划")
        frames = [(c['t_s'], counts_from_angles(self.machine, c['q_rad'])) for c in result.commands]
        return self.run_frames(frames, current, result.commands)

    # ---------------- 串口容错: 瞬时错误不中止绘画 ----------------
    READ_RETRIES = 5
    WRITE_RETRIES = 5
    WRITE_FAIL_STREAK_LIMIT = 40      # 连续失败 40 帧 (~4 秒) 判定为硬故障

    def _safe_read(self, index, stage):
        """Keep measurement age and freshness; commands are never feedback."""
        last_exc = None
        for attempt in range(self.READ_RETRIES):
            if self.cancelled():
                raise RuntimeError('STOPPED')
            try:
                values = read_all(self.port, self.machine)
                self._feedback_counts = dict(values)
                self._feedback_at = time.monotonic()
                return values, self._feedback_at, True
            except (ProbeError, OSError) as exc:
                last_exc = exc
                self.audit('READ_RETRY', dict(index=index, stage=stage,
                                              attempt=attempt + 1, error=str(exc)[:90]))
                time.sleep(0.02)
        self.audit('READ_FALLBACK', dict(index=index, stage=stage,
                                         error=str(last_exc)[:90],
                                         using=dict(self._feedback_counts),
                                         measured_at_s=self._feedback_at, fresh=False))
        self._guard(True, 'FEEDBACK', dict(index=index, stage=stage), '反馈读取失败')
        return dict(self._feedback_counts), self._feedback_at, False

    def _safe_write(self, values, index):
        """下发一帧目标。写失败重试; 但连续失败过多说明串口/指令真有问题,
        必须显式失败 —— 否则任务会"成功"却一动不动, 用户只看到没反应。"""
        last_exc = None
        for attempt in range(self.WRITE_RETRIES):
            if self.cancelled():
                raise RuntimeError('STOPPED')
            try:
                target(self.port, values)
                self._write_fail_streak = 0
                return True
            except Exception as exc:
                last_exc = exc
                self.audit('WRITE_RETRY', dict(index=index, attempt=attempt + 1,
                                               error=str(exc)[:90]))
                time.sleep(0.02)
        streak = getattr(self, '_write_fail_streak', 0) + 1
        self._write_fail_streak = streak
        self.audit('WRITE_FAILED', dict(index=index, error=str(last_exc)[:90],
                                        streak=streak, target=dict(values)))
        if streak >= self.WRITE_FAIL_STREAK_LIMIT:
            raise RuntimeError("连续 %d 帧无法下发给舵机（最后错误：%s）"
                               % (streak, str(last_exc)[:80]))
        return False

    def run_frames(self, frames, current, commands=None, settle_counts=8):
        if not frames:
            raise ValueError('Empty trajectory')
        monitor = None
        if commands is not None:
            if len(commands) != len(frames):
                raise ValueError('Tracking command count mismatch')
            from tracking import TrackingMonitor
            monitor = TrackingMonitor(self.machine)
        previous_t, previous = 0., current
        joints = {j['id']: j for j in self.machine['joints']}
        if set(current) != set(joints):
            raise ValueError('Incomplete initial joint counts')
        for index, (t, values) in enumerate(frames):
            if not math.isfinite(t) or t <= previous_t or set(values) != set(current):
                raise ValueError("Invalid trajectory timing")
            if any(type(v) is not int or not joints[i]['min_count'] <= v <= joints[i]['max_count']
                   for i, v in values.items()):
                raise ValueError('Trajectory count outside joint limits')
            step = max(abs(values[i]-previous[i]) for i in values)
            if step > 100*(t-previous_t)+2:
                if self.guard_policy == 'strict':
                    raise ValueError('Trajectory count rate exceeds limit')
                self.audit('RATE_OFF', dict(index=index, t_s=t, step=step,
                                            limit=100*(t-previous_t)+2))
            previous_t, previous = t, values
        started = time.monotonic()
        last = current
        self._feedback_counts, self._feedback_at = dict(current), started
        self._write_fail_streak = 0
        schedule_shift = 0.; feedback_estimate = .02
        timing = dict(max_feedback_s=0., max_lateness_s=0., schedule_stretch_s=0.,
                      max_following_error_counts=0, max_feedback_age_s=0.,
                      feedback_failures=0, write_failures=0, frames_sent=0,
                      guard_policy=self.guard_policy)
        def wait_until(deadline):
            while time.monotonic() < deadline:
                if self.cancelled():
                    raise RuntimeError('STOPPED')
                time.sleep(min(.01, max(0, deadline-time.monotonic())))
        try:
            for index, (when, values) in enumerate(frames):
                due = started+when+schedule_shift
                # Read just ahead of the target deadline. A delayed cycle stretches
                # the timeline; it never compresses later intervals into a burst.
                wait_until(due-feedback_estimate)
                if self.cancelled():
                    raise RuntimeError("STOPPED")
                lag = time.monotonic()-due
                self._guard(lag > self.max_lateness_s, 'LAG',
                            dict(index=index, lag_s=lag, stage='before_read'), '反馈耗时或调度延迟超限')
                feedback_started = time.monotonic()
                feedback, measured_at, fresh = self._safe_read(index, 'frame')
                timing['feedback_failures'] += int(not fresh)
                feedback_finished = time.monotonic()
                feedback_s = feedback_finished-feedback_started
                feedback_estimate = min(.2, max(.001, feedback_s*1.2))
                if self.cancelled():
                    raise RuntimeError("STOPPED")
                lag = time.monotonic()-due
                self._guard(lag > self.max_lateness_s or feedback_s > self.max_feedback_s,
                            'LAG', dict(index=index, lag_s=lag, feedback_s=feedback_s,
                                        stage='after_read'), '反馈耗时超限')
                following = max(abs(feedback[i]-last[i]) for i in last)
                self._guard(fresh and following > 60, 'FOLLOWING',
                            dict(index=index, following=following, feedback=feedback), '关节跟随误差超限')
                if monitor is not None and index > 0 and fresh:
                    quality = monitor.observe(feedback, commands[index-1])
                    if quality is not None and not quality['qualified']:
                        self._guard(True, 'TRACKING', dict(index=index, feedback=feedback, **quality), '笔尖跟踪误差超限')
                wait_until(due)
                if self.cancelled():
                    raise RuntimeError('STOPPED')
                sent = time.monotonic()
                lag = max(0., sent-due)
                self._guard(lag > self.max_lateness_s, 'LAG',
                            dict(index=index, lag_s=lag, stage='before_write'), '反馈耗时或调度延迟超限')
                wrote = self._safe_write(values, index)
                timing['frames_sent'] += int(wrote)
                timing['write_failures'] += int(not wrote)
                # Include write completion: USB/OS stalls cannot cause catch-up.
                schedule_shift += max(0., time.monotonic()-due)
                timing.update(max_feedback_s=max(timing['max_feedback_s'],feedback_s),
                              max_lateness_s=max(timing['max_lateness_s'],lag),
                              schedule_stretch_s=schedule_shift,
                              max_following_error_counts=max(timing['max_following_error_counts'],following if fresh else 0),
                              max_feedback_age_s=max(timing['max_feedback_age_s'],sent-measured_at))
                if wrote:
                    last = values
                if index % 10 == 0:
                    self.audit("FRAME", dict(index=index, target=values, feedback=feedback, lag_s=lag,
                                             feedback_s=feedback_s, sent_s=sent-started, stretch_s=schedule_shift))
            deadline = time.monotonic()+self.settle_timeout_s
            settled = False
            while True:
                if self.cancelled():
                    raise RuntimeError("STOPPED")
                feedback, measured_at, fresh = self._safe_read(-1, 'settle')
                timing['feedback_failures'] += int(not fresh)
                if fresh and all(abs(feedback[i]-last[i]) <= settle_counts for i in last):
                    settled = True
                    break
                if time.monotonic() > deadline:
                    self._guard(True, 'SETTLE', dict(target=last, final=feedback if fresh else None,
                                residual=max(abs(feedback[i]-last[i]) for i in last) if fresh else None), '终点反馈未到位')
                    break
                time.sleep(.05)
            if monitor is not None and fresh:
                quality = monitor.observe(feedback, commands[-1])
                if quality is not None and not quality['qualified']:
                    self._guard(True, 'TRACKING', quality, '笔尖跟踪误差超限')
            timing['elapsed_s'] = time.monotonic()-started
            timing['settled'] = settled
            self.audit('TIMING', timing)
            outcome = dict(frames=len(frames), final_counts=feedback if fresh else None,
                           last_measured_counts=feedback, feedback_fresh=fresh,
                           feedback_age_s=max(0., time.monotonic()-measured_at), timing=timing,
                           execution_finished=True,
                           task_complete=bool(settled and fresh and not timing['write_failures']))
            if monitor is not None:
                outcome['tracking'] = monitor.summary()
                outcome['tracking']['feedback_complete'] = not timing['feedback_failures']
                outcome['tracking']['tracking_qualified'] &= bool(
                    settled and fresh and not timing['feedback_failures'] and not timing['write_failures'])
                self.audit('TRACKING', outcome['tracking'])
            return outcome
        except Exception:
            self.hold()
            raise
