"""Execute a frozen ZYNQ plan on the TCB705 controller via auto-mode Web programs.

The plan is computed locally (stroke ordering, lift/lower, 7-axis continuous IK on
the PL/CPU batch core and C2 retiming). Its geometric nodes are sent
as one or more controller programs:

  mode 'cartesian': hmcLine, node positions mapped to controller world
                    (T_controller_base_from_model), UVW from tool_rotation;
                    collinear nodes merged within merge_tolerance_mm.
  mode 'joint'    : hmcRobotFree, the locally solved 7 joint angles per node
                    (SDK degrees, mask 127); the controller does no IK.

Safety (all verified on the real arm 2026-10-17 except chunking):
  * refuses unless execution.web_program.enabled, calibration and SDK mapping verified;
  * current pose/joints must match the plan start (otherwise replan);
  * manual->auto can sag J2 (5.9 / 8.4 mm seen): wait still, limit the shift,
    first block then starts from the settled pose;
  * path watchdog: pose must stay within path_deviation_mm of the planned polyline,
    never below the lowest planned Z minus below_paper_mm; no progress -> stop;
  * mode switches require 60 mm clearance; after a low stop, defer mode restoration;
  * never clears alarms, never changes protection, never retries motion requests.
"""
import math
import time
import ctypes as ct
import hashlib
import json
from dataclasses import dataclass
import numpy as np
from .artifact import load, load_nodes, check_frozen
from .model import Model
from .planner import PHASE
from .web_control import Controller, ControllerError, dist3, settle_pose

DEFAULTS = dict(enabled=False, mode='cartesian', draw_speed_pct=5, air_speed_pct=5, smooth=0,
                max_blocks=2000, merge_tolerance_mm=0.02, max_power_on_shift_mm=10.0,
                start_tolerance_mm=3.0, start_tolerance_deg=0.5, path_deviation_mm=3.0,
                below_paper_mm=0.5, no_progress_s=10.0, poll_s=0.1, mold='ZYNQArm_Draw',
                ik_role='planning_only', uvw='current',
                joint_draw_tolerance_mm=0.05, joint_air_tolerance_mm=1.0,
                joint_merge_tolerance_mm=0.02, joint_air_merge_tolerance_mm=0.5, joint_max_block_mm=20.0,
                post_restore_watch_s=4.0, end_mode='auto', home=None)
AIR = {PHASE['APPROACH'], PHASE['LIFT'], PHASE['TRAVEL'], PHASE['FINISH']}
# Shared by every brush preset/radical: reduce the host's segment wait by one
# third. This is not a controller dwell or a promise about physical stroke time.
BRUSH_SEGMENT_WAIT_SCALE = 2.0 / 3.0
# A completed return can need more than six seconds to settle. Keep the same
# five-sample / 0.05 mm test; this is a bounded, read-only wait, never a motion retry.
COMPLETED_RESTORE_SETTLE_S = 20.0


class ExecutionError(RuntimeError):
    pass


class CancelledByUser(ExecutionError):
    """The board's stop button: the only software reason to end a drawing in home mode."""


def read_pose(ctrl, note, sleep, patience_s=120.0, cancel=lambda: False):
    """Pose with retries: a slow controller reply (4 s timeout seen 2026-10-18) is not a reason to stop."""
    waited = 0.0; last = None
    while True:
        try:
            return ctrl.pose()
        except Exception as exc:  # noqa: BLE001 - transient link/HTTP errors
            last = exc
            if cancel():
                raise CancelledByUser('CANCELLED: 用户停止')
            if waited >= patience_s:
                raise ExecutionError('CONTROLLER_UNREACHABLE: %.0f s 读不到位置：%s' % (waited, last))
            note('READ_RETRY', error=str(exc)[:120]); sleep(0.5); waited += 0.5


def controller_halted(ctrl):
    """Alarm, E-stop or servo off: the controller itself has stopped (we cannot continue)."""
    try:
        st = ctrl.state(); al = ctrl.active_alarms()
    except Exception:  # noqa: BLE001 - unknown is not halted; keep waiting
        return None
    if al or st.get('_phc_alarm_') not in ('0', '') or st.get('g_state_') != '1' or \
            st.get('g_servo_statero_') not in ('1', 'true', 'True'):
        return '%s %s' % (st, al)
    return None


def already_auto(st):
    """Jobs end in auto (end_mode, 2026-10-28): a powered auto controller is not switched again."""
    return st.get('_phc_ctrlkey') == '100' and st.get('g_servo_statero_') in ('1', 'true', 'True')


def require_home_ready(ctrl):
    """A controlled brush return requires known healthy feedback and an already powered auto mode."""
    try:
        st = ctrl.state()
        alarms = ctrl.strict_active_alarms() if hasattr(ctrl, 'strict_active_alarms') else ctrl.active_alarms()
    except Exception as exc:
        raise ExecutionError('HOME_STATE_UNKNOWN: 归位前无法确认控制器状态：%s' % exc) from exc
    if (not isinstance(st, dict) or not isinstance(alarms, (list, tuple)) or
            st.get('_phc_alarm_') not in ('0', '') or st.get('g_state_') != '1' or
            st.get('g_servo_statero_') not in ('1', 'true', 'True') or alarms):
        raise ExecutionError('HOME_CONTROLLER_HALTED: 报警、急停、伺服关闭或状态不完整，保持停止')
    if st.get('_phc_ctrlkey') != '100':
        raise ExecutionError('HOME_MODE_CHANGED: 控制器已离开自动模式，保持停止')


def home_pose(ctrl):
    """Unlike the legacy drawing recovery, unknown brush feedback must stop the return immediately."""
    try:
        p = ctrl.pose()
        if len(p) < 6 or not all(math.isfinite(float(v)) for v in p):
            raise ValueError('姿态不是有限的 XYZUVW')
    except Exception as exc:
        raise ExecutionError('HOME_FEEDBACK_INVALID: 归位位置反馈失效：%s' % exc) from exc
    return p


def mode_switch_min_z(config, pose):
    """Controller-world paper plane at this XY, plus the required 60 mm clearance."""
    origin = np.asarray(config['paper']['origin_m'], dtype=float) * 1000
    contact_z = config.get('calibration_source', {}).get('contact_z_mm')
    if contact_z is not None:
        origin[2] = float(contact_z)  # --air raises the drawing plane, not the physical paper.
    brush_z = config.get('calligraphy', {}).get('contact_z_mm')
    if config.get('mounted_tool') == 'brush' and brush_z is not None:
        origin[2] = max(origin[2], float(brush_z))  # clearance is measured from the mounted brush tip
    pen_z = config.get('hardpen', {}).get('contact_z_mm')
    if config.get('mounted_tool') == 'hardpen' and pen_z is not None:
        origin[2] = max(origin[2], float(pen_z))    # ... or from the mounted hard pen's tip
    normal = np.cross(config['paper']['x_axis'], config['paper']['y_axis'])
    height = origin[2] - np.dot(normal[:2], np.asarray(pose[:2]) - origin[:2]) / normal[2]
    return float(height + 60.0)


def require_mode_switch_clearance(config, pose):
    minimum = mode_switch_min_z(config, pose)
    if not np.isfinite(pose[:3]).all() or float(pose[2]) < minimum - 1e-6:
        raise ExecutionError('MODE_SWITCH_CLEARANCE: Z %.3f mm，切模式需至少 %.3f mm（离纸 60 mm）' % (pose[2], minimum))


def restore_safe(ctrl, config, clock=time.monotonic, sleep=time.sleep, settle_timeout=6.0, note=None):
    """Stop the program, then restore only with stable, high, readable feedback.

    Never lift automatically after an error: recovery needs a new reviewed motion.
    """
    try:
        ctrl.run_key(False)
        if note and settle_timeout > 6.0:
            note('RESTORE_WAIT', timeout_s=settle_timeout)
        def observe(sample):
            if note:
                note('RESTORE_SETTLE_SAMPLE', **sample)
            if settle_timeout > 6.0 and not sample['timed_out']:
                # The program is already stopped. A longer read-only wait must
                # not restore modes using stale alarm/servo/mode feedback.
                try:
                    st = ctrl.state()
                    alarms = ctrl.strict_active_alarms() if hasattr(ctrl, 'strict_active_alarms') else ctrl.active_alarms()
                except Exception as exc:
                    raise ExecutionError('RESTORE_STATE_UNKNOWN: 静止等待期间无法确认控制器状态：%s' % exc) from exc
                if (not isinstance(st, dict) or not isinstance(alarms, (list, tuple)) or alarms or
                        st.get('_phc_alarm_') not in ('0', '') or st.get('g_state_') != '1' or
                        st.get('_phc_ctrlkey') != '100' or
                        st.get('g_servo_statero_') not in ('1', 'true', 'True')):
                    raise ExecutionError('RESTORE_STATE_UNSAFE: 静止等待期间控制器报警、急停、伺服关闭或模式改变')
        ref = settle_pose(ctrl, clock=clock, sleep=sleep, timeout=settle_timeout,
                          observe=observe, context='模式恢复前')
        require_mode_switch_clearance(config, ref)
        if note and settle_timeout > 6.0:
            note('RESTORE_SETTLED')
    except Exception as exc:  # noqa: BLE001 - uncertain feedback must prevent a mode switch
        return None, [('restore_deferred', False, str(exc))]
    # end_mode 'auto' (2026-10-28): stay in auto after a job; switching to manual shook the arm at home.
    manual = config.get('execution', {}).get('web_program', {}).get('end_mode', 'auto') == 'manual'
    return ref, ctrl.restore(manual=manual)


def settings(config):
    s = dict(DEFAULTS); s.update(config.get('execution', {}).get('web_program', {}))
    if s['mode'] not in ('cartesian', 'joint'):
        raise ValueError('execution.web_program.mode 必须为 cartesian 或 joint')
    for k in ('draw_speed_pct', 'air_speed_pct'):
        if not 0 < float(s[k]) <= 100:
            raise ValueError(k + ' 必须为 0..100')
    if not 2 <= int(s['max_blocks']) <= 20000:
        raise ValueError('max_blocks 超出范围')
    if s['end_mode'] not in ('auto', 'manual'):
        raise ValueError('execution.web_program.end_mode 必须为 auto 或 manual')
    b = s.get('brush_blend')   # performances (2026-10-28): blend gentle brush vertices, corners stay exact
    if b is not None and (not isinstance(b, dict) or not 1 <= float(b.get('smooth', 0)) <= 9 or
                          not 0 < float(b.get('corner_deg', 0)) <= 45):
        raise ValueError('web_program.brush_blend 需要 smooth 1..9、corner_deg 0..45')
    if s['ik_role'] not in ('planning_only', 'execution') or s['uvw'] not in ('current', 'tool_rotation'):
        raise ValueError('ik_role 必须为 planning_only/execution，uvw 必须为 current/tool_rotation')
    if s['mode'] == 'joint' and s['ik_role'] != 'execution':
        raise ValueError('joint 模式会直接执行本地 IK 关节角，需要 ik_role=execution 且完成关节标定')
    h = s['home']
    if h is not None:
        if not isinstance(h, dict) or type(h.get('enabled')) is not bool:
            raise ValueError('web_program.home 需要 enabled 布尔值')
        q = h.get('joint_degrees')
        if (not isinstance(q, list) or len(q) != 7 or
                not all(isinstance(v, (int, float)) and math.isfinite(v) for v in q)):
            raise ValueError('web_program.home.joint_degrees 必须是 7 个有限角度')
        if not 0 < float(h.get('speed_pct', s['air_speed_pct'])) <= 100:
            raise ValueError('web_program.home.speed_pct 必须为 0..100')
        if h['enabled'] and s['mode'] != 'joint':
            raise ValueError('web_program.home 仅用于 joint 模式')
    return s


def home_enabled(config):
    h = settings(config)['home']
    return bool(h and h['enabled'])


def home_target(config):
    """Home joints (SDK deg) and their controller pose (XYZ mm + UVW deg, pen = tool_rotation)."""
    s = settings(config); model = Model(config)
    q = [float(v) for v in s['home']['joint_degrees']]
    T = model.fk(model.from_sdk(q))
    return q, [float(v) for v in T[:3, 3] * 1000] + uvw_deg(np.asarray(config['tool_rotation'], dtype=float))


def _air_ramp(config, block):
    """Mark a start/home move for the SDK's longer acceleration ramp (sdk_motion air_acc_time).
    Only SDK execution reads the marker; controller programs never receive it."""
    if config.get('execution', {}).get('sdk', {}).get('enabled') is True:
        block['sdk_ramp'] = 'air'
    return block


def home_program(config, s, here):
    """Straight up (pen straightened) to the home height, across to home, then the exact home joints."""
    q, pose = home_target(config)
    up = [round(float(here[0]), 3), round(float(here[1]), 3), round(max(float(here[2]), pose[2]), 3)]
    speed = float(s['home'].get('speed_pct', s['air_speed_pct']))

    def block(fc, mask, endp):
        return _air_ramp(config, {'fc': fc, 'pluginName': 'HC Motion Adapter', 'enabled': True, 'options': {'customName': ''},
                'code': {'robot': config['robot_id'], 'speed': speed, 'delay': 0, 'smooth': 0, 'relative': 0,
                         'mask': mask, 'more': [], 'endp': endp}})
    uvw = [round(v, 3) for v in pose[3:]]
    blocks = [block('hmcLine', 63, up + uvw), block('hmcLine', 63, [round(v, 3) for v in pose[:3]] + uvw),
              block('hmcRobotFree', 127, [round(v, 4) for v in q])]
    content = {'name': s['mold'], 'showname': s['mold'], 'type': 0, 'variables': [],
               'programs': [{'name': '主程序', 'tpid': 0, 'condition': 'd(_phc_ctrlkey) == 100 && d(_phc_key) == 100',
                             'recycle': False, 'type': 0, 'logic': 0,
                             'codeBlock': blocks + [{'fc': 'end', 'pluginName': '', 'enabled': True}]}]}
    return content, [up, pose[:3], pose[:3]], q


class ProgramMotion:
    """Original path: download the blocks as a controller program and press run (auto mode)."""

    def __init__(self, ctrl, s, sleep):
        self.ctrl = ctrl; self.s = s; self.sleep = sleep

    def start(self, content, cancel):
        # The controller program format has no sdk_ramp field; send the blocks without it.
        content = dict(content, programs=[dict(p, codeBlock=[{k: v for k, v in b.items() if k != 'sdk_ramp'}
                                                             for b in p['codeBlock']]) for p in content['programs']])
        self.ctrl.load_program(self.s['mold'], content)
        self.ctrl.run_key(False); self.sleep(0.2)
        if cancel():
            return False
        self.ctrl.run_key(True)
        return True

    def pump(self):
        pass

    def finish(self):
        self.ctrl.run_key(False)

    def stop(self):
        return self.ctrl.stop()


def stop_motion(motion, soft):
    """A user's stop decelerates first where the motion supports it (SDK pause); faults stop at once."""
    if soft and getattr(motion, 'supports_soft_stop', False):
        import inspect
        try:
            accepts = 'soft' in inspect.signature(motion.stop).parameters
        except (TypeError, ValueError):
            accepts = False
        if accepts:
            return motion.stop(soft=True)
    return motion.stop()


def go_home(ctrl, config, s, note, cancel, clock, sleep, label, motion=None, strict=False):
    """Run the home program in auto mode (servo on): straight up, across at the home height, then the
    exact home joints. Out-of-box poses and slowness are only logged; it ends at home, on cancel,
    or when the controller halts / the arm stays still away from home."""
    motion = motion or ProgramMotion(ctrl, s, sleep)
    if cancel():
        raise CancelledByUser('CANCELLED: 归位前停止')
    if strict:
        require_home_ready(ctrl)
    here = home_pose(ctrl) if strict else read_pose(ctrl, note, sleep, cancel=cancel)
    # Every home move shares the GUI speed, also on the controller-program fallback
    # (the old fixed web_program.home.speed_pct no longer applies). The SDK already
    # uses that same global speed for every move.
    home_settings = dict(s, home=dict(s['home'], speed_pct=s['draw_speed_pct']))
    content, targets, q = home_program(config, home_settings, here)
    pts = np.asarray([here[:3]] + targets, dtype=float)
    floor = min(float(here[2]), targets[1][2]) - (float(s['below_paper_mm']) if strict else 3.0)
    margin = float(s['path_deviation_mm']) if strict else 5.0
    lo, hi = pts.min(axis=0) - margin, pts.max(axis=0) + margin
    if not motion.start(content, cancel):
        raise CancelledByUser('CANCELLED: 归位前停止')
    note(label + '_START', start=[round(v, 3) for v in here[:3]], target=[round(v, 3) for v in targets[1]])
    t0 = clock(); last_move = t0; prev = here; stable = 0; last_warn = -1e9; dq = float('nan')
    timeout = 120.0 + sum(dist3(a, b) for a, b in zip(pts[:-1], pts[1:])) / 0.5
    while True:
        sleep(s['poll_s'])
        if cancel():
            raise CancelledByUser('CANCELLED: 用户停止')
        if strict:
            require_home_ready(ctrl)
        motion.pump()
        p = home_pose(ctrl) if strict else read_pose(ctrl, note, sleep, cancel=cancel); now = clock()
        outside = p[2] < floor or any(p[i] < lo[i] or p[i] > hi[i] for i in range(3))
        if strict and outside:
            raise ExecutionError('HOME_BOUNDS: 归位偏离允许范围，保持停止')
        if strict and now - t0 > timeout:
            raise ExecutionError('HOME_TIMEOUT: 归位超时，保持停止')
        if outside and now - last_warn >= 1.0:
            last_warn = now; note('WARN_HOME_BOUNDS', xyz=[round(v, 2) for v in p[:3]])
        if dist3(p, prev) > 0.02:
            last_move = now
        prev = p
        try:
            actual = ctrl.joints(7)
            if strict and (len(actual) != 7 or not all(math.isfinite(float(v)) for v in actual)):
                raise ValueError('关节反馈不是七个有限角度')
            dq = max(abs(a - b) for a, b in zip(actual, q))
        except Exception as exc:  # noqa: BLE001
            if strict:
                raise ExecutionError('HOME_JOINT_FEEDBACK: 归位关节反馈失效：%s' % exc) from exc
            note('READ_RETRY', error=str(exc)[:120]); continue
        stable = stable + 1 if dq < 0.05 and dist3(p, targets[1]) < 0.5 else 0
        if stable >= 5 and (not strict or not hasattr(motion, 'idle') or motion.idle()):
            break
        if now - last_move > s['no_progress_s']:
            if strict:
                raise ExecutionError('HOME_STALLED: 归位 %.0f s 无运动且未到位' % (now - last_move))
            halted = controller_halted(ctrl)
            if halted:
                raise ExecutionError('CONTROLLER_HALTED: 控制器已停止（报警/急停/伺服关）%s' % halted)
            if now - last_move > max(30.0, 3 * s['no_progress_s']):
                raise ExecutionError('HOME_STALLED: 归位 %.0f s 无运动且未到位' % (now - last_move))
    motion.finish()
    note(label + '_DONE', seconds=round(clock() - t0, 1), pose=[round(v, 3) for v in p[:3]],
         max_joint_error_deg=round(dq, 4))
    return p


def mapping_required(config):
    """Local joints only drive the arm in joint mode / ik_role=execution."""
    s = settings(config)
    return s['mode'] == 'joint' or s['ik_role'] == 'execution'


def uvw_deg(r):
    """Inverse of model.rpy_matrix (Rz(W) Ry(V) Rx(U)); controller XYZ mm + UVW deg."""
    p = math.asin(max(-1.0, min(1.0, -r[2, 0])))
    u = math.atan2(r[2, 1], r[2, 2]); w = math.atan2(r[1, 0], r[0, 0])
    return [math.degrees(u), math.degrees(p), math.degrees(w)]


def controller_points(config, nodes):
    # Planner positions/targets are already controller-world: Model.fk/solve apply
    # T_controller_base_from_model, and tool_rotation is the controller-frame target.
    mm = np.asarray(nodes['positions_m'], dtype=float) * 1000.0
    uvw = uvw_deg(np.asarray(config['tool_rotation'], dtype=float))
    return mm, [round(v, 4) for v in uvw]


def _point_line(p, a, b):
    d = b - a; n = float(d @ d)
    t = 0.0 if n < 1e-18 else min(1.0, max(0.0, float((p - a) @ d) / n))
    return float(np.linalg.norm(p - (a + t * d)))


def merge(mm, phase, stops, tol):
    """Node indices kept for hmcLine: drop nodes within tol of the chord, never across
    a phase change or a corner stop."""
    keep = [0]; anchor = 0; i = 1; n = len(mm); stops = set(stops)
    while i < n:
        j = i
        while (j + 1 < n and phase[j] == phase[anchor] and j not in stops and
               all(_point_line(mm[k], mm[anchor], mm[j + 1]) <= tol for k in range(anchor + 1, j + 1))):
            j += 1
        keep.append(j); anchor = j; i = j + 1
    return keep


NEAR_PAPER = {PHASE['DRAW'], PHASE['LOWER'], PHASE['LIFT']}


def _polyline_distance(points, poly):
    """Distance of each point to a polyline (vectorised)."""
    a, b = poly[:-1][None], poly[1:][None]; p = points[:, None]
    d = b - a; n = np.maximum(np.sum(d * d, axis=2), 1e-18)
    t = np.clip(np.sum((p - a) * d, axis=2) / n, 0, 1)
    return np.linalg.norm(p - (a + t[..., None] * d), axis=2).min(axis=1)


def _joint_arrays(model, nodes):
    degrees = np.asarray(nodes['sdk_degrees'], dtype=float)
    mm = np.asarray(nodes['positions_m'], dtype=float) * 1000.0
    n = len(mm)
    if (mm.shape != (n, 3) or degrees.shape != (n, 7) or n < 2 or
            len(nodes['interval_phase']) != n - 1 or
            not np.isfinite(mm).all() or not np.isfinite(degrees).all()):
        raise ExecutionError('invalid joint preparation nodes')
    q = np.empty_like(degrees)
    q[:, model.order] = degrees * math.pi / 180 * model.sign + model.offset
    return np.ascontiguousarray(q), np.ascontiguousarray(mm)


def joint_merge(config, nodes, s, model=None, merge=True):
    """Kept joint knots, one SDK moveJoints per gap (2026-10-25: merging restored).

    With queue_depth=1 every block accelerates, stops and waits for its callback,
    so sending every ~0.3 mm IK knot kept the arm far below the GUI speed (a
    four-character page was 8466 stop-and-go moves). Merged blocks keep the
    executed joint interpolation within joint_merge_tolerance_mm of the planned
    path; brush pages additionally cap it at 0.02 mm and re-check every merged
    block's orientation, pressure, paper and path by FK (refine_merged).
    """
    model = model or Model(config)
    q, _ = _joint_arrays(model, nodes)
    if np.any(q < model.lower) or np.any(q > model.upper):
        raise ExecutionError('FINAL_SAMPLE_LIMIT: 下发关节节点越界')
    if not merge:                       # live handwriting keeps every knot by design
        if nodes.get('calligraphy'):
            from .artifact import check_brush_nodes
            check_brush_nodes(nodes, config)
        return list(range(len(q)))
    if nodes.get('calligraphy'):
        from .artifact import check_brush_nodes
        from calligraphy.execution import refine_merged
        check_brush_nodes(nodes, config)
        # Never relax near-paper precision to gain speed.
        s = dict(s, joint_merge_tolerance_mm=min(s['joint_merge_tolerance_mm'], .02))
        return refine_merged(config, nodes, model, _joint_merge_candidates(config, nodes, s, model), s)
    return _joint_merge_candidates(config, nodes, s, model)


def _joint_merge_candidates(config, nodes, s, model=None):
    """Keep the fewest nodes such that linear joint interpolation between kept
    nodes (what hmcRobotFree executes) stays within tolerance of the dense planned path
    (DRAW/LOWER/LIFT: joint_merge_tolerance_mm, air: joint_air_merge_tolerance_mm).
    Never crosses a phase change or a corner stop; blocks <= joint_max_block_mm."""
    model = model or Model(config)
    q, mm = _joint_arrays(model, nodes)
    phase = nodes['interval_phase']; stops = set(nodes.get('stops', []))
    arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(mm, axis=0), axis=1))]
    if model.native_joint_preparation:
        phases = np.ascontiguousarray(phase, dtype=np.int32)
        stop_flags = np.array([i in stops for i in range(len(mm))], dtype=np.int32)
        near = np.array([p in NEAR_PAPER for p in phase], dtype=np.int32)
        keep = np.empty(len(mm), dtype=np.int32); ip = ct.POINTER(ct.c_int)
        count = model.lib.tcb_joint_merge(
            *[model.ptr(v) for v in (model.data, model.tool, model.base, q, mm, arc)],
            *[v.ctypes.data_as(ip) for v in (phases, stop_flags, near)], len(mm),
            s['joint_merge_tolerance_mm'], s['joint_air_merge_tolerance_mm'],
            s['joint_max_block_mm'], keep.ctypes.data_as(ip))
        if count < 2:
            raise ExecutionError('native joint merge rejected input')
        return keep[:count].tolist()
    keep = [0]; a = 0; n = len(mm)
    while a < n - 1:
        tol = s['joint_merge_tolerance_mm'] if phase[a] in NEAR_PAPER else s['joint_air_merge_tolerance_mm']
        j = a + 1
        while j + 1 < n and phase[j] == phase[a] and j not in stops and arc[j + 1] - arc[a] <= s['joint_max_block_mm']:
            c = j + 1; idx = np.arange(a + 1, c)
            f = ((arc[idx] - arc[a]) / max(arc[c] - arc[a], 1e-12))[:, None]
            g = np.linspace(0, 1, 9)[1:-1, None]          # plus evenly spaced probes
            Q = np.vstack([q[a] * (1 - f) + q[c] * f, q[a] * (1 - g) + q[c] * g])
            P = model.fk_batch(Q)[:, :3, 3] * 1000.0
            dev = max(np.linalg.norm(P[:len(idx)] - mm[idx], axis=1).max(), _polyline_distance(P[len(idx):], mm[a:c + 1]).max())
            if dev > tol:
                break
            j = c
        keep.append(j); a = j
    return keep


def joint_block_error(config, nodes, keep, probes=16, model=None):
    """Offline diagnostic only, never an execution-preparation acceptance gate.

    Max distance (mm) of the executed joint-lerp segments between kept nodes from the dense
    planned path, split into (near paper, air)."""
    model = model or Model(config)
    q, mm = _joint_arrays(model, nodes); phase = nodes['interval_phase']
    if model.native_joint_preparation:
        near = np.array([p in NEAR_PAPER for p in phase], dtype=np.int32)
        indices = np.ascontiguousarray(keep, dtype=np.int32)
        out = np.zeros(2); ip = ct.POINTER(ct.c_int)
        status = model.lib.tcb_joint_block_error(
            *[model.ptr(v) for v in (model.data, model.tool, model.base, q, mm)],
            near.ctypes.data_as(ip), len(mm), indices.ctypes.data_as(ip),
            len(indices), probes, model.ptr(out))
        if status:
            raise ExecutionError('native joint interpolation check rejected input')
        return tuple(float(v) for v in out)
    near = air = 0.0; g = np.linspace(0, 1, probes + 1)[1:-1, None]
    for a, b in zip(keep[:-1], keep[1:]):
        P = model.fk_batch(q[a] * (1 - g) + q[b] * g)[:, :3, 3] * 1000.0
        d = float(_polyline_distance(P, mm[a:b + 1]).max())
        if phase[a] in NEAR_PAPER:
            near = max(near, d)
        else:
            air = max(air, d)
    return near, air


@dataclass(frozen=True)
class JointPreparation:
    key: str
    keep: tuple
    error_mm: tuple
    seconds: float


def preparation_key(config, nodes, model=None):
    """Bind cached geometry to every input that can change it, including execution
    tolerances (deliberately excluded from the ordinary plan digest). Speed/chunk
    edits only rebuild the inexpensive program blocks, never reuse stale blocks."""
    from .config import digest
    s = settings(config)
    fields = ('mode', 'ik_role', 'joint_merge_tolerance_mm', 'joint_air_merge_tolerance_mm',
              'joint_max_block_mm', 'joint_draw_tolerance_mm', 'joint_air_tolerance_mm')
    h = hashlib.sha256()
    h.update(b'joint-preparation-merged-v3')
    if nodes.get('calligraphy'):
        from calligraphy.execution import MERGE_VERSION
        h.update(MERGE_VERSION.encode())
    h.update(digest(config).encode())
    h.update((model or Model(config)).model_sha256.encode())
    h.update(json.dumps({k: s[k] for k in fields}, sort_keys=True, allow_nan=False).encode())
    for k in ('positions_m', 'sdk_degrees', 'interval_phase', 'stops'):
        a = np.ascontiguousarray(nodes.get(k, []), dtype='<f8')
        h.update(str(a.shape).encode()); h.update(a.tobytes())
    return h.hexdigest()


def prepare_joint(config, nodes, cancel=lambda: False, merge=True):
    """Pure computation, safe before preview/confirmation; never connects to a controller.
    merge=False keeps every planned knot (live handwriting's short strokes)."""
    s = settings(config)
    if s['mode'] != 'joint':
        return None
    t = time.monotonic()
    if cancel():
        raise CancelledByUser('CANCELLED: 轨迹准备取消')
    model = Model(config)
    keep = joint_merge(config, nodes, s, model, merge)
    if cancel():
        raise CancelledByUser('CANCELLED: 轨迹准备取消')
    # No FK residual was measured. None is intentionally distinct from 0 mm.
    return JointPreparation(preparation_key(config, nodes, model), tuple(keep), (None, None), time.monotonic() - t)


def _turn_deg(mm, a, b, c):
    """Direction change at node b between segments a->b and b->c (degrees)."""
    u, v = np.asarray(mm[b]) - np.asarray(mm[a]), np.asarray(mm[c]) - np.asarray(mm[b])
    nu, nv = np.linalg.norm(u), np.linalg.norm(v)
    if nu < 1e-9 or nv < 1e-9:
        return 180.0
    return float(np.degrees(np.arccos(np.clip(np.dot(u, v) / (nu * nv), -1.0, 1.0))))


def build(config, nodes, s, uvw=None, joint_keep=None, brush_blend=None):
    """Return chunks: dict(blocks, node_index, content). node_index[k] = plan node of block k.
    uvw: controller UVW for hmcLine (s['uvw']=='current': the pose read at start).
    brush_blend: None keeps every brush block an exact stop (pages, poems, masterpieces).
    Live handwriting passes dict(smooth=1..9, corner_deg=...) to blend through gentle
    vertices inside one phase; corners, pen up/down, stops and stroke ends stay exact."""
    mm, planned_uvw = controller_points(config, nodes)
    uvw = planned_uvw if uvw is None else [round(float(v), 3) for v in uvw]
    phase = nodes['interval_phase']  # phase[i]: interval node i -> i+1
    if s['mode'] == 'cartesian':
        keep = merge(mm, phase, nodes.get('stops', []), float(s['merge_tolerance_mm']))
    else:
        keep = list(joint_keep) if joint_keep is not None else joint_merge(config, nodes, s)
    keep = keep[1:]  # node 0 is the measured start pose
    blocks = []
    stops = set(nodes.get('stops', [])); last = len(mm) - 1
    for k, i in enumerate(keep):
        ph = phase[i - 1]
        # blend only through gentle vertices inside one phase; exact stop at corners,
        # pen up/down transitions and stroke/plan ends
        gentle = i < last and i not in stops and phase[i] == ph
        if not nodes.get('calligraphy') and ph in AIR:
            gentle = False   # 2026-10-29: line art air moves stay exact too (a blended approach cut 23.75 mm)
        speed = s['air_speed_pct'] if ph in AIR else s['draw_speed_pct']
        smooth = float(s['smooth'])
        if nodes.get('calligraphy'):
            speed=s['draw_speed_pct']
            if brush_blend is None:
                gentle=False  # Brush pages: blending has not been calibrated.
            else:
                prev = keep[k - 1] if k else 0
                nxt = keep[k + 1] if k + 1 < len(keep) else None
                # draw_only (performances, 2026-10-28): long joint moves in the air cut their corners
                # 23.75 mm off the planned approach when blended; only the brush on paper flows.
                gentle = (gentle and not (brush_blend.get('draw_only') and ph in AIR) and
                          nxt is not None and phase[nxt - 1] == ph and
                          _turn_deg(mm, prev, i, nxt) <= float(brush_blend['corner_deg']))
                smooth = float(brush_blend['smooth'])
        code = {'robot': config['robot_id'], 'speed': float(speed), 'delay': 0, 'smooth': smooth if gentle else 0,
                'relative': 0, 'more': []}
        if nodes.get('calligraphy'):code['brush_uniform_speed']=True
        if s['mode'] == 'cartesian':
            code.update(mask=63, endp=[round(float(v), 3) for v in mm[i]] + uvw)
            fc = 'hmcLine'
        else:
            code.update(mask=127, endp=[round(float(v), 4) for v in nodes['sdk_degrees'][i]])
            fc = 'hmcRobotFree'
        block = {'fc': fc, 'pluginName': 'HC Motion Adapter', 'enabled': True,
                 'options': {'customName': ''}, 'code': code}
        if ph in (PHASE['APPROACH'], PHASE['FINISH']):   # leaving / returning to home
            _air_ramp(config, block)
        blocks.append((i, block))
    chunks = []; start = 0; limit = int(s['max_blocks'])
    while start < len(blocks):
        end = min(len(blocks), start + limit)
        if end < len(blocks):  # prefer to cut where the pen is in the air
            found_air=False
            for k in range(end - 1, start, -1):
                i = blocks[k][0]
                if i < len(phase) and phase[i] in AIR:
                    end = k + 1; found_air=True; break
            if nodes.get('calligraphy') and not found_air:
                raise ExecutionError('BRUSH_BLOCK_LIMIT: 单笔超出程序容量，请减小模块尺寸')
        part = blocks[start:end]
        content = {'name': s['mold'], 'showname': s['mold'], 'type': 0, 'variables': [],
                   'programs': [{'name': '主程序', 'tpid': 0, 'condition': 'd(_phc_ctrlkey) == 100 && d(_phc_key) == 100',
                                 'recycle': False, 'type': 0, 'logic': 0,
                                 'codeBlock': [b for _, b in part] + [{'fc': 'end', 'pluginName': '', 'enabled': True}]}]}
        chunks.append(dict(node_index=[i for i, _ in part], content=content, blocks=len(part)))
        start = end
    return mm, chunks


def joint_interpolation_error(config, nodes, fractions=(0.25, 0.5, 0.75)):
    """joint mode: the controller interpolates hmcRobotFree targets in joint space, so the
    pen tip between two nodes is FK(lerp(q_a, q_b)), not the planned straight segment.
    Returns (max mm over DRAW intervals, max mm over all other intervals)."""
    model = Model(config)
    q = np.array([model.from_sdk(d) for d in nodes['sdk_degrees']])
    mm = np.asarray(nodes['positions_m'], dtype=float) * 1000.0
    phase = np.asarray(nodes['interval_phase'])
    f = np.asarray(fractions)[None, :, None]
    samples = (q[:-1, None, :] * (1 - f) + q[1:, None, :] * f).reshape(-1, 7)
    pts = model.fk_batch(samples)[:, :3, 3].reshape(len(q) - 1, len(fractions), 3) * 1000.0
    a, b = mm[:-1, None, :], mm[1:, None, :]
    d = b - a; n = np.maximum(np.sum(d * d, axis=2, keepdims=True), 1e-18)
    t = np.clip(np.sum((pts - a) * d, axis=2, keepdims=True) / n, 0, 1)
    dev = np.linalg.norm(pts - (a + t * d), axis=2).max(axis=1)
    draw = phase == PHASE['DRAW']
    return float(dev[draw].max() if draw.any() else 0.0), float(dev[~draw].max() if (~draw).any() else 0.0)


HIGH_AIR_CLEAR_MM = 30.0       # 2026-10-28: travel this far above the highest brush point ...
HIGH_AIR_DEVIATION_MM = 8.0    # ... may run this far off its line (fast joint moves at 100 %)


def high_air_z(nodes, mm):
    """Controller Z above which a brush run's TRAVEL is "high air" (None: no brush strokes)."""
    ph = nodes['interval_phase']
    draw = [i for i, v in enumerate(ph) if v == PHASE['DRAW']]
    if not draw:
        return None
    return max(max(float(mm[i][2]), float(mm[i + 1][2])) for i in draw) + HIGH_AIR_CLEAR_MM


def deviation_limit(s, nodes, mm, node, high_z):
    """Path watchdog limit for the planned interval node -> node + 1.

    A poem stopped 3.11 mm off a long travel move 70 mm above the paper at 100 % (2026-10-28;
    100 % columns already ran 2.6-2.9 mm). Only TRAVEL with both ends at least
    HIGH_AIR_CLEAR_MM above the highest brush point gets HIGH_AIR_DEVIATION_MM; lowering,
    drawing, lifting and low travel keep path_deviation_mm, and the Z floor is unchanged."""
    limit = float(s['path_deviation_mm'])
    ph = nodes['interval_phase']
    if high_z is None or not 0 <= node < len(ph) or ph[node] != PHASE['TRAVEL']:
        return limit
    if min(float(mm[node][2]), float(mm[node + 1][2])) < high_z:
        return limit
    return max(limit, HIGH_AIR_DEVIATION_MM)


class Tracker:
    """Monotone progress along the dense planned polyline + deviation check."""
    TIE_MM = 0.3

    def __init__(self, path, window_mm=40.0):
        self.path = np.asarray(path, dtype=float); self.k = 0
        seg = np.linalg.norm(np.diff(self.path, axis=0), axis=1)
        self.s = np.r_[0, np.cumsum(seg)]; self.window = window_mm

    def update(self, p):
        p = np.asarray(p[:3], dtype=float); last = len(self.path) - 1
        if self.k >= last:
            return float(np.linalg.norm(p - self.path[last]))
        hi = int(np.searchsorted(self.s, self.s[self.k] + self.window, side='right'))
        hi = min(max(hi, self.k + 2), last + 1)
        # include the segments just behind k: the arm may lag the node the tracker already
        # passed (k advances within 0.5 mm of a node); searching only ahead reported the lag
        # (up to ~0.5 mm) as path deviation.
        lo = max(0, self.k - 2)
        d = [_point_line(p, self.path[j], self.path[j + 1]) for j in range(lo, hi - 1)]
        # Where the path revisits a place (the brush lifts and lands again at the same
        # paper point, common in 草书), a later segment can fit as well as the current
        # one. Jumping ahead there made the still-lifting arm look 5.9 mm off the path
        # (2026-10-25). Deviation stays the true nearest distance; progress advances only
        # to the earliest segment that fits within TIE_MM of it.
        dev = min(d)
        j = lo + next(i for i, v in enumerate(d) if v <= dev + self.TIE_MM)
        if float(np.linalg.norm(p - self.path[j + 1])) < 0.5:
            j += 1
        self.k = max(self.k, j)   # progress stays monotone even when matching a segment behind
        return dev

    def done(self):
        return self.k >= len(self.path) - 1


def return_home(config, cancel=lambda: False, progress=None, controller=None,
                clock=time.monotonic, sleep=time.sleep, motion=None, force=True):
    """复位 (2026-10-26): move to the calibrated home pose on its own, at the GUI speed.

    force (2026-10-29, the default): 强制复位 with no start conditions. No paper-calibration
    check; a low pen in manual mode is switched to auto and lifted straight up anyway (the
    switch can sag J2 by 6-8 mm); the power-on shift is only logged; the move runs without the
    bounds/timeout stops (cancel, a controller halt or a 30 s stall still end it). Only what the
    controller itself refuses stays: an alarm, E-stop or servo that will not power on.
    force=False keeps the strict 2026-10-26 rules.
    """
    s = settings(config)
    if s['enabled'] is not True:
        raise ExecutionError('WEB_PROGRAM_DISABLED: 配置 execution.web_program.enabled 未开启')
    if not home_enabled(config):
        raise ExecutionError('HOME_NOT_CONFIGURED: 未启用已标定的归位点，不能复位')
    if not force and (not config['calibration_verified'] or (mapping_required(config) and not config['sdk_mapping_verified'])):
        raise ExecutionError('复位前需完成纸面标定' + ('与关节映射核对' if mapping_required(config) else ''))
    ctrl = controller or Controller(config['controller'], config['robot_id'])
    motion = motion or ProgramMotion(ctrl, s, sleep)
    log = []

    def note(kind, **kw):
        kw['event'] = kind; kw['t'] = round(clock(), 3); log.append(kw)
        if progress:
            progress(kw)

    ctrl.login()
    if ctrl.axis_count() != 7:
        raise ExecutionError('控制器轴数不是 7')
    st = ctrl.state(); alarms = ctrl.active_alarms()
    if alarms or st['_phc_alarm_'] not in ('0', '') or st['g_state_'] != '1':
        raise ExecutionError('控制器有报警或急停状态，不运动：%s %s' % (st, alarms))
    start = ctrl.pose()
    keep_auto = False
    try:
        require_mode_switch_clearance(config, start)
    except ExecutionError:
        if st.get('_phc_ctrlkey') == '100':
            if not force:
                require_home_ready(ctrl)
            keep_auto = True
            note('HOME_KEEP_AUTO', detail='笔尖处于低处，保持已有自动模式，直接复位')
        elif not force:
            raise ExecutionError('LOW_START: 笔尖离纸太近且控制器不在自动模式，不能自动复位；请先用示教器把笔抬高')
        else:
            note('HOME_FORCE_LOW', detail='强制复位：笔尖处于低处且为手动模式，切自动后先竖直抬笔')
    note('READY', start=start, motion=type(motion).__name__)
    if cancel():
        raise CancelledByUser('CANCELLED: 上电前停止')
    moved = False; result = None; t_all = clock()
    try:
        if keep_auto or already_auto(st):
            if not force:
                require_home_ready(ctrl)
        else:
            ctrl.power('auto'); sleep(1.5)
        st = ctrl.state()
        if st['g_servo_statero_'] not in ('1', 'true', 'True'):
            raise ExecutionError('切换自动模式后伺服未上电')
        if hasattr(motion, 'set_speed'):
            note('SPEED', pct=s['draw_speed_pct'], read_back=motion.set_speed(s['draw_speed_pct']))
        settled = settle_pose(ctrl, clock=clock, sleep=sleep); shift = dist3(settled, start)
        note('POWER_ON', shift_mm=round(shift, 3), settled=settled)
        if not keep_auto and not force and shift > s['max_power_on_shift_mm']:
            raise ExecutionError('上电位移 %.2f mm 过大' % shift)
        moved = True
        here = go_home(ctrl, config, s, note, cancel, clock, sleep, 'HOME', motion, strict=not force)
        result = dict(status='DONE', physical_motion=True, simulation=False, robot_type='TCB705', kind='home',
                      seconds=round(clock() - t_all, 1), final_pose=here)
        return result
    except Exception as exc:
        try:
            stops = stop_motion(motion, isinstance(exc, CancelledByUser)) if moved else []
        except Exception as stop_exc:  # noqa: BLE001 - keep the original reason
            stops = [('stop', False, str(stop_exc))]
        note('ERROR', error=str(exc), stop=stops)
        if isinstance(exc, CancelledByUser):
            raise
        raise ExecutionError(str(exc)) from exc
    finally:
        ref, steps = restore_safe(ctrl, config, clock=clock, sleep=sleep,
                                 settle_timeout=COMPLETED_RESTORE_SETTLE_S if result is not None else 6.0,
                                 note=note)
        note('RESTORE', steps=steps, deferred=ref is None)
        if result is not None:
            result['restore_deferred'] = ref is None
            result['log'] = log[-30:]


def paper_margin(s, need):
    """How far below the lowest planned point the arm may go before a run stops: the
    configured below_paper_mm, at least 1.0 mm for the spring-held hard pen.

    Blended brush runs (performances at 100 %, 2026-10-28) carry the brush through its press
    changes without stopping and dipped 0.6 mm below the lowest planned point (a poem stopped
    at 0.5 mm); they get BLENDED_BRUSH_BELOW_PAPER_MM. 7 mm of press is still well inside the
    12 mm hair, so the ferrule stays off the paper."""
    m = float(s['below_paper_mm'])
    if need == 'hardpen':
        from calligraphy.hardpen import BELOW_PAPER_MM
        m = max(m, BELOW_PAPER_MM)
    elif need == 'brush' and s.get('brush_blend'):
        m = max(m, BLENDED_BRUSH_BELOW_PAPER_MM)
    return m


BLENDED_BRUSH_BELOW_PAPER_MM = 1.0


def execute(folder, config, cancel=lambda: False, progress=None, controller=None,
            clock=time.monotonic, sleep=time.sleep, frozen=None, motion=None, prepared=None,
            recovery_cancel=None):
    """motion: None = controller program (Web API); sdk_motion.SdkMotion = Huacheng SDK commands."""
    if frozen is not None:   # in-memory plan (no plan files): same config/model/node checks
        doc, nodes = frozen; check_frozen(doc, nodes, config)
    else:
        doc = load(folder, config, with_rows=False); nodes = load_nodes(folder, doc)
    s = settings(config)
    from calligraphy.presets import tool_of, tool_fits, TOOL_NAMES, TASK_NAMES
    brush=bool(nodes.get('calligraphy'))
    tool = config.get('mounted_tool', 'pen'); need = tool_of(nodes.get('calligraphy'))
    # One calibration per tool (画笔 / 毛笔 2026-10-26, 硬笔 2026-10-27): never run a plan made for another tool.
    if not tool_fits(tool, need):
        raise ExecutionError('TOOL_MISMATCH: 当前装的是%s，不能执行%s；请换上%s并在设置中把当前工具切换为%s'
                             % (TOOL_NAMES.get(tool, tool), TASK_NAMES[need], TOOL_NAMES[need], TOOL_NAMES[need]))
    if need == 'brush' and config.get('calligraphy', {}).get('contact_z_mm') is None:
        raise ExecutionError('BRUSH_NOT_CALIBRATED: 毛笔落笔高度尚未标定，请先在设置中标定毛笔')
    if need == 'hardpen' and config.get('hardpen', {}).get('contact_z_mm') is None:
        raise ExecutionError('HARDPEN_NOT_CALIBRATED: 硬笔落笔高度尚未标定，请先在设置中标定硬笔')
    if brush:
        if need == 'hardpen':
            from calligraphy.hardpen import profile as hardpen_profile
            hardpen_profile(config, require_verified=True)
        else:
            from calligraphy.presets import profile
            profile(config,require_verified=True)
        # Pose IO already takes about 94 ms on this controller; another 100 ms
        # sleep per completed SDK block only adds idle time. Keep the same
        # feedback/stop checks while shortening this idle interval for brush work.
        s['poll_s']=min(float(s['poll_s']),0.02)
        if s['mode']!='joint':raise ExecutionError('书法模式需要本地七轴 IK 的 joint 执行配置')
        if not home_enabled(config):
            raise ExecutionError('BRUSH_HOME_REQUIRED: 书法需要启用已标定归位点，开始和结束均先归位')
    if s['enabled'] is not True:
        raise ExecutionError('WEB_PROGRAM_DISABLED: 配置 execution.web_program.enabled 未开启')
    if not config['calibration_verified'] or (mapping_required(config) and not config['sdk_mapping_verified']):
        raise ExecutionError('实机执行前需完成纸面标定' + ('与关节映射核对' if mapping_required(config) else ''))
    ctrl = controller or Controller(config['controller'], config['robot_id'])
    motion = motion or ProgramMotion(ctrl, s, sleep)
    log = []

    def note(kind, **kw):
        kw['event'] = kind; kw['t'] = round(clock(), 3); log.append(kw)
        if progress:
            progress(kw)

    segment_wait = s['poll_s'] * (BRUSH_SEGMENT_WAIT_SCALE if brush else 1.0)
    if brush:
        note('BRUSH_CADENCE', wait_scale=BRUSH_SEGMENT_WAIT_SCALE,
             previous_wait_s=s['poll_s'], segment_wait_s=segment_wait)

    ctrl.login()
    if ctrl.axis_count() != 7:
        raise ExecutionError('控制器轴数不是 7')
    st = ctrl.state(); alarms = ctrl.active_alarms()
    first_pose = ctrl.pose()
    preparation_started = clock()
    cached = (s['mode'] == 'joint' and isinstance(prepared, JointPreparation) and
              prepared.key == preparation_key(config, nodes))
    if s['mode'] == 'joint' and not cached:
        prepared = prepare_joint(config, nodes, cancel)
    mm, chunks = build(config, nodes, s, uvw=first_pose[3:6] if s['uvw'] == 'current' else None,
                       joint_keep=prepared.keep if s['mode'] == 'joint' else None,
                       brush_blend=s.get('brush_blend') if nodes.get('calligraphy') else None)
    interp = None
    if s['mode'] == 'joint':
        interp = prepared.error_mm
    preparation = dict(cached=bool(cached), seconds=round(clock() - preparation_started, 3),
                       precomputed_seconds=prepared.seconds if s['mode'] == 'joint' else None)
    note('PREPARED', **preparation)
    z_floor = float(np.min(mm[:, 2])) - paper_margin(s, need)
    if alarms or st['_phc_alarm_'] not in ('0', '') or st['g_state_'] != '1':
        raise ExecutionError('控制器有报警或急停状态，不运动：%s %s' % (st, alarms))
    start = ctrl.pose()
    homing = home_enabled(config)
    if homing:
        # The plan starts from the fixed home joints; the arm goes there first (after the mode switch).
        dq = max(abs(a - b) for a, b in zip(home_target(config)[0], nodes['sdk_degrees'][0]))
        if dq > 0.01:
            raise ExecutionError('PLAN_NOT_FROM_HOME: 规划起点不是归位姿态（相差 %.3f 度），请重新生成预览' % dq)
    else:
        if dist3(start, mm[0]) > s['start_tolerance_mm']:
            raise ExecutionError('START_MISMATCH: 当前位置与规划起点相差 %.2f mm，请重新规划' % dist3(start, mm[0]))
        if s['mode'] == 'joint':
            q = ctrl.joints(7); dq = max(abs(a - b) for a, b in zip(q, nodes['sdk_degrees'][0]))
            if dq > s['start_tolerance_deg']:
                raise ExecutionError('START_MISMATCH: 当前关节与规划起点相差 %.3f 度，请重新规划' % dq)
    keep_auto = False
    if homing:
        try:
            require_mode_switch_clearance(config, start)
        except ExecutionError as exc:   # user decision 2026-10-18: always home automatically, never refuse
            if brush:
                # A previous controlled stop may have left the pen low in auto mode. Do not switch
                # modes there; verify the existing powered state and lift through strict homing.
                if st.get('_phc_ctrlkey') != '100':
                    raise
                require_home_ready(ctrl)
                keep_auto = True
                note('HOME_KEEP_AUTO', detail='笔尖处于低处，保持已有自动模式，先归位')
            else:
                note('WARN_LOW_START', error=str(exc))
    else:
        require_mode_switch_clearance(config, start)
    require_mode_switch_clearance(config, mm[-1])
    contact_z = config.get('calibration_source', {}).get('contact_z_mm')
    if not brush and contact_z is not None and float(np.min(mm[:, 2])) < float(contact_z) - 1e-6:
        raise ExecutionError('CONTACT_HEIGHT: 规划低于已标定落笔高度')
    note('READY', mode=s['mode'], chunks=len(chunks), blocks=sum(c['blocks'] for c in chunks), start=start,
         joint_interpolation_mm=interp, motion=type(motion).__name__)
    if cancel():
        raise CancelledByUser('CANCELLED: 上电前停止')

    moved = False; result = None
    try:
        if keep_auto or already_auto(st):
            require_home_ready(ctrl)
        else:
            ctrl.power('auto'); sleep(1.5)
        st = ctrl.state()
        if st['g_servo_statero_'] not in ('1', 'true', 'True'):
            raise ExecutionError('切换自动模式后伺服未上电')
        if hasattr(motion, 'set_speed'):   # SDK: one global speed (0..100), changeable while drawing
            note('SPEED', pct=s['draw_speed_pct'], read_back=motion.set_speed(s['draw_speed_pct']))
        settled = settle_pose(ctrl, clock=clock, sleep=sleep); shift = dist3(settled, start)
        note('POWER_ON', shift_mm=round(shift, 3), settled=settled)
        start_floor = z_floor
        if keep_auto:
            start_floor = (mode_switch_min_z(config, settled) - 60.0 -
                           float(config['calligraphy']['max_press_mm']) - float(s['below_paper_mm']))
        if shift > s['max_power_on_shift_mm'] or settled[2] < start_floor:
            if not homing or brush:
                raise ExecutionError('上电位移 %.2f mm 过大或低于纸面' % shift)
            note('WARN_POWER_ON_SHIFT', shift_mm=round(shift, 3))
        here = settled; t_all = clock(); done_node = 0
        high_z = high_air_z(nodes, mm) if brush else None
        if homing:
            moved = True
            here = go_home(ctrl, config, s, note, cancel, clock, sleep, 'HOME', motion, strict=brush)
            dq = max(abs(a - b) for a, b in zip(ctrl.joints(7), nodes['sdk_degrees'][0]))
            if dq > s['start_tolerance_deg'] or dist3(here, mm[0]) > s['start_tolerance_mm']:
                if brush:raise ExecutionError('BRUSH_HOME_OFFSET: 毛笔起始姿态未到位，请核对工具与归位标定')
                note('WARN_HOME_OFFSET', joint_deg=round(dq, 4), mm=round(dist3(here, mm[0]), 3))
        for ci, chunk in enumerate(chunks):
            idx = chunk['node_index']
            # dense planned polyline of this chunk, starting from where the arm really is
            path = [here[:3]] + [mm[i].tolist() for i in range(done_node + 1, idx[-1] + 1)]
            base = done_node              # tracker segment k is planned interval base + k
            done_node = idx[-1]
            tracker = Tracker(path)
            length = float(tracker.s[-1])
            if not motion.start(chunk['content'], cancel):
                raise CancelledByUser('CANCELLED: 启动前停止')
            moved = True
            note('CHUNK_START', chunk=ci, blocks=chunk['blocks'], length_mm=round(length, 1))
            t0 = clock(); last_move = t0; prev = here; stable = 0; last_note = t0; max_dev = 0.0
            timeout = 120.0 + length / 1.0; last_warn = -1e9
            while True:
                sleep(segment_wait)
                if cancel():
                    raise CancelledByUser('CANCELLED: 用户停止')
                motion.pump()
                p = read_pose(ctrl, note, sleep, cancel=cancel) if homing else ctrl.pose(); now = clock()
                dev = tracker.update(p); max_dev = max(max_dev, dev)
                low, off = p[2] < z_floor, dev > deviation_limit(s, nodes, mm, base + tracker.k, high_z)
                if (low or off) and (not homing or brush):
                    if low:
                        raise ExecutionError('Z %.3f 低于允许下限 %.3f' % (p[2], z_floor))
                    raise ExecutionError('偏离规划路径 %.2f mm at %s' % (dev, [round(v, 2) for v in p[:3]]))
                if (low or off) and now - last_warn >= 1.0:   # home mode: log only, never stop
                    last_warn = now
                    note('WARN_LOW' if low else 'WARN_DEVIATION', dev_mm=round(dev, 3), xyz=[round(v, 2) for v in p[:3]])
                if dist3(p, prev) > 0.02:
                    last_move = now
                prev = p
                end = mm[idx[-1]]
                stable = stable + 1 if (tracker.done() and dist3(p, end) < 0.1) else 0
                if now - last_note >= 1.0:
                    last_note = now
                    note('PROGRESS', chunk=ci, node=tracker.k, of=len(path) - 1, xyz=[round(v, 2) for v in p[:3]], dev_mm=round(dev, 3))
                if stable >= 5 and (not hasattr(motion,'idle') or motion.idle()):
                    break
                if not homing or brush:
                    if now - last_move > s['no_progress_s']:
                        raise ExecutionError('NO_PROGRESS: %.0f s 无运动（chunk %d, node %d/%d）' % (s['no_progress_s'], ci, tracker.k, len(path) - 1))
                    if now - t0 > timeout:
                        raise ExecutionError('CHUNK_TIMEOUT')
                elif now - last_move > s['no_progress_s']:
                    halted = controller_halted(ctrl)
                    if halted:
                        raise ExecutionError('CONTROLLER_HALTED: 控制器已停止（报警/急停/伺服关）%s' % halted)
                    if now - last_move > max(30.0, 3 * s['no_progress_s']):
                        # the controller ran out of program without an alarm: carry on, never abort
                        note('WARN_CHUNK_STALLED', chunk=ci, node=tracker.k, of=len(path) - 1)
                        break
                if brush:
                    # A DONE callback may have arrived during the slow pose IO.
                    # Refill only after all feedback/watchdogs and another stop
                    # check, instead of adding an avoidable wait before dispatch.
                    # SdkMotion still enforces queue_depth and checks callbacks.
                    if cancel():
                        raise CancelledByUser('CANCELLED: 用户停止')
                    motion.pump()
            motion.finish()
            here = p
            note('CHUNK_DONE', chunk=ci, seconds=round(clock() - t0, 1), max_deviation_mm=round(max_dev, 3))
        if homing:  # finish at home: high enough that the next run can switch modes without help
            here = go_home(ctrl, config, s, note, cancel, clock, sleep, 'RETURN_HOME', motion, strict=brush)
        result = dict(status='DONE', physical_motion=True, simulation=False, robot_type='TCB705', mode=s['mode'],
                      motion='sdk' if hasattr(motion, 'set_speed') else 'web_program',
                      chunks=len(chunks), blocks=sum(c['blocks'] for c in chunks), seconds=round(clock() - t_all, 1),
                      final_pose=here, preparation=preparation)
        return result
    except Exception as exc:
        try:
            stops = stop_motion(motion, isinstance(exc, CancelledByUser)) if moved else []
        except Exception as stop_exc:  # noqa: BLE001 - keep the original reason
            stops = [('stop', False, str(stop_exc))]
        note('ERROR', error=str(exc), stop=stops)
        if homing and moved and brush and isinstance(exc, CancelledByUser):
            # The first stop ends writing. A distinct second stop cancels this return; faults never
            # enter this path. Keep auto/servo state instead of switching modes while the tip is low.
            return_cancel = recovery_cancel or (lambda: False)
            try:
                if not stops or any(not isinstance(step, (list, tuple)) or len(step) < 2 or step[1] is not True for step in stops):
                    raise ExecutionError('HOME_STOP_UNCONFIRMED: 停止指令未全部确认，禁止自动归位')
                if return_cancel():
                    raise CancelledByUser('CANCELLED: 用户再次停止，取消归位')
                require_home_ready(ctrl)
                settle_pose(ctrl, clock=clock, sleep=sleep)
                require_home_ready(ctrl)
                if return_cancel():
                    raise CancelledByUser('CANCELLED: 用户再次停止，取消归位')
                go_home(ctrl, config, s, note, return_cancel, clock, sleep, 'HOME_AFTER_STOP', motion, strict=True)
            except Exception as home_exc:  # no retry after an interrupted or failed return
                try:
                    home_stops = stop_motion(motion, isinstance(home_exc, CancelledByUser))
                except Exception as stop_exc:
                    home_stops = [('stop', False, str(stop_exc))]
                stop_confirmed = (isinstance(home_stops, (list, tuple)) and bool(home_stops) and
                    all(isinstance(step, (list, tuple)) and len(step) >= 2 and step[1] is True
                        for step in home_stops))
                cancelled_again = isinstance(home_exc, CancelledByUser) and stop_confirmed
                detail = str(home_exc) if stop_confirmed else '归位停止未确认：%s' % home_exc
                note('HOME_AFTER_STOP_FAILED', error=detail, detail=detail,
                     cancelled_again=cancelled_again, stop_confirmed=stop_confirmed, stop=home_stops)
                if cancelled_again:
                    raise CancelledByUser('CANCELLED: 用户再次停止，归位未完成') from home_exc
                if not stop_confirmed:
                    raise ExecutionError('HOME_AFTER_STOP_FAILED: %s' % detail) from home_exc
                raise ExecutionError('HOME_AFTER_STOP_FAILED: 已停止书写，但归位未完成：%s' % home_exc) from home_exc
        if homing and moved and not brush:
            halted = controller_halted(ctrl)
            if halted:
                note('HOME_AFTER_STOP_SKIPPED', reason=halted)
            else:
                try:
                    ctrl.power('auto'); sleep(0.5)
                    go_home(ctrl, config, s, note, lambda: False, clock, sleep, 'HOME_AFTER_STOP', motion)
                except Exception as home_exc:  # noqa: BLE001
                    note('HOME_AFTER_STOP_FAILED', error=str(home_exc))
        if isinstance(exc, CancelledByUser):
            raise
        raise ExecutionError(str(exc)) from exc
    finally:
        ref, steps = restore_safe(ctrl, config, clock=clock, sleep=sleep,
                                 settle_timeout=COMPLETED_RESTORE_SETTLE_S if result is not None else 6.0,
                                 note=note)
        note('RESTORE', steps=steps, deferred=ref is None)
        # watch the arm after the auto->manual switch (transient dips of ~15 mm were seen)
        try:
            if ref is None:
                raise ExecutionError('RESTORE_DEFERRED: 低处或反馈不可靠，未切模式；请人工处理并重新确认动作')
            low = ref[2]; far = 0.0; t_w = clock()
            while clock() - t_w < s['post_restore_watch_s']:
                sleep(0.2); p = ctrl.pose(); low = min(low, p[2]); far = max(far, dist3(p, ref))
            settled = settle_pose(ctrl, clock=clock, sleep=sleep, timeout=10.0)
            note('POST_RESTORE', max_dip_mm=round(ref[2] - low, 3), max_displacement_mm=round(far, 3),
                 settled=[round(v, 3) for v in settled], settled_offset_mm=round(dist3(settled, ref), 3))
        except Exception as exc:  # noqa: BLE001 - observation only
            note('POST_RESTORE', error=str(exc))
        if result is not None:
            result['restore_deferred'] = ref is None
            result['log'] = log[-50:]
            result['post_restore'] = next((e for e in reversed(log) if e['event'] == 'POST_RESTORE'), None)
