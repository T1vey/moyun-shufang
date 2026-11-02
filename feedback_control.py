"""Bounded encoder correction, with no following-error abort or time slowdown.

Units here are encoder counts. No servo speed/acceleration unit is inferred and
no PID/EEPROM register is changed. The nominal drawing remains the reference.
"""
import math
import numpy as np

VERSION = 'joint-feedback-v1'
POLICY = 'speed_priority_feedback_corrected'


class JointFeedbackController:
    def __init__(self, machine, period, config=None):
        cfg = dict(config or {})
        self.enabled = cfg.get('enabled', True) is not False
        self.joints = machine['joints']
        self.ids = [j['id'] for j in self.joints]
        self.period = float(period)
        def vector(name, default, minimum, maximum):
            value = np.asarray(cfg.get(name, default), dtype=float)
            if value.ndim == 0:
                value = np.full(len(self.ids), float(value))
            if (value.shape != (len(self.ids),) or not np.isfinite(value).all()
                    or np.any(value < minimum) or np.any(value > maximum)):
                raise ValueError('Invalid feedback_control.' + name)
            return value
        self.kp = vector('kp', .5, 0., 2.)
        self.ki = vector('ki_per_s', .8, 0., 4.)
        self.cap = vector('max_correction_counts', 32., 0., 96.)
        self.slew = vector('max_correction_rate_counts_s', 40., 1., 200.)
        self.deadband = vector('deadband_counts', 1., 0., 8.)
        self.filter_s = float(cfg.get('filter_s', .15))
        self.stale_s = float(cfg.get('stale_s', .3))
        if (not math.isfinite(self.filter_s) or not 0. <= self.filter_s <= 2.
                or not math.isfinite(self.stale_s) or not .05 <= self.stale_s <= 2.):
            raise ValueError('Invalid feedback filter/stale time')
        self.integral = np.zeros(len(self.ids))
        self.filtered_error = np.zeros(len(self.ids))
        self.desired = np.zeros(len(self.ids))
        self.applied = np.zeros(len(self.ids))
        self.last_observation = None
        self.samples = 0
        self.saturated_samples = 0
        self.max_applied = np.zeros(len(self.ids))
        self.count_clips = 0

    def reset_transition(self):
        """Drop dynamic endpoint chasing, retain bounded slow load bias."""
        self.filtered_error.fill(0.)
        self.desired=self.integral.copy();self.applied=self.integral.copy();self.last_observation=None

    def seed_support(self, nominal, issued, now):
        """Continue the active release controller's bounded support on handoff.

        The old DRAW integrator includes motion lag and is no longer a useful
        baseline after an encoder-controlled lift. Seed from the most recently
        issued goal, then resume ordinary observations on the new reference.
        """
        if not self.enabled:return
        support=np.asarray([issued[sid]-nominal[sid] for sid in self.ids],dtype=float)
        support=np.clip(support,-self.cap,self.cap)
        self.filtered_error.fill(0.)
        self.integral=support.copy();self.applied=support.copy();self.desired=support.copy()
        self.last_observation=float(now)

    def observe(self, nominal, measured, now):
        """Observe error against the NOMINAL target, never the compensated goal.

        Only complete fresh readings update the integrator. Conditional
        integration prevents wind-up when a joint is stuck or correction caps.
        """
        if not self.enabled:
            return
        error = np.asarray([nominal[sid] - measured[sid] for sid in self.ids], dtype=float)
        if not np.isfinite(error).all():
            return
        raw_dt = self.period if self.last_observation is None else max(0., now-self.last_observation)
        dt = min(raw_dt, .2)
        if self.last_observation is not None and raw_dt > self.stale_s:
            # A reconnect must not integrate the unobserved interval.
            dt = 0.
        self.last_observation = float(now)
        alpha = 1. if self.filter_s == 0 else -math.expm1(-max(self.period, dt)/self.filter_s)
        error = np.sign(error)*np.maximum(0., np.abs(error)-self.deadband)
        self.filtered_error += alpha*(error-self.filtered_error)
        candidate = self.integral+self.ki*self.filtered_error*dt
        wanted = self.kp*self.filtered_error+candidate
        winding = (np.abs(wanted) > self.cap) & (self.filtered_error*wanted > 0)
        self.integral = np.clip(np.where(winding, self.integral, candidate), -self.cap, self.cap)
        wanted = self.kp*self.filtered_error+self.integral
        self.desired = np.clip(wanted, -self.cap, self.cap)
        self.samples += 1
        self.saturated_samples += int(np.any(np.abs(wanted) > self.cap))

    def target(self, nominal, now):
        fresh = self.last_observation is not None and now-self.last_observation <= self.stale_s
        desired = self.desired if self.enabled and fresh else np.zeros(len(self.ids))
        self.applied += np.clip(desired-self.applied, -self.slew*self.period, self.slew*self.period)
        self.applied = np.clip(self.applied, -self.cap, self.cap)
        result, correction = {}, {}
        for i, joint in enumerate(self.joints):
            sid = joint['id']
            wanted = int(round(nominal[sid]+self.applied[i]))
            value = max(joint['min_count'], min(joint['max_count'], wanted))
            if value != wanted:
                self.count_clips += 1
                # Back-calculate the integral at an actual position bound.
                self.integral[i] = np.clip(value-nominal[sid]-self.kp[i]*self.filtered_error[i], -self.cap[i], self.cap[i])
                self.applied[i] = value-nominal[sid]
            result[sid] = value
            correction[sid] = value-nominal[sid]
        self.max_applied = np.maximum(self.max_applied, np.abs(list(correction.values())))
        return result, correction

    def summary(self):
        return dict(version=VERSION, enabled=self.enabled, samples=self.samples,
            max_correction_counts={sid: float(v) for sid, v in zip(self.ids, self.max_applied)},
            configured_cap_counts=self.cap.tolist(), saturated_samples=self.saturated_samples,
            count_clips=self.count_clips, stale_policy='slew correction to zero; continue drawing',
            following_error_policy='bounded correction and diagnostics; never abort',
            scope='outer encoder loop; no physical pen contact sensor')


class PenPhaseCoordinator:
    """Finite refinement at LOWER/LIFT endpoints; never waits indefinitely.

    Drawing and travel are never held mid-stroke. An inaccurate or missing
    reading uses at most this small boundary budget, then drawing continues.
    """
    def __init__(self, curve, config=None):
        cfg = dict(config or {})
        self.enabled = cfg.get('enabled', True) is not False
        self.budget_s = float(cfg.get('max_refinement_s', .3))
        self.tolerance_counts = float(cfg.get('tolerance_counts', 8.))
        if (not math.isfinite(self.budget_s) or not 0. <= self.budget_s <= 1.
                or not math.isfinite(self.tolerance_counts) or not 0. <= self.tolerance_counts <= 100.):
            raise ValueError('Invalid pen_phase coordination config')
        self.boundaries = []
        for stamp in curve.stops:
            before = curve.sample(stamp)
            after = curve.sample(min(curve.duration, stamp+curve.period*.01))
            if before['phase'] in ('LOWER', 'LIFT') and (before['phase'], before['stroke']) != (after['phase'], after['stroke']):
                self.boundaries.append((float(stamp), before['phase'], before['stroke']))
        self.index = 0
        self.remaining = 0
        self.elapsed_s = 0.
        self.refinements = 0
        self.expired = 0
        self.phase = None

    def refine(self, stamp, nominal, measured, fresh, period, skip_lift=False):
        # Measured lift completion is owned by the scheduler. Consume those
        # boundaries without the old timed/count refinement fall-through.
        while (skip_lift and self.index < len(self.boundaries)
               and self.boundaries[self.index][1] == 'LIFT'
               and stamp >= self.boundaries[self.index][0]-1e-8):
            self.index += 1; self.phase = None; self.remaining = 0
        if not self.enabled or self.budget_s == 0:
            return False
        if self.index >= len(self.boundaries):
            return False
        boundary, phase, stroke = self.boundaries[self.index]
        if stamp < boundary-1e-8:
            return False
        good = fresh and measured is not None and all(abs(nominal[sid]-measured[sid]) <= self.tolerance_counts for sid in nominal)
        if self.phase is None:
            self.phase = (phase, stroke)
            self.remaining = int(math.floor(self.budget_s/period+1e-8))
        if good or self.remaining <= 0:
            if not good:
                self.expired += 1
            self.index += 1
            self.phase = None
            return False
        self.remaining -= 1
        self.refinements += 1
        self.elapsed_s += period
        return True

    def summary(self):
        return dict(enabled=self.enabled, boundary_count=len(self.boundaries),
            refinement_frames=self.refinements, extra_time_s=self.elapsed_s,
            max_per_boundary_s=self.budget_s, unconfirmed_boundaries=self.expired,
            expiry_policy='continue; never abort or require replan')
