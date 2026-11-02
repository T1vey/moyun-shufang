"""Bounded, coupled model-height correction. No serial I/O or error aborts.

This supplements the existing joint controller and preserves its learned load
bias. Encoder FK is the observation: paper contact and force are not measured.
"""
import math
import numpy as np
from drawing_geometry import paper_frame
from motion import angles_from_counts

VERSION = 'normal-feedback-v1'


class NormalFeedbackController:
    def __init__(self, machine, model, period, config=None):
        self.machine, self.model, self.period = machine, model, float(period)
        cfg = dict(config or {})
        self.enabled = cfg.get('enabled', True) is not False
        self.normal = paper_frame(machine['paper'])['normal']
        self.joints = machine['joints']
        self.ids = [j['id'] for j in self.joints]
        self.gain = float(cfg.get('kp', .6))
        self.deadband = float(cfg.get('deadband_m', .00015))
        self.cap = float(cfg.get('max_offset_m', .004))
        self.slew = float(cfg.get('max_offset_rate_m_s', .020))
        values = [self.period, self.gain, self.deadband, self.cap, self.slew]
        if (not all(math.isfinite(v) for v in values) or self.period <= 0
                or not 0 <= self.gain <= 2 or not 0 <= self.deadband <= .002
                or not 0 <= self.cap <= .01 or not 0 < self.slew <= .1):
            raise ValueError('Invalid normal feedback configuration')
        joint_cfg = machine.get('execution', {}).get('feedback_control', {})
        self.count_cap = np.asarray(joint_cfg.get('max_correction_counts', 32.), dtype=float)
        if self.count_cap.ndim == 0:
            self.count_cap = np.full(len(self.ids), float(self.count_cap))
        if (self.count_cap.shape != (len(self.ids),) or not np.isfinite(self.count_cap).all()
                or np.any(self.count_cap < 0) or np.any(self.count_cap > 96)):
            raise ValueError('Invalid feedback correction count cap')
        self.offset = 0.
        self.last_time = None
        self.samples = self.fresh_samples = self.stale_samples = 0
        self.saturated_samples = self.fallback_samples = 0
        self.maximum_error = self.maximum_offset = 0.
        self.minimum_signed = self.maximum_signed = None
        self.maximum_tangent = self.maximum_axis = 0.

    def _detail(self, **values):
        detail = dict(version=VERSION, enabled=self.enabled,
            extra_normal_offset_m=float(self.offset),
            scope='encoder FK model height only; no physical contact or pressure sensor')
        detail.update(values)
        return detail

    def target(self, command, base_counts, measured, fresh, now):
        """Return an additional vertical goal while retaining joint load support.

        The correction preserves the base goal's tangential tip position and
        pen axis. A single scale bounds the coupled correction at count/model
        limits, avoiding five unrelated clamps that would distort its direction.
        Missing feedback decays this extra correction and drawing continues.
        """
        base = {sid: int(base_counts[sid]) for sid in self.ids}
        if not self.enabled or command.get('phase') not in ('DRAW', 'LOWER'):
            self.offset = 0.
            self.last_time = None
            return base, self._detail(active=False)
        self.samples += 1
        dt = self.period
        if self.last_time is not None and math.isfinite(float(now)):
            dt = min(self.period, max(0., float(now)-self.last_time))
        self.last_time = float(now)
        signed = None
        requested = 0.
        saturated = False
        try:
            if fresh and measured is not None:
                actual = self.model.pose(angles_from_counts(self.machine, measured))[:3, 3]
                reference = np.asarray(command['tip_reference_m'], dtype=float)
                if reference.shape != (3,) or not np.isfinite(reference).all():
                    raise ValueError('Invalid normal feedback reference')
                signed = float((actual-reference) @ self.normal)
                error = -signed
                requested = self.gain*math.copysign(max(0., abs(error)-self.deadband), error)
                if abs(requested) > self.cap:
                    saturated = True
                requested = float(np.clip(requested, -self.cap, self.cap))
                self.fresh_samples += 1
                self.maximum_error = max(self.maximum_error, abs(signed))
                self.minimum_signed = signed if self.minimum_signed is None else min(self.minimum_signed, signed)
                self.maximum_signed = signed if self.maximum_signed is None else max(self.maximum_signed, signed)
            else:
                self.stale_samples += 1
        except (ValueError, KeyError, TypeError, np.linalg.LinAlgError):
            # An incomplete reading is treated exactly like a stale sample.
            self.stale_samples += 1
            requested = 0.
        self.offset += float(np.clip(requested-self.offset, -self.slew*dt, self.slew*dt))
        self.offset = float(np.clip(self.offset, -self.cap, self.cap))
        self.maximum_offset = max(self.maximum_offset, abs(self.offset))
        if abs(self.offset) < 1e-12:
            self.offset = 0.
            self.saturated_samples += int(saturated)
            return base, self._detail(active=True, signed_normal_error_m=signed, coupling_scale=1.)
        try:
            q0 = np.asarray(angles_from_counts(self.machine, base), dtype=float)
            pose = self.model.pose(q0)
            position = pose[:3, 3] + self.normal*self.offset
            axis = pose[:3, :3] @ self.model.tool_axis
            q = q0.copy()
            # Full position and pen-axis rows jointly impose zero tangent and
            # zero axis change. Orientation rows are converted to metre scale.
            for _ in range(3):
                error, jacobian, pe, tilt = self.model.task(q, position, axis)
                if pe < .00001 and tilt < .0001:
                    break
                error = error.copy(); jacobian = jacobian.copy()
                error[3:] *= .04; jacobian[3:] *= .04
                step = np.linalg.solve(jacobian.T @ jacobian + np.eye(5)*1e-8,
                                       jacobian.T @ error)
                step *= min(1., .05/max(float(np.max(abs(step))), 1e-12))
                q += step
            if not np.isfinite(q).all():
                raise ValueError('Nonfinite coupled correction')
            nominal_q = np.asarray(command['q_rad'], dtype=float)
            if nominal_q.shape != (5,) or not np.isfinite(nominal_q).all():
                raise ValueError('Invalid normal feedback nominal')
            zeros = np.asarray([j['zero_count'] for j in self.joints])
            directions = np.asarray([j['direction'] for j in self.joints])
            base_vector = np.asarray([base[sid] for sid in self.ids], dtype=float)
            nominal = np.rint(zeros+directions*nominal_q*4096/(2*math.pi))
            delta = directions*(q-q0)*4096/(2*math.pi)
            scale = 1.
            for i, joint in enumerate(self.joints):
                model_counts = zeros[i]+directions[i]*self.model.limits[i]*4096/(2*math.pi)
                low = max(joint['min_count'], math.ceil(nominal[i]-self.count_cap[i]), math.ceil(min(model_counts)))
                high = min(joint['max_count'], math.floor(nominal[i]+self.count_cap[i]), math.floor(max(model_counts)))
                if low > high or base_vector[i] < low or base_vector[i] > high:
                    # The owning joint controller already bounds its base.
                    # Do not change its goal if no extra feasible interval exists.
                    scale = 0.
                elif delta[i] > 0:
                    scale = min(scale, (high-base_vector[i])/delta[i])
                elif delta[i] < 0:
                    scale = min(scale, (low-base_vector[i])/delta[i])
            scale = float(np.clip(scale, 0., 1.))
            if scale < 1.-1e-9:
                saturated = True
            goals = {sid: int(round(value)) for sid, value in zip(self.ids, base_vector+scale*delta)}
            corrected = self.model.pose(angles_from_counts(self.machine, goals))
            displacement = corrected[:3, 3]-pose[:3, 3]
            normal_displacement = float(displacement @ self.normal)
            tangent = float(np.linalg.norm(displacement-self.normal*normal_displacement))
            corrected_axis = corrected[:3, :3] @ self.model.tool_axis
            angle = float(np.arctan2(np.linalg.norm(np.cross(axis, corrected_axis)), axis @ corrected_axis))
            self.maximum_tangent = max(self.maximum_tangent, tangent)
            self.maximum_axis = max(self.maximum_axis, angle)
            self.saturated_samples += int(saturated)
            return goals, self._detail(active=True, signed_normal_error_m=signed,
                applied_normal_offset_m=normal_displacement, tangent_side_effect_m=tangent,
                axis_side_effect_rad=angle, coupling_scale=scale)
        except (ValueError, KeyError, TypeError, np.linalg.LinAlgError, OverflowError):
            self.fallback_samples += 1
            self.saturated_samples += int(saturated)
            return base, self._detail(active=True, signed_normal_error_m=signed, fallback=True)

    def summary(self):
        return dict(version=VERSION, enabled=self.enabled, samples=self.samples,
            fresh_samples=self.fresh_samples, stale_samples=self.stale_samples,
            saturated_samples=self.saturated_samples, fallback_samples=self.fallback_samples,
            max_normal_error_m=self.maximum_error,
            min_signed_normal_error_m=self.minimum_signed,
            max_signed_normal_error_m=self.maximum_signed,
            max_extra_normal_offset_m=self.maximum_offset,
            max_tangent_side_effect_m=self.maximum_tangent,
            max_axis_side_effect_rad=self.maximum_axis,
            stale_policy='slew extra height correction to zero; retain joint controller goal',
            following_error_policy='bounded correction; never abort',
            scope='encoder FK model height only; no physical contact or pressure sensor')
