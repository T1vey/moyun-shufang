"""Fixed-period, single-owner STS execution. Reference bounds are not vibration measurements."""
import hashlib
import copy
import json
import math
import queue
import threading
import time
import numpy as np
from protocol import exchange_deadline, servo_snapshot, ProbeError
from motion import (angles_from_counts, counts_from_angles, sync, sync_position_profile)
from feedback_control import JointFeedbackController, PenPhaseCoordinator, POLICY

VERSION = 'motion-smooth-v1'
SCHEMA = 'so101-motion-execution-v1'
LIFT_GUARD_VERSION = 'feedback-only-lift-guard-v2'


class LiftCompletionGuard:
    """Keep correcting an uncleared lift; stop only when feedback is lost.

    Height progress and elapsed waiting time are diagnostics, not abort
    conditions. The scheduler still requires measured clearance for XY travel
    and checks the user's stop request every cycle.
    """
    def __init__(self, config=None):
        cfg = dict(config or {})
        self.feedback_timeout_s = float(cfg.get('lift_feedback_timeout_s', 1.))
        self.progress_m = float(cfg.get('lift_progress_m', .0005))
        if not all(math.isfinite(v) and v > 0 for v in
                   (self.feedback_timeout_s, self.progress_m)):
            raise ValueError('Invalid lift completion guard')
        self.reset()

    def reset(self):
        self.stroke = None; self.started = None; self.last_progress = None
        self.last_feedback = None; self.sample_time = None; self.best_margin = None

    def observe(self, stroke, detail, sample_time, now):
        if self.started is None or stroke != self.stroke:
            self.reset(); self.stroke = stroke
            self.started = self.last_progress = self.last_feedback = now
        detail = detail or {}
        margins = []
        for actual, required in (('actual_rise_m', 'required_rise_m'),
                                 ('actual_plane_height_m', 'required_plane_height_m'),
                                 ('measured_height_m', 'required_height_m')):
            if detail.get(actual) is not None and detail.get(required) is not None:
                value = float(detail[actual])-float(detail[required])
                if math.isfinite(value): margins.append(value)
        # Repeated reads at the same angle are valid feedback; reused timestamps
        # and missing/invalid height feedback must not conceal a lost connection.
        if (detail.get('fresh') and margins and
                (self.sample_time is None or sample_time > self.sample_time)):
            self.sample_time = sample_time; self.last_feedback = now
            margin = min(margins)
            if self.best_margin is None or margin >= self.best_margin+self.progress_m-1e-12:
                self.best_margin = margin; self.last_progress = now
        reason = None
        if now-self.last_feedback >= self.feedback_timeout_s:
            reason = 'feedback_timeout'
        if reason is None: return None
        return dict(version=LIFT_GUARD_VERSION, reason=reason, stroke=stroke,
                    elapsed_s=now-self.started, no_progress_s=now-self.last_progress,
                    feedback_missing_s=now-self.last_feedback, clearance=detail,
                    policy='stop and hold; no uncleared XY travel or automatic home')

    def summary(self):
        return dict(version=LIFT_GUARD_VERSION, timeout_s=None,
                    no_progress_timeout_s=None,
                    feedback_timeout_s=self.feedback_timeout_s, progress_m=self.progress_m,
                    policy='continue lift correction until measured clearance or user stop; stop on missing feedback')


class MotionCurve:
    def __init__(self, result, machine):
        import planning
        from r1a.model import Model
        from r1b.retiming import derivative_bounds_many, legal_segments
        from r1b.continuous import evaluate
        self.contract = dict(getattr(result, 'execution_contract', None) or {})
        rows = getattr(result, 'trajectory_segments', None)
        if (self.contract.get('schema') != SCHEMA
                or self.contract.get('motion_algorithm_version') != VERSION
                or result.metrics.get('motion_algorithm_version') != VERSION
                or not isinstance(rows, list) or not 1 <= len(rows) <= 10000):
            raise ValueError('不支持或缺少新版运动执行契约，请重新规划')
        vertical_drawing = ((machine.get('execution',{}).get('vertical_pen_lift') is True
                             or self.contract.get('pen_lift_policy') == 'planned_vertical_v2')
                            and any(r.get('stroke',-1)>=0 and r.get('phase')=='DRAW' for r in rows))
        if vertical_drawing and self.contract.get('pen_lift_policy') not in ('world_vertical_v1', 'planned_vertical_v2'):
            raise ValueError('该轨迹未采用全程竖直抬笔，请重新规划')
        if (self.contract.get('motion_mode') == 'sugar_fast'
                and self.contract.get('pen_lift_policy') != 'planned_vertical_v2'):
            raise ValueError('糖画快速模式需要新版预规划竖直抬笔，请重新规划')
        self.model, self.machine = Model(machine['model']), machine
        self.period = float(self.contract.get('command_period_s', 0))
        if not math.isfinite(self.period) or not .005 <= self.period <= .2:
            raise ValueError('Invalid fixed command period')
        self.rows = rows
        self.coeffs = np.asarray([r['coeffs'] for r in rows], dtype=float)
        if self.coeffs.shape != (len(rows), 6, 5) or not np.isfinite(self.coeffs).all():
            raise ValueError('Invalid motion coefficients')
        self.starts = np.asarray([r['start_time_s'] for r in rows], dtype=float)
        self.times = np.asarray([r['duration_s'] for r in rows], dtype=float)
        self.ends = self.starts+self.times
        self.limits = np.asarray([self.contract.get(name) for name in
            ('joint_max_velocity_rad_s', 'joint_max_acceleration_rad_s2', 'joint_max_jerk_rad_s3')], dtype=float)
        if (self.limits.shape != (3, 5) or not np.isfinite(self.limits).all() or np.any(self.limits <= 0)
                or self.starts.shape != self.times.shape or not np.isfinite(self.starts).all()
                or not np.isfinite(self.times).all() or np.any(self.times <= 0)
                or abs(self.starts[0]) > 1e-10 or np.any(np.abs(self.starts[1:]-self.ends[:-1]) > 1e-8)):
            raise ValueError('Invalid motion segment timing/limits')
        if abs(round(self.ends[-1]/self.period)*self.period-self.ends[-1])>1e-8:
            raise ValueError('Motion duration is not aligned to the grid')
        # Canonicalise only after checking raw durations/contiguity. A few
        # ULPs must not change the pen-down meaning at a phase boundary.
        if len(rows)>1:
            self.ends[:-1] = self.starts[1:]
        self.ends[-1] = round(self.ends[-1]/self.period)*self.period
        bounds = derivative_bounds_many(self.coeffs, self.times)
        if not legal_segments(self.coeffs, self.model.limits).all():
            raise ValueError('Motion segment exceeds joint limits')
        if any(np.any(bound > limit*(1+1e-8)) for bound, limit in zip(bounds, self.limits)):
            raise ValueError('Motion segment exceeds v/a/jerk contract')
        self.peaks = np.asarray([b.max(axis=0) for b in bounds])
        self.duration = float(self.ends[-1])
        cycles = round(self.duration/self.period)
        if abs(cycles*self.period-self.duration) > 1e-8:
            raise ValueError('Motion duration is not aligned to the grid')
        self.stops = []
        for i, row in enumerate(rows):
            if (row.get('phase') not in ('APPROACH', 'TRAVEL', 'LOWER', 'DRAW', 'LIFT', 'MOVE')
                    or type(row.get('stroke')) is not int or type(row.get('motion_block_id')) is not int):
                raise ValueError('Invalid motion phase/block')
            for field in ('segment_start_m', 'segment_end_m', 'axis_start', 'axis_end'):
                value = np.asarray(row[field], dtype=float)
                if value.shape != (3,) or not np.isfinite(value).all():
                    raise ValueError('Invalid motion geometry metadata')
                if field.startswith('axis') and abs(np.linalg.norm(value)-1.)>1e-6:
                    raise ValueError('Invalid motion pen axis')
                if (vertical_drawing and row['stroke']>=0 and row['phase'] in ('DRAW','LOWER','LIFT')
                        and field.startswith('axis') and not np.allclose(value,[0.,0.,-1.],atol=1e-8,rtol=0)):
                    raise ValueError('绘画与抬笔的笔轴必须保持竖直，请重新规划')
            if row.get('hard_stop_end'):
                self.stops.append(float(self.ends[i]))
                if abs(round(self.ends[i]/self.period)*self.period-self.ends[i]) > 1e-8:
                    raise ValueError('Rest boundary is not on the grid')
        if not self.stops or abs(self.stops[-1]-self.duration) > 1e-8:
            raise ValueError('Missing final rest boundary')
        # Evaluate every boundary in two NumPy calls, preserving the exact
        # Horner arithmetic and all continuity/rest checks.
        boundaries0 = evaluate(np.moveaxis(self.coeffs, 1, 0), 0., self.times[:, None])
        boundaries1 = evaluate(np.moveaxis(self.coeffs, 1, 0), 1., self.times[:, None])
        q0, v0, a0 = (value[0] for value in boundaries0)
        q1, v1, a1 = (value[-1] for value in boundaries1)
        if max(np.max(np.abs(x)) for x in (v0, a0, v1, a1)) > 1e-7:
            raise ValueError('Motion must start/end at rest')
        self.q0 = q0
        if any(np.any(np.abs(x[:-1]-y[1:]) > 1e-7) for x, y in zip(boundaries1, boundaries0)):
            raise ValueError('Motion segment continuity mismatch')
        stopped = np.asarray([bool(row.get('hard_stop_end')) for row in rows])
        if any(np.any(np.abs(x[stopped]) > 1e-7) for x in boundaries1[1:]):
            raise ValueError('Nonzero velocity/acceleration at a stop')
        commands = result.commands
        if not commands or len(commands) != cycles:
            raise ValueError('Motion commands do not match segment duration')
        # The displayed/persisted integer command path must match the executed
        # coefficients. This validation completes before a real port is opened.
        for start in range(0, len(commands), 512):
            part = commands[start:start+512]
            stamps = np.asarray([c['t_s'] for c in part])
            wanted = np.arange(start+1, start+len(part)+1)*self.period
            if not np.isfinite(stamps).all() or not np.allclose(stamps, wanted, atol=1e-9, rtol=0):
                raise ValueError('Invalid fixed-grid commands')
            idx = np.clip(np.searchsorted(self.ends, stamps, side='left'), 0, len(rows)-1)
            u = np.clip((stamps-self.starts[idx])/self.times[idx], 0, 1)
            q, _, _ = evaluate(np.moveaxis(self.coeffs[idx], 1, 0), u[:, None], self.times[idx, None])
            command_q = np.asarray([c['q_rad'] for c in part], dtype=float)
            if command_q.shape != q.shape or not np.isfinite(command_q).all() or np.max(np.abs(q-command_q)) > 1e-8:
                raise ValueError('Displayed command / polynomial mismatch')
            from motion import quantized_angles_many
            quantized_angles_many(machine, command_q)
            for c, i in zip(part, idx):
                if (c.get('phase') != rows[i]['phase'] or c.get('stroke') != rows[i]['stroke']
                        or bool(c.get('pen_down')) != (rows[i]['phase'] == 'DRAW')):
                    raise ValueError('Motion command provenance mismatch')
        self.settings = ServoSettings(machine, self.contract)
        if self.contract.get('pen_lift_policy') == 'planned_vertical_v2':
            from planned_execution import PlannedFeedforward
            feedforward = PlannedFeedforward(machine, self.model)
            feedforward.validate_curve(self)
            if self.settings.frame_speed_enabled:
                previous = counts_from_angles(machine, self.q0)
                for command in result.commands:
                    values, _ = feedforward.target(self, self.sample(command['t_s']))
                    self.settings.frame_speeds(values, previous, self.period)
                    previous = values
        import copy
        # Own the validated execution metadata. A caller retaining the input
        # plan cannot alter a compiled curve while it is being handed off.
        self.rows = copy.deepcopy(rows)
        self.machine = copy.deepcopy(machine)
        self.contract = copy.deepcopy(self.contract)

    def sample(self, stamp):
        from r1b.continuous import evaluate
        from r1b.path import lerp_axis
        stamp = min(self.duration, max(0., float(stamp)))
        index = min(len(self.rows)-1, int(np.searchsorted(self.ends, stamp, side='left')))
        row = self.rows[index]
        u = min(1., max(0., (stamp-self.starts[index])/self.times[index]))
        q, v, a = evaluate(self.coeffs[index], u, self.times[index])
        c = self.coeffs[index]
        j = (6*c[3]+24*c[4]*u+60*c[5]*u*u)/self.times[index]**3
        p0, p1 = np.asarray(row['segment_start_m']), np.asarray(row['segment_end_m'])
        reference = self.model.pose(q)[:3, 3]
        return dict(t_s=stamp, q_rad=q.tolist(), velocity_rad_s=v.tolist(), acceleration_rad_s2=a.tolist(),
                    jerk_rad_s3=j.tolist(), tip_target_m=((1-u)*p0+u*p1).tolist(),
                    tip_reference_m=reference.tolist(), axis_target=lerp_axis(row['axis_start'], row['axis_end'], u).tolist(),
                    phase=row['phase'], stroke=row['stroke'], pen_down=row['phase'] == 'DRAW',
                    motion_block_id=row['motion_block_id'], source_segment_id=row.get('source_segment_id'),
                    path_segment_index=index, segment_start_m=p0.tolist(), segment_end_m=p1.tolist(),
                    endpoint_pause=bool(row.get('endpoint_pause')))

    def next_stop(self, stamp):
        index = int(np.searchsorted(self.stops, stamp+1e-9, side='right'))
        return self.stops[min(index, len(self.stops)-1)]


def align_start(curve, current, backend=None, cancel=None):
    """Accept encoder drift without altering the saved DRAW path or its origin."""
    expected = counts_from_angles(curve.machine, curve.q0)
    delta = {sid: current[sid]-expected[sid] for sid in expected}
    detail = dict(applied=any(delta.values()), measured_counts=dict(current),
                  planned_counts=expected, delta_counts=delta, duration_s=0.)
    if not detail['applied']:
        return curve, detail
    adapted = StartAlignedCurve(curve, current, backend=backend, cancel=cancel)
    detail['duration_s'] = adapted.alignment_duration
    detail['replaced_approach_s']=adapted.cut_time
    return adapted, detail


class StartAlignedCurve:
    """One scheduler joins measured rest -> planned rest -> unchanged drawing.

    The entry move shares the servo settings and has bounded derivatives. There
    is no encoder-distance gate or separate exact-position settling test.
    """
    def __init__(self, base, current, backend=None, cancel=None):
        import planning
        self.base = base
        self.machine, self.model, self.settings = base.machine, base.model, base.settings
        self.contract, self.period, self.limits = base.contract, base.period, base.limits
        self.q0 = np.asarray(angles_from_counts(self.machine, current), dtype=float)
        counts_from_angles(self.machine, self.q0)
        # Join above the first stroke. Returning to an old low q0 would put
        # the pen back on the paper only to lift it again immediately.
        lower=next((r for r in base.rows if r['phase']=='LOWER' and r['stroke']>=0),None)
        self.cut_time=float(lower['start_time_s']) if lower is not None else 0.
        target_q=np.asarray(base.sample(self.cut_time)['q_rad'])
        expected=counts_from_angles(self.machine,target_q)
        result,_,_=planning.build_pen_up_transfer(self.machine,current,expected,
            backend=backend, cancel=cancel,
            motion_mode=base.contract.get('motion_mode','gentle'),allow_low_endpoint=True,end_q_rad=target_q,
            joint_limits=self.limits*.9)
        if result.status!='OK':raise ValueError('起始抬笔接入规划失败：'+str(result.status))
        self.prefix=MotionCurve(result,self.machine)
        self.alignment_duration=self.prefix.duration
        self.peaks=np.maximum(base.peaks,self.prefix.peaks)
        self.duration=self.alignment_duration+base.duration-self.cut_time
        self.stops=self.prefix.stops+[self.alignment_duration+s-self.cut_time for s in base.stops if s>self.cut_time+1e-9]
        self.index_offset=len(self.prefix.rows)
        self.block_offset=self.prefix.rows[-1]['motion_block_id']+1

    def sample(self, stamp):
        stamp = min(self.duration, max(0., float(stamp)))
        if stamp > self.alignment_duration:
            sample = dict(self.base.sample(self.cut_time+stamp-self.alignment_duration))
            sample['t_s'] = stamp
            sample['path_segment_index'] += self.index_offset
            sample['motion_block_id'] += self.block_offset
            return sample
        return self.prefix.sample(stamp)

    def next_stop(self, stamp):
        index = int(np.searchsorted(self.stops, stamp+1e-9, side='right'))
        return self.stops[min(index, len(self.stops)-1)]


class ServoSettings:
    def __init__(self, machine, contract):
        profile = dict(contract.get('servo_profile') or {})
        ids = [j['id'] for j in machine['joints']]
        def fields(value, lower, upper):
            if isinstance(value, dict):
                result = {sid: value.get(str(sid), value.get(sid)) for sid in ids}
            elif isinstance(value, list):
                if len(value) != len(ids):
                    raise ValueError('Servo profile length mismatch')
                result = dict(zip(ids, value))
            else:
                result = {sid: value for sid in ids}
            if any(type(v) is not int or not lower <= v <= upper for v in result.values()):
                raise ValueError('Invalid servo profile codes')
            return result
        stream_policy = profile.get('position_stream_policy')
        if stream_policy not in (None, 'sts_phase12_position_v1'):
            raise ValueError('Unknown documented position stream policy')
        self.documented_stream = stream_policy is not None
        self.speeds = fields(profile.get('speed_codes', 200), 1, 700 if self.documented_stream else 200)
        requested_frame_speed = profile.get('frame_speed_enabled', False) is True
        self.unverified_policy = profile.get('unverified_policy', 'preserve_static')
        if self.unverified_policy not in ('preserve_static', 'reject'):
            raise ValueError('Invalid servo profile unverified_policy')
        self.frame_speed_enabled = requested_frame_speed and profile.get('units_verified') is True
        if requested_frame_speed and not self.frame_speed_enabled and self.unverified_policy == 'reject':
            raise ValueError('逐帧速度码单位尚未实测验证，不能启用')
        self.frame_speed_min = profile.get('frame_speed_min_code', 20)
        self.frame_speed_margin = float(profile.get('frame_speed_margin', 1.15))
        if (type(self.frame_speed_min) is not int or not 1 <= self.frame_speed_min <= 200
                or (requested_frame_speed and self.frame_speed_min > min(self.speeds.values()))
                or not math.isfinite(self.frame_speed_margin) or not 1. <= self.frame_speed_margin <= 2.):
            raise ValueError('Invalid frame speed limits')
        codes = profile.get('acceleration_codes')
        self.accelerations = None
        if codes is not None:
            if profile.get('units_verified') is not True:
                raise ValueError('舵机加速度单位尚未验证，不能应用加速度码')
            self.accelerations = fields(codes, 1, 254)
        if profile.get('units_verified') is True:
            registers=profile.get('verified_registers')
            if not isinstance(registers,dict) or not registers:
                raise ValueError('Missing firmware/register signature for verified units')
            unit_v = np.asarray(profile.get('speed_unit_rad_s'), dtype=float)
            unit_a = np.asarray(profile.get('acceleration_unit_rad_s2'), dtype=float)
            if unit_v.ndim == 0: unit_v = np.full(5, float(unit_v))
            if unit_a.ndim == 0: unit_a = np.full(5, float(unit_a))
            if (unit_v.shape != (5,) or unit_a.shape != (5,) or not np.isfinite([unit_v, unit_a]).all()
                    or np.any(unit_v <= 0) or np.any(unit_a <= 0)):
                raise ValueError('Missing verified servo unit mapping')
            v = np.asarray(contract['joint_max_velocity_rad_s'])
            a = np.asarray(contract['joint_max_acceleration_rad_s2'])
            if np.any(v > np.asarray([self.speeds[sid] for sid in ids])*unit_v+1e-12):
                raise ValueError('Trajectory velocity exceeds verified servo cap')
            if self.accelerations and np.any(a > np.asarray([self.accelerations[sid] for sid in ids])*unit_a+1e-12):
                raise ValueError('Trajectory acceleration exceeds verified servo cap')
            self.speed_units = dict(zip(ids, unit_v.tolist()))
        if self.frame_speed_enabled and not self.accelerations:
            raise ValueError('逐帧位置速度需要已验证的加速度码')
        if self.frame_speed_enabled and len({self.accelerations[sid] for sid in (2, 3, 4) if sid in self.accelerations}) > 1:
            raise ValueError('预规划抬笔 ID2/ID3/ID4 需要相同的已验证加速度码')
        self.status = 'verified_profile' if self.accelerations else 'existing_acceleration_preserved_unverified'
        if self.frame_speed_enabled:
            self.status = 'verified_per_frame_position_profile'
        elif requested_frame_speed:
            self.status = 'frame_speed_disabled_units_unverified_static_fallback'
        self.verified_registers = profile.get('verified_registers') if profile.get('units_verified') is True else None
        self.signature_fields = ('firmware','velocity_unit','maximum_acceleration','acceleration_multiplier')
        if self.documented_stream:
            # FEETECH STS phase bit 2 selects one encoder step/second. This is
            # a documented mapping, NOT a fabricated dynamic calibration. A
            # fixed cap avoids restarting a slow internal ramp every 20 ms.
            # Positions still follow the bounded, sampled joint trajectory.
            if requested_frame_speed or profile.get('units_verified') is True or codes is not None:
                raise ValueError('Documented position stream preserves acceleration and uses a fixed speed cap')
            signature = profile.get('verified_registers')
            self.signature_fields = ('model','mode','firmware','phase','velocity_unit','maximum_speed',
                                     'acceleration','acceleration_multiplier')
            if not isinstance(signature, dict) or set(map(str, signature)) != set(map(str, ids)):
                raise ValueError('Documented stream requires readback signatures for all joints')
            for sid in ids:
                row = signature.get(str(sid), signature.get(sid))
                required = dict(model=777,mode=0,phase=12,velocity_unit=50,
                                acceleration=0,acceleration_multiplier=0)
                if (not isinstance(row,dict) or any(row.get(k)!=v for k,v in required.items())
                        or not isinstance(row.get('firmware'),dict)
                        or type(row.get('maximum_speed')) is not int
                        or self.speeds[sid] > row['maximum_speed']*50):
                    raise ValueError('Documented STS speed mapping does not match the readback signature')
            unit = 2*math.pi/4096
            if np.any(np.asarray(contract['joint_max_velocity_rad_s'])*1.15 >
                      np.asarray([self.speeds[sid]*unit for sid in ids])+1e-12):
                raise ValueError('Documented servo speed cap cannot cover the planned joint velocity')
            self.verified_registers = signature
            self.status = 'documented_sts_position_stream_acceleration_preserved'
        self.hash = hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.last_profile = None

    def frame_speeds(self, counts, previous, period):
        if not math.isfinite(period) or period <= 0 or set(counts) != set(previous):
            raise ValueError('Invalid per-frame speed interval/previous target')
        speeds = {}
        for sid, count in counts.items():
            velocity = abs(count-previous[sid])*(2*math.pi/4096)/period
            code = max(self.frame_speed_min, int(math.ceil(velocity*self.frame_speed_margin/self.speed_units[sid])))
            if code > self.speeds[sid]:
                raise ValueError('ID %s 逐帧所需速度码超过已验证上限，需要重新规划或降低速度' % sid)
            speeds[sid] = code
        return speeds

    def write(self, port, counts, previous=None, period=None):
        speeds = self.speeds
        if self.frame_speed_enabled and previous is not None:
            speeds = self.frame_speeds(counts, previous, period)
        if self.accelerations:
            sync_position_profile(port, counts, speeds, self.accelerations)
        else:
            sync(port, 42, {sid: [count & 255, count >> 8, 0, 0,
                                speeds[sid] & 255, speeds[sid] >> 8] for sid, count in counts.items()})
        self.last_profile = dict(speed_codes=dict(speeds), acceleration_codes=self.accelerations,
                                 per_frame=self.frame_speed_enabled and previous is not None)


class Progress:
    """Shared time warp. Whole-ramp triangle bounds include the chain-rule terms."""
    def __init__(self, curve):
        self.curve = curve; self.position = 0.
        self.rate = 1.; self.first = self.second = 0.
        self.ramp = None; self.elapsed = 0.; self.length = 0.; self.goal = 1.
        self.pending = None; self.changes = 0

    def target(self, rate):
        from r1b.retiming import quintic_full, _HULL5
        from r1b.continuous import _HULL4, _HULL3
        rate = min(1., max(.25, float(rate)))
        if abs(rate-self.goal) < 1e-9:
            self.pending = None
            return True
        v, a, j = self.curve.peaks
        vm, am, jm = self.curve.limits
        duration = 1.
        for _ in range(12):
            c = quintic_full(np.array([self.rate]), np.array([rate]), np.array([self.first]),
                             np.zeros(1), np.array([self.second]), np.zeros(1), duration)
            controls = _HULL5 @ c
            rmax = float(controls.max()); rmin = float(controls.min())
            first = np.arange(1, 6)[:, None]*c[1:]/duration
            second = np.arange(1, 5)[:, None]*first[1:]/duration
            rd = float(np.abs(_HULL4 @ first).max()); rdd = float(np.abs(_HULL3 @ second).max())
            if (rmin >= .25-1e-10 and rmax <= 1.+1e-10
                    and np.all(v*rmax <= vm*(1+1e-9))
                    and np.all(a*rmax*rmax+v*rd <= am*(1+1e-9))
                    and np.all(j*rmax**3+3*a*rmax*rd+v*rdd <= jm*(1+1e-9))):
                self.ramp = c[:, 0]; self.length = duration; self.elapsed = 0.; self.goal = rate
                self.changes += 1; self.pending = None
                return True
            duration *= 1.5
        self.pending = rate
        return False

    def advance(self, dt):
        from r1b.continuous import evaluate
        distance = self.rate*dt
        if self.ramp is not None:
            old, new = self.elapsed, min(self.length, self.elapsed+dt)
            u0, u1 = old/self.length, new/self.length
            distance = self.length*sum(c*(u1**(k+1)-u0**(k+1))/(k+1)
                                      for k, c in enumerate(self.ramp))
            r, dr, ddr = evaluate(self.ramp[:, None], u1, self.length)
            self.rate, self.first, self.second = float(r[0]), float(dr[0]), float(ddr[0])
            self.elapsed = new
            if new >= self.length:
                distance += self.goal*max(0., dt-(new-old))
                self.rate = self.goal; self.first = self.second = 0.; self.ramp = None
        stop = self.curve.next_stop(self.position)
        self.position = min(stop, self.position+max(0., distance), self.curve.duration)
        if self.pending is not None and self.ramp is None:
            self.target(self.pending)
        return self.position


class BufferedAudit:
    """Only the log writer is a worker thread. Serial IO remains single-owner."""
    def __init__(self, sink, enabled=True):
        self.sink, self.enabled = sink, enabled; self.error = None
        self.dropped = 0
        self.queue = queue.Queue(maxsize=256); self.worker = None
        if enabled:
            self.worker = threading.Thread(target=self._run, daemon=True)
            self.worker.start()

    def _run(self):
        while True:
            item = self.queue.get()
            try:
                if item is None: return
                if self.error is None:
                    self.sink(*item)
            except Exception as exc:
                self.error = exc
            finally:
                self.queue.task_done()

    def check(self):
        return self.error is None

    def __call__(self, event, detail):
        if not self.check():
            self.dropped += 1
            return
        if not self.enabled:
            try: self.sink(event, detail)
            except Exception as exc: self.error = exc; self.dropped += 1
            return
        try:
            self.queue.put_nowait((event, detail))
        except queue.Full:
            self.dropped += 1

    def close(self):
        if self.enabled:
            try: self.queue.put(None, timeout=.2)
            except queue.Full:
                # Make room for termination without blocking motion completion.
                try: self.queue.get_nowait(); self.queue.task_done(); self.dropped += 1
                except queue.Empty: pass
                self.queue.put_nowait(None)
            self.worker.join(2.)
        self.check()


class SerialMotionScheduler:
    def __init__(self, executor, curve):
        self.executor, self.curve = executor, curve
        self.port, self.machine = executor.port, executor.machine
        cfg = dict(self.machine.get('execution') or {})
        classic=curve.contract.get('motion_mode')=='classic_fast'
        self.planned_vertical = curve.contract.get('pen_lift_policy') == 'planned_vertical_v2'
        self.execution_policy=('planned_vertical_v2_feedforward' if self.planned_vertical else
                               ('classic_nominal_direct' if classic else POLICY))
        if classic or self.planned_vertical:
            # The reference v0.6.1 sends the planned joint positions directly.
            # Preserve live geometry, but do not stack PS-side error/height
            # corrections onto them; each servo retains its own position loop.
            cfg=copy.deepcopy(cfg)
            cfg.setdefault('feedback_control',{})['enabled']=False
            cfg.setdefault('normal_feedback',{})['enabled']=False
            cfg.setdefault('pen_phase',{})['enabled']=False
            # An explicitly configured ID3-before-ID4 release also applies
            # when the drawing itself uses the classic nominal path.
            cfg['measured_pen_release'] = (cfg.get('elbow_first_lift',False) is True
                                           or cfg.get('vertical_pen_lift',False) is True)
            if self.planned_vertical:
                cfg['measured_pen_release'] = False
                cfg['pen_lift_policy'] = 'planned_vertical_v2'
            self.machine=copy.deepcopy(self.machine);self.machine['execution']=cfg
        self.cfg = cfg
        self.period = curve.period
        self.feedback_period = self._positive('position_feedback_period_s', .1)
        self.health_period = self._positive('health_feedback_period_s', 1.)
        # Five USB serial round trips need their own bounded transaction budget.
        # A 20ms command period must not reduce that total to 6ms. The budget is
        # an upper timeout, not a sleep or reserved time added to every frame.
        default_feedback_budget = .04 if self.planned_vertical else min(.012, self.period*.3)
        self.feedback_budget = self._positive('feedback_budget_s', default_feedback_budget)
        self.stale_limit = self._positive('feedback_stale_s', .25)
        self.feedback_recovery_budget = min(.1, self.stale_limit/2)
        self.warn_late = self._positive('lateness_warn_s', .005)
        self.fault_late = self._positive('lateness_fault_s', .05)
        self.write_failure_timeout = self._positive('write_failure_timeout_s', .2)
        invalid_budget = (self.feedback_budget > min(.1, self.stale_limit/2)
                          if self.planned_vertical else self.feedback_budget >= self.period)
        if invalid_budget or self.fault_late < self.warn_late:
            raise ValueError('Invalid feedback/command timing budget')
        self.lift_guard = LiftCompletionGuard(cfg)
        self.audit = BufferedAudit(executor.audit, bool(cfg.get('buffered_audit', True)))
        self.settings = curve.settings
        self.controller = JointFeedbackController(self.machine, self.period, cfg.get('feedback_control'))
        self.pen_phases = PenPhaseCoordinator(curve, cfg.get('pen_phase'))
        from pen_contact import MeasuredPenRelease
        self.release=MeasuredPenRelease(self.machine,curve.model,self.period)
        from planned_execution import PlannedFeedforward, PlannedLiftMonitor
        self.feedforward = PlannedFeedforward(self.machine, curve.model) if self.planned_vertical else None
        self.planned_lift = PlannedLiftMonitor(self.machine, curve.model) if self.planned_vertical else None
        self.last_checked_lift = None
        if self.feedforward:
            self.feedforward.validate_curve(curve)
            if curve.settings.frame_speed_enabled:
                previous = counts_from_angles(self.machine, curve.q0)
                for k in range(1, int(round(curve.duration/self.period))+1):
                    values, _ = self.feedforward.target(curve, curve.sample(k*self.period))
                    curve.settings.frame_speeds(values, previous, self.period)
                    previous = values
        from cartesian_feedback import NormalFeedbackController
        self.normal_control=NormalFeedbackController(self.machine,curve.model,self.period,cfg.get('normal_feedback'))
        rows=getattr(curve,'rows',getattr(getattr(curve,'base',None),'rows',[]))
        if (self.normal_control.enabled or self.release.enabled) and any(
                row['phase'] in ('DRAW','LOWER','LIFT') for row in rows):
            self.feedback_period=min(self.feedback_period,self.period)
        self.lift_wait_frames=0;self.lift_wait_key=None
        self.release_control_active=False
        self.parameters_ready = False
        self.last_counts = None; self.last_command = None
        self.last_nominal_counts = None
        self.feedback = None; self.measured = 0.; self.measurements = {}
        self.timing = dict(frames_sent=0, write_failures=0, feedback_failures=0,
            max_feedback_s=0., max_lateness_s=0., schedule_stretch_s=0., max_feedback_age_s=0.,
            max_following_error_counts=0, guard_policy=executor.guard_policy, missed_deadlines=0,
            trajectory_frames_sent=0, refinement_frames_sent=0, settle_frames_sent=0,
            feedback_budget_s=self.feedback_budget, feedback_stale_s=self.stale_limit,
            feedback_recovery_budget_s=self.feedback_recovery_budget,
            feedback_recovery_attempts=0, feedback_recovery_successes=0)
        self.intervals = []; self.last_sent = None
        self.quality_warning = False

    def _positive(self, name, default):
        value = float(self.cfg.get(name, default))
        if not math.isfinite(value) or value <= 0:
            raise ValueError('invalid execution.' + name)
        return value

    def _wait(self, until):
        while time.monotonic() < until:
            if self.executor.cancelled(): raise RuntimeError('STOPPED')
            self.audit.check()
            time.sleep(min(.005, max(0., until-time.monotonic())))

    def _read_positions(self, deadline):
        values, timestamps = {}, {}
        begin = time.monotonic()
        try:
            for joint in self.machine['joints']:
                if self.executor.cancelled(): raise RuntimeError('STOPPED')
                sid = joint['id']; before = time.monotonic()
                value = exchange_deadline(self.port, sid, 'position_speed', deadline)
                after = time.monotonic(); count = value['position_count']
                if value.get('status_byte'):
                    last=getattr(self,'status_flag_logged',{}).get(sid,0.)
                    if after-last>=1.:
                        self.audit('SERVO_STATUS_FLAG',dict(id=sid,status_byte=value['status_byte'],
                            position_count=count,feedback_valid=True,policy='retain validated encoder payload'))
                        if not hasattr(self,'status_flag_logged'):self.status_flag_logged={}
                        self.status_flag_logged[sid]=after
                if not joint['min_count'] <= count <= joint['max_count']:
                    if self.planned_vertical:
                        raise ValueError('ID %s 编码器反馈超出计数限位' % sid)
                    self.quality_warning = True
                values[sid] = count
                timestamps[sid] = dict(begin_s=before, end_s=after, speed_raw=value['speed_raw'])
            # A complete USB read can return after its deadline if the process
            # was descheduled. Late data must not refresh the stale watchdog.
            completed_at = time.monotonic()
            if completed_at > deadline:
                raise ProbeError('TIMEOUT', 'Complete feedback group exceeded its deadline')
        except (ProbeError, OSError) as exc:
            self.timing['feedback_failures'] += 1
            self.audit('FEEDBACK_MISSED', dict(error=str(exc)[:120], measured_at_s=self.measured, fresh=False,
                budget_s=max(0., deadline-begin), elapsed_s=time.monotonic()-begin,
                completed_ids=list(values), failed_id=sid if sid not in values else None,
                error_code=getattr(exc,'code','IO_ERROR'),
                joint_elapsed_s={key:row['end_s']-row['begin_s'] for key,row in timestamps.items()},
                failed_request_elapsed_s=time.monotonic()-before if sid not in values else 0.,
                complete_but_late=len(values)==len(self.machine['joints'])))
            return False
        duration = completed_at-begin
        self.feedback, self.measured, self.measurements = values, completed_at, timestamps
        self.timing['max_feedback_s'] = max(self.timing['max_feedback_s'], duration)
        return True

    def _read_feedback(self, deadline):
        """Recover one incomplete group before the existing stale watchdog expires.

        Linux/USB scheduling can use the 40 ms group budget before later IDs
        are even queried. Retry the entire group once with more scheduling
        headroom, without advancing the trajectory or refreshing partial data.
        Real silence still exhausts the original 250 ms feedback watchdog.
        """
        deadline = min(deadline, self.measured+self.stale_limit)
        if self._read_positions(deadline):
            return True
        if not self.planned_vertical:
            return False
        now = time.monotonic()
        recovery_deadline = min(now+self.feedback_recovery_budget, self.measured+self.stale_limit)
        if recovery_deadline <= now:
            return False
        self.timing['feedback_recovery_attempts'] += 1
        self.audit('FEEDBACK_RETRY',dict(budget_s=recovery_deadline-now,
            feedback_age_s=now-self.measured, action='read_only_retry_before_next_target'))
        if not self._read_positions(recovery_deadline):
            return False
        self.timing['feedback_recovery_successes'] += 1
        self.audit('FEEDBACK_RECOVERED',dict(measured_at_s=self.measured,
            elapsed_s=time.monotonic()-now, complete_ids=list(self.feedback), fresh=True))
        return True

    def _health(self, deadline):
        for joint in self.machine['joints']:
            sid = joint['id']
            if time.monotonic() >= deadline: return
            try:
                if exchange_deadline(self.port, sid, 'torque', deadline) != 1:
                    self.audit('TORQUE_OFF', dict(id=sid))
                    if self.planned_vertical:
                        raise RuntimeError('ID %s 扭矩关闭，停止预规划轨迹' % sid)
                    self.quality_warning = True
            except (ProbeError, OSError) as exc:
                self.audit('HEALTH_READ_MISSED', dict(id=sid, error=str(exc)[:100]))
                return
        index = getattr(self, 'health_index', 0)
        sid = self.machine['joints'][index % 5]['id']
        self.health_index = index+1
        if time.monotonic() < deadline:
            try:
                health = exchange_deadline(self.port, sid, 'health', deadline)
                self.audit('SERVO_HEALTH', dict(id=sid, measured_at_s=time.monotonic(), **health))
                threshold = self.cfg.get('maximum_temperature_c')
                if threshold is not None and health['temperature_c'] > float(threshold):
                    self.audit('TEMPERATURE_OFF', dict(id=sid, **health))
                    self.quality_warning = True
            except (ProbeError, OSError) as exc:
                self.audit('HEALTH_READ_MISSED', dict(id=sid, error=str(exc)[:100]))

    def _configure(self, current):
        if self.executor.cancelled(): raise RuntimeError('STOPPED')
        try:
            snapshot = servo_snapshot(self.port, list(current))
        except (ProbeError, OSError) as exc:
            self.audit('SERVO_SNAPSHOT_MISSED', dict(error=str(exc)[:120]))
            snapshot = {}
        self.audit('SERVO_PARAMETER_SNAPSHOT', dict(parameters=snapshot,
            status=self.settings.status, profile_hash=self.settings.hash,
            scope='readback; unverified raw units are not converted'))
        if self.settings.verified_registers is not None and set(snapshot) != set(current):
            raise ValueError('舵机单位寄存器未完整回读，不能应用已验证参数')
        for sid, row in snapshot.items():
            if row['model'] != 777 or row['mode'] != 0:
                self.audit('SERVO_MODEL_OFF', dict(id=sid, model=row['model'], mode=row['mode']))
                self.quality_warning = True
                if self.planned_vertical:
                    raise ValueError('ID %s 型号/位置模式未通过回读' % sid)
            if self.settings.verified_registers is not None:
                signature=self.settings.verified_registers
                expected=signature.get(str(sid),signature.get(sid,signature))
                fields=self.settings.signature_fields
                if not isinstance(expected,dict) or any(field not in expected or expected[field]!=row[field] for field in fields):
                    raise ValueError('ID %s 固件或单位寄存器已变化，需要重新确认舵机单位' % sid)
            if self.settings.accelerations is not None:
                maximum = row['maximum_acceleration']
                if type(maximum) is not int or self.settings.accelerations[sid] > maximum:
                    raise ValueError('加速度配置超过舵机最大加速度或读取未确认')
        if self.settings.accelerations is not None or self.settings.documented_stream:
            # Apply a verified profile while holding the measured position,
            # then read it back before advancing the reference trajectory.
            self.settings.write(self.port, current)
            for sid in current:
                expected_acceleration = (self.settings.accelerations[sid] if self.settings.accelerations else 0)
                if (exchange_deadline(self.port,sid,'acceleration',time.monotonic()+.04) != expected_acceleration
                        or exchange_deadline(self.port,sid,'goal_speed',time.monotonic()+.04) != self.settings.speeds[sid]):
                    raise RuntimeError('舵机速度/加速度参数回读不一致')
        if self.executor.cancelled(): raise RuntimeError('STOPPED')
        self.parameters_ready = True

    def _hold(self):
        # Prefer a fresh measured hold, but never retrace an old measured pose
        # after feedback fails. Reissuing the last goal keeps support torque.
        try:
            try: self._read_positions(time.monotonic()+self.feedback_budget)
            except Exception: pass
            counts = self.feedback if time.monotonic()-self.measured <= self.feedback_budget else self.last_counts
            if counts is not None:
                if self.parameters_ready:
                    self.settings.write(self.port, counts)
                else:
                    # A failed unit/signature check must never apply the
                    # unverified acceleration profile through the fault hold.
                    sync(self.port,42,{sid:[c&255,c>>8,0,0,100,0] for sid,c in counts.items()})
        except Exception:
            pass

    def _write_target(self, values):
        retry_at = 0.
        started = time.monotonic()
        while True:
            if self.executor.cancelled(): raise RuntimeError('STOPPED')
            try:
                if getattr(self.settings, 'frame_speed_enabled', False):
                    self.settings.write(self.port, values, self.last_counts, self.period)
                else:
                    # Preserve the static two-argument writer contract used by
                    # existing executors and virtual unequal-rate motor models.
                    self.settings.write(self.port, values)
                return
            except (ProbeError, OSError) as exc:
                self.timing['write_failures'] += 1
                if self.planned_vertical and time.monotonic()-started >= self.write_failure_timeout:
                    raise RuntimeError('运动指令持续写入失败，已停止保持') from exc
                self.quality_warning = True
                if time.monotonic() >= retry_at:
                    self.audit('WRITE_RETRY', dict(target=values, error=str(exc)[:120]))
                    retry_at = time.monotonic()+1.
                try: self.port.reset_output_buffer()
                except (AttributeError, OSError): pass
                self._wait(time.monotonic()+self.period)

    def _lift_completion(self, stamp):
        """Finish an actual upward move before permitting the next XY move."""
        if not self.release.enabled and not self.planned_vertical:return False,None
        current=self.curve.sample(stamp)
        after=self.curve.sample(min(self.curve.duration,stamp+self.period*.01))
        boundary=(stamp>=self.curve.duration-1e-9 or
                  (current['phase'],current['stroke'])!=(after['phase'],after['stroke']))
        if current['phase']!='LIFT' or not boundary:return False,None
        if self.planned_vertical:
            key = (current['stroke'], float(stamp))
            if self.last_checked_lift == key:
                return False, None
            # The final setpoint must get at least one command interval before
            # observing its effect. Reading immediately after transmission can
            # sample the servo's preceding control tick (20 ms on this board).
            if self.last_sent is not None:
                self._wait(self.last_sent+self.period)
            try:
                if not self._read_feedback(time.monotonic()+self.feedback_budget):
                    if time.monotonic()-self.measured > self.stale_limit:
                        raise RuntimeError('位置反馈已失效，停止预规划轨迹并保持')
                    detail = self.planned_lift.unconfirmed(current, 'endpoint_feedback_missing',
                        '抬笔结束位置反馈中断，已停止保持')
                else:
                    detail = self.planned_lift.finish(self.feedback, self.measured, current)
            except Exception as exc:
                self.audit('PEN_LIFT_FAILED', getattr(exc, 'lift_completion', dict(error=str(exc))))
                raise
            self.last_checked_lift = key
            if not detail['confirmed']:
                self.quality_warning = True
            self.audit('PLANNED_LIFT_ENDPOINT' if detail['confirmed'] else 'PEN_LIFT_WARNING', detail)
            return False, detail
        fresh=time.monotonic()-self.measured<=self.feedback_period+.025
        if current['stroke']>=0:
            detail=self.release.clearance_detail(self.feedback,fresh)
            clear=self.release.is_clear(self.feedback,fresh)
        else:
            height=None
            if fresh and self.feedback is not None:
                tip=self.curve.model.pose(angles_from_counts(self.machine,self.feedback))[:3,3]
                height=float((tip-self.release.frame['origin'])@self.release.n)
            clear=height is not None and height>=self.release.lift-.0005
            detail=dict(confirmed=clear,fresh=fresh,measured_height_m=height,
                        required_height_m=self.release.lift-.0005)
        return not clear,detail

    def _check_lift_wait(self, stroke, detail, now):
        fault = self.lift_guard.observe(stroke, detail, self.measured, now)
        if fault is None: return
        fault.update(target_counts=dict(self.last_counts or {}),
                     feedback_counts=dict(self.feedback or {}))
        self.audit('PEN_LIFT_FAILED', fault)
        labels = dict(feedback_timeout='抬笔位置反馈中断')
        height = (detail or {}).get('actual_plane_height_m', (detail or {}).get('measured_height_m'))
        required = (detail or {}).get('required_plane_height_m', (detail or {}).get('required_height_m'))
        extra = ('；模型离纸高度%.1f/%.1f mm' % (height*1000, required*1000)
                 if height is not None and required is not None else '')
        location = '第%d笔' % (stroke+1) if stroke is not None and stroke >= 0 else '起始抬笔'
        message = ('%s%s%s，已停止并保持当前位置。请先检查肩肘和线束，勿带电掰动关节。'
                   % (location, labels[fault['reason']], extra))
        error = RuntimeError(message)
        error.lift_completion = fault
        raise error

    def run(self, current, settle_counts=8):
        from tracking import TrackingMonitor
        curve = self.curve; progress = Progress(curve)
        monitor = TrackingMonitor(self.machine)
        self.last_counts = dict(current); self.feedback = dict(current)
        self.last_nominal_counts = dict(current)
        trace = []
        first_draw_recorded = False
        previous_timeout = getattr(self.port, 'write_timeout', None)
        settle_timeout = self.executor.settle_timeout_s
        self.port.write_timeout = max(.05, self.period)
        try:
            self._configure(current)
            started = time.monotonic(); self.measured = started
            feedback_due = started+self.feedback_period; health_due = started+self.health_period
            due = started+self.period
            while True:
                lift_wait,lift_completion=self._lift_completion(progress.position)
                if progress.position>=curve.duration-1e-9 and not lift_wait:
                    if self.lift_wait_key is not None:
                        self.audit('PEN_LIFT_CONFIRMED',dict(stroke=self.lift_wait_key,**(lift_completion or {})))
                        self.lift_wait_key=None
                    self.lift_guard.reset()
                    break
                self._wait(due)
                begin = time.monotonic(); late = max(0., begin-due)
                if late > self.warn_late:
                    self.quality_warning = True; self.timing['missed_deadlines'] += 1
                refine = lift_wait or self.pen_phases.refine(progress.position, self.last_nominal_counts,
                    self.feedback, time.monotonic()-self.measured <= self.feedback_period+.01, self.period,
                    skip_lift=self.release.enabled)
                if lift_wait:
                    self.lift_wait_frames+=1
                    key=(self.last_command or {}).get('stroke')
                    if key!=self.lift_wait_key:
                        self.lift_wait_key=key
                        self.audit('PEN_LIFT_COMPLETING',dict(stroke=key,**(lift_completion or {})))
                    self._check_lift_wait(key, lift_completion, begin)
                elif self.lift_wait_key is not None:
                    self.audit('PEN_LIFT_CONFIRMED',dict(stroke=self.lift_wait_key,**(lift_completion or {})))
                    self.lift_wait_key=None
                    self.lift_guard.reset()
                if not refine:
                    progress.advance(self.period)
                    self.timing['trajectory_frames_sent'] += 1
                else:
                    self.timing['refinement_frames_sent'] += 1
                command = curve.sample(progress.position)
                if lift_wait:command['endpoint_pause']=True
                nominal = counts_from_angles(self.machine, command['q_rad'])
                if (command['phase']=='LIFT' and (command['stroke']>=0 or self.planned_vertical)
                        and (self.last_command is None or
                             (self.last_command['phase'],self.last_command['stroke'])!=('LIFT',command['stroke']))):
                    # Read at the release boundary, rather than anchoring to a
                    # DRAW sample that can be 100 ms old. This is a read, not a
                    # tolerance wait. V2 requires a complete fresh snapshot.
                    read = (self._read_feedback if self.planned_vertical else self._read_positions)(
                        time.monotonic()+self.feedback_budget)
                    if self.planned_vertical:
                        if not read:
                            if not self.planned_lift.warn_only:
                                raise RuntimeError('抬笔起点位置反馈中断，已停止保持')
                            self.planned_lift.anchor = None; self.quality_warning = True
                            self.audit('PEN_LIFT_START_WARNING',dict(stroke=command['stroke'],
                                fresh=False,action='continue_warning'))
                        else:
                            self.planned_lift.begin(self.feedback, self.measured, command['stroke'])
                released,entered,release_detail=self.release.target(command,self.feedback,
                    time.monotonic()-self.measured<=self.feedback_period+.03,self.controller.integral,
                    issued_counts=self.last_counts)
                if entered:self.controller.reset_transition()
                if released is not None:
                    values=released;correction={sid:values[sid]-nominal[sid] for sid in nominal}
                    self.release_control_active=True
                else:
                    if self.release_control_active:
                        self.controller.seed_support(self.last_nominal_counts,self.last_counts,begin)
                        self.release_control_active=False
                        self.audit('PEN_RELEASE_HANDOFF',dict(stroke=command['stroke'],phase=command['phase'],
                            support_counts=self.controller.integral.tolist()))
                    values, correction = self.controller.target(nominal, begin)
                normal_detail=None
                if released is None:
                    values,normal_detail=self.normal_control.target(command,values,self.feedback,
                        time.monotonic()-self.measured<=self.feedback_period+.025,begin)
                    correction={sid:values[sid]-nominal[sid] for sid in nominal}
                elif command['phase'] not in ('DRAW','LOWER'):
                    # Clear the preceding contact-height correction at lift.
                    # Its load support is already included in issued_counts.
                    _,normal_detail=self.normal_control.target(command,values,self.feedback,False,begin)
                feedforward_detail = None
                if self.feedforward:
                    values, feedforward_detail = self.feedforward.target(curve, command)
                    correction = {sid: values[sid]-nominal[sid] for sid in nominal}
                if self.planned_vertical and time.monotonic()-self.measured > self.stale_limit:
                    raise RuntimeError('位置反馈已失效，停止预规划轨迹并保持')
                write_begin = time.monotonic()
                self._write_target(values)
                finished = time.monotonic()
                if self.timing['frames_sent'] == 0:
                    self.audit('FIRST_COMMAND', dict(monotonic_s=finished))
                if command['phase'] == 'DRAW' and not first_draw_recorded:
                    first_draw_recorded = True
                    self.audit('FIRST_DRAW_COMMAND', dict(monotonic_s=finished))
                self.last_counts, self.last_command = values, command
                self.last_nominal_counts = nominal
                if finished-write_begin > self.warn_late:
                    self.quality_warning = True
                self.timing['frames_sent'] += 1
                if self.last_sent is not None: self.intervals.append(write_begin-self.last_sent)
                self.last_sent = write_begin
                self.timing['max_lateness_s'] = max(self.timing['max_lateness_s'], late)
                self.timing['schedule_stretch_s'] = max(0., finished-started-self.timing['frames_sent']*self.period)
                # Keep the configured command period between cycle starts; do not add every write/FK
                # duration to the trajectory. A delayed start is never caught up.
                reserve = .001 if self.planned_vertical else self.feedback_budget+.001
                pacing_start = write_begin if self.planned_vertical else begin
                due = max(due+self.period, pacing_start+self.period, finished+reserve)
                fresh = False; following = None; quality = None
                if finished >= feedback_due:
                    if self.planned_vertical:
                        # Usually fits inside this frame. USB jitter may stretch
                        # one cycle; never discard later joints solely to meet a
                        # command tick, and never catch up with a command burst.
                        self._wait(min(due-.001, finished+min(.002,self.period*.1)))
                        fresh = self._read_feedback(time.monotonic()+self.feedback_budget)
                    else:
                        self._wait(min(due-self.feedback_budget, finished+self.period*.35))
                        fresh = self._read_positions(min(due-.001, time.monotonic()+self.feedback_budget))
                    feedback_due += self.feedback_period
                    if feedback_due <= time.monotonic():
                        feedback_due = time.monotonic()+self.feedback_period
                    if fresh:
                        following = max(abs(self.feedback[sid]-nominal[sid]) for sid in nominal)
                        self.timing['max_following_error_counts'] = max(self.timing['max_following_error_counts'], following)
                        quality = monitor.observe_phase(self.feedback, command)
                        if released is None:self.controller.observe(nominal, self.feedback, self.measured)
                        if len(trace) < 10000:
                            trace.append(dict(nominal_time_s=progress.position, elapsed_s=self.measured-started,
                                phase=command['phase'], stroke=command['stroke'],
                                source_segment_id=command.get('source_segment_id'),
                                nominal_counts=nominal, issued_counts=values, feedback_counts=dict(self.feedback),
                                normal_feedback=normal_detail,measured_release=release_detail,
                                planned_feedforward=feedforward_detail,
                                lift_completion=lift_completion,
                                **quality))
                        if command['pen_down'] and quality and not quality['qualified']:
                            self.quality_warning = True
                            self.audit('TRACKING_OFF', dict(**quality, reference_time_s=progress.position,
                                measurement_at_s=self.measured, scope='FK from sequential encoder samples'))
                        # Encoder feedback corrects targets. It never changes
                        # drawing rate or aborts on following/contact error.
                if time.monotonic()-self.measured > self.stale_limit:
                    self.quality_warning = True
                    if self.planned_vertical:
                        raise RuntimeError('位置反馈已失效，停止预规划轨迹并保持')
                if time.monotonic() >= health_due and due-time.monotonic() > .002:
                    self._health(min(due-.001, time.monotonic()+self.feedback_budget))
                    health_due += self.health_period
                    if health_due <= time.monotonic():
                        health_due = time.monotonic()+self.health_period
                age = time.monotonic()-self.measured
                self.timing['max_feedback_age_s'] = max(self.timing['max_feedback_age_s'], age)
                self.audit('FRAME_SMOOTH', dict(sequence=self.timing['frames_sent'], target=values,
                    nominal_target=nominal, correction_counts=correction, phase_refinement=refine,
                    feedback=self.feedback, fresh=fresh, feedback_at_s=self.measured, measurement_times=self.measurements,
                    following_counts=following, quality=quality, nominal_time_s=progress.position,
                    progress_rate=progress.rate, progress_rate_first=progress.first, progress_rate_second=progress.second,
                    due_mono_s=begin-late, cycle_begin_mono_s=begin,
                    write_begin_mono_s=write_begin, write_end_mono_s=finished,
                    write_duration_s=finished-write_begin,
                    phase=command['phase'], stroke=command['stroke'], motion_block_id=command['motion_block_id'],
                    source_segment_id=command.get('source_segment_id'), lateness_s=late,
                    endpoint_pause=command.get('endpoint_pause',False),
                    measured_release=release_detail,
                    normal_feedback=normal_detail,lift_completion=lift_completion,
                    planned_feedforward=feedforward_detail, servo_frame_profile=getattr(self.settings, 'last_profile', None),
                    servo_parameter_status=self.settings.status, quality_warning=self.quality_warning))
            released_final=(self.release.enabled and self.last_command is not None and
                self.last_command['phase']=='LIFT')
            endpoint_confirmed = True
            if self.planned_vertical:
                # The document replaces posture/position settling loops with a
                # single endpoint observation. A final LIFT was checked above;
                # other endings still require fresh feedback, without chasing.
                if self.last_command is None or self.last_command['phase'] != 'LIFT':
                    if not self._read_feedback(time.monotonic()+self.feedback_budget):
                        if not self.planned_lift.warn_only or time.monotonic()-self.measured > self.stale_limit:
                            raise RuntimeError('运动终点位置反馈中断，已停止保持')
                        endpoint_confirmed = False; self.quality_warning = True
                        self.audit('MOTION_ENDPOINT_WARNING',dict(fresh=False,action='continue_warning'))
                elif self.planned_lift.endpoints:
                    endpoint_confirmed = self.planned_lift.endpoints[-1]['confirmed']
                released_final = True
            # The measured lift endpoint deliberately has different XY counts
            # from the old DRAW endpoint. Never undo it in nominal count settling.
            settled=released_final and endpoint_confirmed
            deadline = time.monotonic()+min(settle_timeout, 1.)
            while not released_final and time.monotonic() < deadline:
                if self.executor.cancelled(): raise RuntimeError('STOPPED')
                if self._read_positions(time.monotonic()+self.feedback_budget):
                    if all(abs(self.feedback[sid]-self.last_nominal_counts[sid]) <= settle_counts for sid in self.last_nominal_counts):
                        settled = True; break
                    self.controller.observe(self.last_nominal_counts, self.feedback, self.measured)
                    values, correction = self.controller.target(self.last_nominal_counts, time.monotonic())
                    self._write_target(values)
                    self.last_counts = values
                    self.timing['settle_frames_sent'] += 1
                    self.audit('ENDPOINT_REFINEMENT', dict(nominal_target=self.last_nominal_counts,
                        target=values, correction_counts=correction, feedback=dict(self.feedback)))
                self._wait(time.monotonic()+min(.05, self.period))
            if not settled:
                self.quality_warning = True
            interval = np.asarray(self.intervals)
            self.timing.update(elapsed_s=time.monotonic()-started, settled=settled,
                actual_interval_p50_s=float(np.percentile(interval, 50)) if len(interval) else None,
                actual_interval_p99_s=float(np.percentile(interval, 99)) if len(interval) else None,
                max_actual_interval_s=float(interval.max()) if len(interval) else None,
                max_interval_error_s=float(np.abs(interval-self.period).max()) if len(interval) else None,
                progress_changes=progress.changes, timing_scope='host write times; not servo receipt/physical vibration')
            outcome = dict(target_counts=self.last_nominal_counts, issued_target_counts=self.last_counts,
                final_counts=self.feedback if settled else None,
                frames=self.timing['frames_sent'],last_measured_counts=self.feedback,
                feedback_fresh=settled,feedback_age_s=max(0.,time.monotonic()-self.measured),execution_finished=True,
                timing=self.timing, task_complete=settled, quality_warning=self.quality_warning,
                tracking=monitor.summary(), motion_algorithm_version=VERSION,
                execution_policy=self.execution_policy, feedback_control=self.controller.summary(),
                quality_guard_policy=self.planned_lift.endpoint_policy if self.planned_lift else 'audit',
                pen_phase=self.pen_phases.summary(),
                measured_release=self.release.summary(),
                normal_feedback=self.normal_control.summary(),
                planned_feedforward=self.feedforward.summary() if self.feedforward else None,
                lift_completion=(self.planned_lift.summary() if self.planned_lift else
                    dict(wait_frames=self.lift_wait_frames,extra_time_s=self.lift_wait_frames*self.period,
                         **self.lift_guard.summary())),
                servo_parameter_status=self.settings.status, servo_profile_hash=self.settings.hash)
            outcome['tracking']['feedback_complete'] = not self.timing['feedback_failures']
            outcome['tracking']['tracking_qualified'] &= bool(settled and not self.quality_warning and not self.timing['feedback_failures'])
            self.audit('MOTION_SMOOTH_DONE', outcome)
            self.audit.close()
            outcome['audit_dropped'] = self.audit.dropped
            outcome['audit_error'] = str(self.audit.error) if self.audit.error else None
            # Workbench persists this separately; keep polling responses small.
            outcome['_tracking_trace'] = trace
            return outcome
        except Exception as exc:
            if getattr(exc, 'lift_completion', None) is not None:
                exc.tracking_trace = trace
            self._hold()
            try: self.audit.close()
            except Exception: pass
            raise
        finally:
            self.port.write_timeout = previous_timeout


def validate_plan(result, machine):
    return MotionCurve(result, machine)


def execute(executor, result, current, settle_counts=8):
    return SerialMotionScheduler(executor, MotionCurve(result, executor.machine)).run(current, settle_counts)


def joint_move(executor, current, end, minimum_duration=1., settle_counts=8, minimum_clearance_m=None, motion_mode='gentle'):
    """A single rest-to-rest move, using the same bounds and serial scheduler."""
    import planning
    from r1b.retiming import rest_move, normalize_motion_limits
    from r1b.continuous import evaluate
    from types import SimpleNamespace
    machine = executor.machine
    if set(end) != set(current) or len(end) != 5:
        raise ValueError('Incomplete joint move; gripper must remain separate')
    joints = {j['id']: j for j in machine['joints']}
    if any(type(v) is not int or not joints[sid]['min_count'] <= v <= joints[sid]['max_count'] for sid,v in end.items()):
        raise ValueError('Joint move exceeds count limits')
    cfg = planning.load('trajectory.json')
    cfg['command_period_s'] = .05
    cfg.update(machine.get('trajectory', {}))
    cfg = planning.motion_config(cfg, motion_mode)
    limits = normalize_motion_limits(cfg)
    q0,q1 = [np.asarray(angles_from_counts(machine, counts)) for counts in (current,end)]
    constrained = dict(cfg)
    for name, values in zip(('joint_max_velocity_rad_s','joint_max_acceleration_rad_s2','joint_max_jerk_rad_s3'), limits):
        constrained[name] = (values*.9).tolist()
    c, duration = rest_move(q0,q1,constrained)
    period = cfg['command_period_s']
    duration = math.ceil(max(duration,float(minimum_duration))/period)*period
    from r1b.retiming import quintic_full
    c = quintic_full(q0,q1,np.zeros(5),np.zeros(5),np.zeros(5),np.zeros(5),duration)
    model = planning.Model(machine['model'])
    if minimum_clearance_m is not None:
        u=np.linspace(0.,1.,101)[:,None]
        q,_,_=evaluate(c,u,duration)
        from drawing_geometry import paper_frame
        frame=paper_frame(machine['paper']);origin=frame['origin'];normal=frame['normal']
        clearance=(model.pose_many(q)[:,:3,3]-origin)@normal
        if not np.isfinite(clearance).all() or clearance.min()<float(minimum_clearance_m)-1e-6:
            executor.audit('HOME_PLANE_OFF', dict(minimum_clearance_m=float(clearance.min())))
    p0,p1 = [model.pose(q) for q in (q0,q1)]
    row = dict(coeffs=c.tolist(),start_time_s=0.,duration_s=duration,motion_block_id=0,phase='MOVE',stroke=-1,
        source_segment_id=None,segment_start_m=p0[:3,3].tolist(),segment_end_m=p1[:3,3].tolist(),
        axis_start=(p0[:3,:3]@model.tool_axis).tolist(),axis_end=(p1[:3,:3]@model.tool_axis).tolist(),
        hard_stop_end=True,stop_reason='joint_move_endpoint')
    commands=[]
    for k in range(1,round(duration/period)+1):
        q,v,a = evaluate(c,k*period/duration,duration)
        counts_from_angles(machine,q)
        commands.append(dict(t_s=k*period,q_rad=q.tolist(),phase='MOVE',stroke=-1,pen_down=False))
    contract = dict(schema=SCHEMA,motion_algorithm_version=VERSION,command_period_s=period,
        servo_profile=dict(machine.get('execution',{}).get('servo_profile') or {}))
    for name,values in zip(('joint_max_velocity_rad_s','joint_max_acceleration_rad_s2','joint_max_jerk_rad_s3'),limits):
        contract[name]=values.tolist()
    result=SimpleNamespace(status='OK',commands=commands,metrics={'motion_algorithm_version':VERSION},
                           trajectory_segments=[row],execution_contract=contract)
    return execute(executor,result,current,settle_counts)
