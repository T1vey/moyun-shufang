"""Calibrated feedforward for planned_vertical_v2. No motor I/O.

The document's load and delay compensation require measured inputs. Nominal
examples are never treated as calibration. All compensated commands are checked
against both model angles and encoder limits before they can reach the bus.
"""
import math
import numpy as np
from motion import angles_from_counts, counts_from_angles


class PlannedFeedforward:
    def __init__(self, machine, model):
        self.machine, self.model = machine, model
        self.ids = [j['id'] for j in machine['joints']]
        cfg = machine.get('execution', {})
        self.samples = []
        self.delays = np.zeros(5)
        bias = cfg.get('load_bias_counts') or {}
        delay = cfg.get('joint_delay_s') or {}
        if not isinstance(bias, dict) or not isinstance(delay, dict):
            raise ValueError('负载/滞后补偿必须提供带 calibrated 状态的实测配置')
        self.bias_enabled = bias.get('enabled', False) is True
        self.delay_enabled = delay.get('enabled', False) is True
        if self.bias_enabled:
            self._require_calibration(bias, '负载')
            samples = bias.get('samples')
            if not isinstance(samples, list) or len(samples) < 5:
                raise ValueError('负载补偿需要中心和四角至少五组实测数据')
            for sample in samples:
                point = np.asarray(sample.get('tip_m'), dtype=float)
                if point.shape != (3,) or not np.isfinite(point).all():
                    raise ValueError('负载补偿采样点必须是有限的 tip_m 三维坐标')
                values = self._vector(sample.get('counts'), '负载补偿计数', -32., 32.)
                self.samples.append((point, values))
            points = np.asarray([p[:2] for p, _ in self.samples])
            if len(np.unique(points, axis=0)) != len(points) or np.linalg.matrix_rank(points-points.mean(axis=0)) < 2:
                raise ValueError('负载补偿采样点需要覆盖二维画面，不能重复或共线')
        if self.delay_enabled:
            self._require_calibration(delay, '滞后')
            self.delays = self._vector(delay.get('seconds'), '关节滞后秒数', 0., .2)

    @staticmethod
    def _require_calibration(cfg, label):
        if cfg.get('calibrated') is not True or not str(cfg.get('measurement_id', '')).strip():
            raise ValueError('%s补偿尚未实测标定，不能启用' % label)

    def _vector(self, values, label, lo, hi):
        if not isinstance(values, dict) or set(str(k) for k in values) != set(str(sid) for sid in self.ids):
            raise ValueError('%s必须包含全部五个关节 ID' % label)
        result = np.asarray([values.get(str(sid), values.get(sid)) for sid in self.ids], dtype=float)
        if result.shape != (5,) or not np.isfinite(result).all() or np.any(result < lo) or np.any(result > hi):
            raise ValueError('%s超出允许范围' % label)
        return result

    def load_bias(self, tip):
        if not self.bias_enabled:
            return np.zeros(5)
        point = np.asarray(tip, dtype=float)
        if point.shape != (3,) or not np.isfinite(point).all():
            raise ValueError('负载补偿目标位置无效')
        distance2 = np.asarray([np.sum((p[:2]-point[:2])**2) for p, _ in self.samples])
        values = np.asarray([value for _, value in self.samples])
        nearest = int(np.argmin(distance2))
        if distance2[nearest] < 1e-16:
            return values[nearest].copy()
        weights = 1./distance2
        return (weights[:, None]*values).sum(axis=0)/weights.sum()

    def target(self, curve, command):
        q = np.asarray(command['q_rad'], dtype=float).copy()
        stamp = float(command['t_s'])
        # Do not anticipate the next phase/stroke through a hard stop. Per-joint
        # lead applies only inside the current planned movement block.
        if self.delay_enabled:
            stop_index = int(np.searchsorted(curve.stops, stamp-1e-9, side='left'))
            stop = curve.stops[min(stop_index, len(curve.stops)-1)]
            for i, delay in enumerate(self.delays):
                if delay:
                    q[i] = curve.sample(min(stamp+delay, stop))['q_rad'][i]
        if not self.model.legal(q):
            raise ValueError('滞后补偿超出关节角限位')
        base = counts_from_angles(self.machine, q)
        bias = self.load_bias(command['tip_reference_m'])
        counts = {sid: int(round(base[sid]+bias[i])) for i, sid in enumerate(self.ids)}
        for joint in self.machine['joints']:
            if not joint['min_count'] <= counts[joint['id']] <= joint['max_count']:
                raise ValueError('ID %s 负载补偿超出计数限位' % joint['id'])
        if not self.model.legal(angles_from_counts(self.machine, counts)):
            raise ValueError('负载补偿或量化超出关节角限位')
        return counts, dict(load_bias_counts=dict(zip(self.ids, bias.tolist())),
                            joint_delay_s=dict(zip(self.ids, self.delays.tolist())))

    def validate_curve(self, curve):
        """Preflight every actual fixed-grid target before opening a port."""
        if not self.bias_enabled and not self.delay_enabled:
            return
        for k in range(1, int(round(curve.duration/curve.period))+1):
            self.target(curve, curve.sample(k*curve.period))

    def summary(self):
        return dict(load_bias_enabled=self.bias_enabled, load_bias_samples=len(self.samples),
                    delay_enabled=self.delay_enabled, joint_delay_s=self.delays.tolist(),
                    scope='measured feedforward; no inferred calibration or physical accuracy claim')


class PlannedLiftMonitor:
    """One endpoint observation per lift, without posture convergence waits."""
    def __init__(self, machine, model):
        self.machine, self.model = machine, model
        self.anchor = None
        self.endpoints = []
        self.endpoint_policy = machine.get('execution', {}).get('lift_endpoint_policy', 'warn_continue')
        if self.endpoint_policy not in ('stop', 'warn_continue'):
            raise ValueError('Invalid lift endpoint policy')
        self.warn_only = self.endpoint_policy == 'warn_continue'

    def unconfirmed(self, command, reason, message):
        detail = dict(policy='planned_vertical_v2', stroke=command['stroke'],
                      confirmed=False, fresh=False, actual_rise_m=None, required_rise_m=.002,
                      reason=reason, action='continue_warning' if self.warn_only else 'stop',
                      scope='No complete endpoint comparison; physical lift is unconfirmed')
        self.endpoints.append(detail); self.anchor = None
        if not self.warn_only:
            error = RuntimeError(message); error.lift_completion = detail
            raise error
        return detail

    def begin(self, counts, sample_time, stroke):
        pose = self.model.pose(angles_from_counts(self.machine, counts))
        self.anchor = dict(tip=pose[:3, 3].copy(), sample_time=float(sample_time), stroke=stroke,
                           counts=dict(counts))

    def finish(self, counts, sample_time, command):
        if self.anchor is None or self.anchor['stroke'] != command['stroke']:
            return self.unconfirmed(command, 'start_feedback_missing', '竖直抬笔缺少起点反馈')
        if not math.isfinite(sample_time) or sample_time <= self.anchor['sample_time']:
            return self.unconfirmed(command, 'endpoint_feedback_not_new', '竖直抬笔结束反馈不是新的完整采样')
        pose = self.model.pose(angles_from_counts(self.machine, counts))
        axis = pose[:3, :3] @ self.model.tool_axis
        delta = pose[:3, 3]-self.anchor['tip']
        axis_target = np.asarray(command['axis_target'], dtype=float)
        detail = dict(policy='planned_vertical_v2', stroke=command['stroke'],
                      actual_rise_m=float(delta[2]), required_rise_m=.002,
                      axis_error_rad=float(np.arccos(np.clip(axis @ axis_target, -1., 1.))),
                      xy_drift_m=float(np.linalg.norm(delta[:2])), measured_at_s=float(sample_time),
                      start_counts=self.anchor['counts'],end_counts=dict(counts),
                      start_tip_m=self.anchor['tip'].tolist(),end_tip_m=pose[:3,3].tolist(),
                      nominal_end_tip_m=command.get('tip_reference_m'),
                      fresh=True, confirmed=bool(delta[2] >= .002),
                      action='continue_warning' if self.warn_only and delta[2] < .002 else 'confirmed',
                      scope='FK of measured encoders; not physical contact or external angle measurement')
        self.endpoints.append(detail)
        self.anchor = None
        if not detail['confirmed'] and not self.warn_only:
            detail['action'] = 'stop'
            error = RuntimeError('抬笔结束净上升不足 2 mm（编码器模型回读 %.2f mm），已停止保持' % (delta[2]*1000))
            error.lift_completion = detail
            raise error
        return detail

    def summary(self):
        return dict(version='planned-lift-endpoint-v2', wait_frames=0, extra_time_s=0.,
                    minimum_rise_m=.002, endpoint_checks=len(self.endpoints), endpoints=list(self.endpoints),
                    unconfirmed_endpoints=sum(not row['confirmed'] for row in self.endpoints),
                    policy=self.endpoint_policy)
