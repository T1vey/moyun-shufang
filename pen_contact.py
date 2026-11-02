"""Encoder-feedback pen release; pure math, with no motor I/O or error aborts.

The controller freezes the measured model TCP and preserves the previous
issued joint support target. A bounded incremental Cartesian PI loop then
lifts it. Encoder/model clearance is not a physical pen contact sensor.
"""
import numpy as np
from motion import angles_from_counts
from drawing_geometry import paper_frame

VERSION = 'measured-release-vertical-v6'


class MeasuredPenRelease:
    def __init__(self, machine, model, period):
        self.machine, self.model, self.period = machine, model, float(period)
        self.frame = paper_frame(machine['paper']); self.plane_n = self.frame['normal']
        self.vertical = machine.get('execution', {}).get('vertical_pen_lift', False) is True
        self.n = np.array([0.,0.,1.]) if self.vertical else self.plane_n
        self.vertical_axis = np.array([0.,0.,-1.])
        self.normal_gain = float(self.n@self.plane_n)
        if self.vertical and self.normal_gain <= .1:
            raise ValueError('纸面方向无法沿世界竖直方向安全抬升，请检查纸面标定')
        self.enabled = (machine.get('execution', {}).get('pen_lift_policy') != 'planned_vertical_v2'
                        and (self.vertical or machine.get('execution', {}).get('measured_pen_release', True) is not False))
        self.lift = float(machine['trajectory'].get('lift_m', .02))
        self.lift_distance = self.lift/self.normal_gain
        self.radians_per_count = 2*np.pi/4096
        caps = machine.get('execution', {}).get('measured_pen_release_correction_cap_counts', 64)
        ids = [joint['id'] for joint in machine['joints']]
        self.elbow_first = not self.vertical and machine.get('execution', {}).get('elbow_first_lift', False) is True
        self.elbow_index = ids.index(3) if self.elbow_first else None
        self.wrist_index = ids.index(4) if self.elbow_first else None
        # Let the elbow clear the paper before the wrist changes pen angle.
        # This is measured TCP rise, not a timed delay or a servo angle.
        requested_lead = machine.get('execution', {}).get('elbow_first_clearance_m', self.lift)
        if isinstance(requested_lead, bool):
            raise ValueError('ID3 先抬高度必须为 0–50 mm 范围内的正数（单位：米）')
        try: requested_lead = float(requested_lead)
        except (TypeError, ValueError):
            raise ValueError('ID3 先抬高度必须为 0–50 mm 范围内的正数（单位：米）')
        if not np.isfinite(requested_lead) or not 0 < requested_lead <= .050:
            raise ValueError('ID3 先抬高度必须为 0–50 mm 范围内的正数（单位：米）')
        self.lead_clearance = min(requested_lead, self.lift)
        self.release_axis = None
        self.lead_finished = not self.elbow_first
        self.lead_hold_q = None; self.lead_start_elbow = None
        self.lead_releases = 0
        if isinstance(caps, dict):
            try:caps = {int(k):v for k,v in caps.items()}
            except (TypeError,ValueError):raise ValueError('抬笔补偿上限的关节 ID 无效')
            if not set(caps).issubset(ids):raise ValueError('抬笔补偿上限包含未知关节')
            caps = [caps.get(sid,64) for sid in ids]
        elif np.isscalar(caps):caps = [caps]*len(ids)
        self.cap_counts = np.asarray(caps,dtype=float)
        if (self.cap_counts.shape != (5,) or not np.isfinite(self.cap_counts).all()
                or np.any(self.cap_counts != np.floor(self.cap_counts))
                or np.any(self.cap_counts < 1) or np.any(self.cap_counts > 128)):
            raise ValueError('抬笔补偿上限需要五关节各 1–128 个整数计数')
        self.cap = self.cap_counts*self.radians_per_count
        self.step_cap = 12*self.radians_per_count
        self.kp, self.ki = .45, 3.
        self.key = None; self.anchor = None; self.start = None; self.offset = None
        self.join_start = None; self.last_q = None; self.last_reference_q = None
        self.command_q = None; self.last_goals = None; self.hold_axis = None
        self.previous_error_q = np.zeros(5); self.load_bias = np.zeros(5)
        self.cancelled_lateral_counts = np.zeros(5)
        self.actual_rise = 0.; self.maximum_error = 0.; self.max_xy_drift = 0.
        self.max_first_step = 0.; self.max_correction = 0.; self.saturated_frames = 0
        self.max_axis_error = 0.
        self.vertical_height = 0.
        self.releases = 0; self.fallbacks = 0; self.missing_feedback_holds = 0
        self.clearance_checks = 0; self.clearance_wait_frames = 0; self.clearance_confirmations = 0
        self.clear_confirmed = False

    def _q(self, counts):
        # Saved JSON and live serial dictionaries can have different key types.
        return np.asarray(angles_from_counts(self.machine, {int(k): v for k, v in counts.items()}))

    def _counts(self, q):
        q = np.clip(q, self.model.limits[:, 0], self.model.limits[:, 1])
        result = {}
        for joint, angle in zip(self.machine['joints'], q):
            count = int(round(joint['zero_count']+joint['direction']*angle/self.radians_per_count))
            result[joint['id']] = max(joint['min_count'], min(joint['max_count'], count))
        return result

    def _task_step(self, q, position, axis):
        error, jacobian, pe, tilt = self.model.task(q, position, axis)
        jacobian = jacobian.copy(); error = error.copy()
        jacobian[3:] *= .04; error[3:] *= .04
        step = np.linalg.solve(jacobian.T@jacobian+np.eye(5)*1e-7, jacobian.T@error)
        return step, pe, tilt

    def _reference(self, wanted, axis):
        q = self.last_reference_q.copy()
        for _ in range(6):
            step, pe, tilt = self._task_step(q, wanted, axis)
            if pe < .00003 and tilt < .002:
                break
            step *= min(1., .06/max(np.max(abs(step)), 1e-12))
            q = np.clip(q+step, self.model.limits[:, 0], self.model.limits[:, 1])
        return q

    def _holding(self, issued_counts, entered=False):
        """Missing feedback retains support; it never chases the old endpoint."""
        self.missing_feedback_holds += 1
        goals = self.last_goals or issued_counts
        if goals is None:
            return None, entered, None
        goals = {int(k): int(v) for k, v in goals.items()}
        return goals, entered, dict(version=VERSION, phase=self.key[0] if self.key else 'LIFT',
            feedback_hold=True, clearance_confirmed=False,
            release_stage='id3_lead' if self.elbow_first and not self.lead_finished else 'coordinated_lift',
            scope='hold issued support target pending encoder feedback')

    def _hold_entry(self, issued_counts, measured):
        # A missed boundary read must not let the wrist finish a pending DRAW
        # command. Freeze it at the latest known encoder position while waiting
        # for a fresh complete pose. Never infer clearance from this stale pose.
        if self.elbow_first and issued_counts is not None and measured is not None:
            try:
                known = self._counts(self._q(measured))
                goals = {int(k): int(v) for k, v in issued_counts.items()}
                goals[4] = known[4]
                self.last_goals = goals
            except (ValueError, KeyError, TypeError):
                pass
        return self._holding(issued_counts)

    def _elbow_lead_target(self, command, measured, entered):
        """Hold ID4 at the captured angle until ID3 actually lifts the tool.

        Only ID3 gets a new motion target during this phase. The shoulder
        retains its previous support command; wrist/pan/roll stop chasing
        their final DRAW targets. A joint-only lead traces a short arc.
        """
        actual_q = self._q(measured); actual = self.model.pose(actual_q)[:3,3]
        rise = float((actual-self.anchor)@self.n)
        plane_height = float((actual-self.frame['origin'])@self.n)
        elbow_moved = abs(actual_q[self.elbow_index]-self.lead_start_elbow)/self.radians_per_count
        self.actual_rise = max(self.actual_rise,rise)
        if rise>=self.lead_clearance and plane_height>=self.lead_clearance and elbow_moved>=1.-1e-8:
            self.lead_finished=True;self.lead_releases+=1
            # Start the coordinated lift from the measured state, retaining
            # the issued load support but discarding the scalar lead error.
            self.last_reference_q=actual_q.copy();self.previous_error_q.fill(0.)
            return None
        wanted_rise=max(min(self.lift,self.lead_clearance+.001),
            self.lead_clearance+.001-float((self.anchor-self.frame['origin'])@self.n))
        reference_q=actual_q.copy();index=self.elbow_index
        for _ in range(12):
            pose=self.model.pose(reference_q)[:3,3]
            error_m=wanted_rise-float((pose-self.anchor)@self.n)
            if abs(error_m)<.00003:break
            _,jacobian,_,_=self.model.task(reference_q,pose,self.hold_axis)
            derivative=float(self.n@jacobian[:3,index])
            if abs(derivative)<1e-5:
                return self._holding(self.last_goals or self._counts(self.command_q),entered)
            reference_q[index]=np.clip(reference_q[index]+np.clip(error_m/derivative,-.06,.06),
                self.model.limits[index,0],self.model.limits[index,1])
        error_q=reference_q[index]-actual_q[index]
        desired=(self.command_q[index]+reference_q[index]-self.last_reference_q[index]
            +self.kp*(error_q-self.previous_error_q[index])+self.ki*self.period*error_q)
        bounded=float(np.clip(desired,reference_q[index]-self.cap[index],reference_q[index]+self.cap[index]))
        saturated=abs(bounded-desired)>1e-10
        self.saturated_frames+=int(saturated)
        q=self.lead_hold_q.copy()
        q[index]=self.command_q[index]+np.clip(bounded-self.command_q[index],-self.step_cap,self.step_cap)
        q=np.clip(q,self.model.limits[:,0],self.model.limits[:,1])
        goals=self._counts(q);issued_q=self._q(goals)
        if entered:
            self.max_first_step=max(self.max_first_step,float(abs(issued_q[index]-self.command_q[index])/self.radians_per_count))
        self.command_q=q;self.last_reference_q=reference_q;self.previous_error_q.fill(0.)
        self.previous_error_q[index]=error_q;self.last_goals=goals
        drift=actual-self.anchor-self.n*rise
        self.max_xy_drift=max(self.max_xy_drift,float(np.linalg.norm(drift)))
        reference_counts=self._counts(reference_q)
        correction=[goals[j['id']]-reference_counts[j['id']] for j in self.machine['joints']]
        self.max_correction=max(self.max_correction,abs(correction[index]))
        return goals,entered,dict(version=VERSION,release_stage='id3_lead',phase='LIFT',feedback_hold=False,
            frozen_tip_m=self.anchor.tolist(),requested_tip_m=(self.anchor+self.n*wanted_rise).tolist(),
            reference_tip_m=self.model.pose(reference_q)[:3,3].tolist(),
            issued_tip_m=self.model.pose(issued_q)[:3,3].tolist(),
            id3_motion_counts=float(elbow_moved),id4_held_count=goals[4],
            lead_required_rise_m=self.lead_clearance,load_bias_counts=self.load_bias.tolist(),
            correction_counts=correction,correction_saturated_joint_ids=[3] if saturated else [],
            held_pen_axis=False,cancelled_lateral_counts=self.cancelled_lateral_counts.tolist(),
            clearance=self.clearance_detail(measured,True))

    def clearance_detail(self, measured, fresh):
        detail = dict(version=VERSION, fresh=bool(fresh), anchored=self.anchor is not None,
            clearance_confirmed=False, required_rise_m=max(0., self.lift_distance-.0005),
            required_plane_height_m=max(0., self.lift-.0005),
            release_stage='id3_lead' if self.elbow_first and not self.lead_finished else 'coordinated_lift',
            scope='encoder FK; no physical contact sensor')
        if not fresh or measured is None or self.anchor is None:
            return detail
        try:
            pose = self.model.pose(self._q(measured))
            actual = pose[:3, 3]
        except (ValueError, KeyError, TypeError):
            return detail
        rise = float((actual-self.anchor)@self.n)
        height = float((actual-self.frame['origin'])@self.plane_n)
        drift = actual-self.anchor-self.n*rise
        good = (rise >= detail['required_rise_m'] and height >= detail['required_plane_height_m']
                and (not self.elbow_first or self.lead_finished))
        if self.elbow_first or self.vertical:
            # A full elbow lift already satisfies the height gate. Do not end
            # LIFT after the first wrist command: let the coordinated stage
            # restore the pen axis and lateral anchor before travel resumes.
            axis = pose[:3,:3]@self.model.tool_axis
            tilt = (float(np.arctan2(np.linalg.norm(np.cross(axis,self.release_axis)),
                                    np.dot(axis,self.release_axis)))
                    if self.release_axis is not None else float('inf'))
            adjusted = tilt <= (.02 if self.vertical else .05) and float(np.linalg.norm(drift)) <= .002
            good = good and adjusted
            detail.update(wrist_adjustment_confirmed=bool(adjusted),axis_error_rad=tilt)
        detail.update(actual_rise_m=rise, actual_plane_height_m=height,
            actual_xy_drift_m=float(np.linalg.norm(drift)), clearance_confirmed=bool(good))
        return detail

    def is_clear(self, measured, fresh):
        detail = self.clearance_detail(measured, fresh)
        self.clearance_checks += 1
        if not detail['clearance_confirmed']:
            self.clearance_wait_frames += 1
            return False
        if not self.clear_confirmed:
            self.clearance_confirmations += 1
            self.clear_confirmed = True
        return True

    def target(self, command, measured, fresh, bias_counts=None, issued_counts=None):
        phase = command['phase']; key = (phase, command['stroke']); entered = False
        if not self.enabled:
            return None, False, None
        if phase == 'DRAW':
            self.anchor = self.offset = None; self.join_start = None; self.key = key
            self.last_goals = None; self.clear_confirmed = False
            self.lead_finished=not self.elbow_first;self.lead_hold_q=None;self.lead_start_elbow=None
            return None, False, None
        if phase == 'LIFT' and command['stroke'] >= 0:
            if self.anchor is None or self.key != key:
                self.key = key
                if not fresh or measured is None:
                    self.fallbacks += 1
                    return self._hold_entry(issued_counts, measured)
                try:
                    actual_q = self._q(measured)
                    pose = self.model.pose(actual_q)
                    self.anchor = pose[:3, 3].copy()
                    self.hold_axis = pose[:3, :3]@self.model.tool_axis
                    self.release_axis = (self.vertical_axis.copy() if self.vertical
                                         else np.asarray(command['axis_target'],dtype=float))
                    self.last_reference_q = actual_q.copy()
                    # The previous issued target already supports the loaded
                    # joints. Do not import DRAW's dynamic error integrator.
                    if issued_counts is not None:
                        self.command_q = self._q(issued_counts)
                        # Pan and wrist-roll carry no main gravity-support
                        # torque. Their pending DRAW goal is lateral endpoint
                        # chasing, which must be cancelled at stroke release.
                        self.cancelled_lateral_counts.fill(0.)
                        self.cancelled_lateral_counts[[0, 4]] = (actual_q-self.command_q)[[0, 4]]/self.radians_per_count
                        self.command_q[[0, 4]] = actual_q[[0, 4]]
                    else:
                        # Older callers can supply a measured pose and a known
                        # static support bias. Production uses issued_counts.
                        bias = np.zeros(5) if bias_counts is None else np.clip(np.asarray(bias_counts, dtype=float), -64., 64.)
                        support = self._counts(actual_q)
                        for joint, value in zip(self.machine['joints'], bias):
                            support[joint['id']] += int(round(value))
                        self.command_q = self._q(support)
                    if self.elbow_first:
                        # Cancel ID4's pending DRAW movement before issuing an
                        # ID3 lead, rather than merely delaying a new wrist goal.
                        self.cancelled_lateral_counts[self.wrist_index]=(actual_q[self.wrist_index]-self.command_q[self.wrist_index])/self.radians_per_count
                        self.command_q[self.wrist_index]=actual_q[self.wrist_index]
                        self.lead_hold_q=self.command_q.copy()
                        self.lead_start_elbow=actual_q[self.elbow_index]
                        self.lead_finished=False
                    self.load_bias = (self.command_q-actual_q)/self.radians_per_count
                    self.start = np.asarray(command['segment_start_m'])
                    delta = self.anchor-self.start
                    self.offset = delta-self.n*(delta@self.n)
                    self.previous_error_q.fill(0.)
                    self.join_start = None; self.actual_rise = 0.; self.clear_confirmed = False
                    self.vertical_height = 0.
                    self.releases += 1; entered = True
                except (ValueError, KeyError, TypeError):
                    self.anchor = None; self.fallbacks += 1
                    return self._holding(issued_counts)
            self.key = key
            if not fresh or measured is None:
                return self._holding(issued_counts, entered)
            try:
                actual_pose = self.model.pose(self._q(measured))
                actual = actual_pose[:3, 3]
            except (ValueError, KeyError, TypeError):
                self.fallbacks += 1
                return self._holding(issued_counts, entered)
            if self.elbow_first and not self.lead_finished:
                try:
                    lead=self._elbow_lead_target(command,measured,entered)
                except (ValueError, KeyError, TypeError, np.linalg.LinAlgError):
                    self.fallbacks += 1
                    return self._holding(issued_counts,entered)
                if lead is not None:return lead
            nominal = np.asarray(command['tip_reference_m'])
            rise = max(0., float((nominal-self.start)@self.n))
            height = max(.0015, rise)
            if self.elbow_first:
                # A fast elbow can clear before the nominal LIFT ramp catches
                # up. Do not command a descent while handing over to ID4.
                height = max(height, self.lead_clearance+.001,
                    self.lead_clearance+.001-float((self.anchor-self.frame['origin'])@self.n))
            if command.get('endpoint_pause'):
                # Complete both relative release and absolute plane clearance,
                # even when the stroke ended below the model drawing plane.
                height = max(height, self.lift_distance,
                    (self.lift-float((self.anchor-self.frame['origin'])@self.plane_n))/self.normal_gain)
            if self.vertical:
                measured_axis = actual_pose[:3,:3]@self.model.tool_axis
                tilt = float(np.arctan2(np.linalg.norm(np.cross(measured_axis,self.vertical_axis)),
                                       np.dot(measured_axis,self.vertical_axis)))
                # Do not advance a fast elbow while the wrist lags behind.
                # Hold the current vertical target to recover orientation;
                # otherwise ramp it at at most 10 mm/s, with all joints coupled.
                if tilt <= .01:
                    self.vertical_height = min(max(height,self.vertical_height),
                                               self.vertical_height+.010*self.period)
                height = self.vertical_height
            wanted = self.anchor+self.n*height
            self.actual_rise = max(self.actual_rise, float((actual-self.anchor)@self.n))
            # Wrist reorientation at a zero-length/unmeasured TCP can sweep
            # the real pen sideways. Hold the observed pen axis until lifted.
            axis = (self.vertical_axis if self.vertical else
                    self.hold_axis if self.actual_rise < .005 else np.asarray(command['axis_target']))
        elif self.offset is not None and phase in ('TRAVEL', 'LOWER', 'APPROACH'):
            if not fresh or measured is None:
                return self._holding(issued_counts)
            if self.join_start is None:
                self.join_start = float(command['t_s'])-self.period
            x = min(1., max(0., (float(command['t_s'])-self.join_start)/.4))
            blend = 1.-(10*x**3-15*x**4+6*x**5)
            wanted = np.asarray(command['tip_reference_m'])+self.offset*blend
            if blend > 0. and (phase == 'LOWER' or self.vertical and phase == 'TRAVEL'):
                wanted += self.n*max(0., (self.lift-float((wanted-self.frame['origin'])@self.plane_n))/self.normal_gain)
            if x >= 1.:
                self.offset = None
            axis = np.asarray(command['axis_target']); self.key = key
        else:
            self.key = key
            return None, False, None
        try:
            measured_q = self._q(measured)
            reference_q = self._reference(wanted, axis)
            error_q, _, _ = self._task_step(measured_q, wanted, axis)
            # Increment the issued support baseline, rather than solving an
            # ideal position then appending a frozen DRAW integral. Cartesian
            # feedback remains active throughout LIFT and endpoint holding.
            feedforward = reference_q-self.last_reference_q
            correction = self.kp*(error_q-self.previous_error_q)+self.ki*self.period*error_q
            desired = self.command_q+feedforward+correction
            bounded = np.clip(desired, reference_q-self.cap, reference_q+self.cap)
            self.saturated_frames += int(np.any(abs(bounded-desired) > 1e-10))
            delta_q = bounded-self.command_q
            # Keep the coordinated joint increment's proportions; clipping
            # elbow and wrist independently bends the pen during the lift.
            if self.vertical:
                delta_q *= min(1., self.step_cap/max(float(np.max(abs(delta_q))),1e-12))
            else:
                delta_q = np.clip(delta_q, -self.step_cap, self.step_cap)
            q = self.command_q+delta_q
            q = np.clip(q, self.model.limits[:, 0], self.model.limits[:, 1])
            goals = self._counts(q)
            issued_q = self._q(goals)
            step_counts = np.max(abs(issued_q-self.command_q))/self.radians_per_count
            if entered:
                self.max_first_step = max(self.max_first_step, float(step_counts))
            # Preserve fractional encoder counts in the incremental PI state.
            # Rounding that state every cycle discards sub-half-count integral
            # updates and can leave a quantized lift permanently below clear.
            # Only the hardware goal and audit FK use integer issued_q.
            self.command_q = q; self.last_q = reference_q
            self.last_reference_q = reference_q; self.previous_error_q = error_q
            self.last_goals = goals
            predicted = self.model.pose(reference_q)[:3, 3]
            measured_pose = self.model.pose(measured_q)
            actual = measured_pose[:3, 3]
            drift = actual-self.anchor; drift -= self.n*(drift@self.n)
            self.max_xy_drift = max(self.max_xy_drift, float(np.linalg.norm(drift)))
            self.maximum_error = max(self.maximum_error, float(np.linalg.norm(predicted-wanted)))
            reference_counts = self._counts(reference_q)
            correction_counts = np.asarray([goals[j['id']]-reference_counts[j['id']] for j in self.machine['joints']])
            self.max_correction = max(self.max_correction, float(np.max(abs(correction_counts))))
            measured_axis = measured_pose[:3,:3]@self.model.tool_axis
            axis_error = float(np.arctan2(np.linalg.norm(np.cross(measured_axis,axis)),np.dot(measured_axis,axis)))
            self.max_axis_error = max(self.max_axis_error,axis_error)
            return goals, entered, dict(version=VERSION, frozen_tip_m=self.anchor.tolist(),
                release_stage='vertical_lift' if self.vertical else 'coordinated_lift',
                requested_axis=axis.tolist(),measured_axis=measured_axis.tolist(),axis_error_rad=axis_error,
                requested_tip_m=wanted.tolist(), reference_tip_m=predicted.tolist(),
                issued_tip_m=self.model.pose(issued_q)[:3, 3].tolist(), load_bias_counts=self.load_bias.tolist(),
                correction_counts=correction_counts.tolist(), phase=phase, feedback_hold=False,
                correction_saturated_joint_ids=[joint['id'] for joint,value in
                    zip(self.machine['joints'],abs(bounded-desired)) if value>1e-10],
                cancelled_lateral_counts=self.cancelled_lateral_counts.tolist(),
                held_pen_axis=bool(phase == 'LIFT' and (self.vertical or self.actual_rise < .005)),
                clearance=self.clearance_detail(measured, fresh))
        except (ValueError, KeyError, TypeError, np.linalg.LinAlgError):
            self.fallbacks += 1
            return self._holding(issued_counts, entered)

    def summary(self):
        return dict(version=VERSION, enabled=self.enabled, releases=self.releases, fallbacks=self.fallbacks,
            max_ik_residual_m=self.maximum_error, max_measured_xy_drift_m=self.max_xy_drift,
            max_first_goal_step_counts=self.max_first_step, max_total_correction_counts=self.max_correction,
            correction_cap_counts=(int(self.cap_counts[0]) if np.all(self.cap_counts==self.cap_counts[0]) else
                {str(joint['id']):int(value) for joint,value in zip(self.machine['joints'],self.cap_counts)}),
            per_cycle_step_cap_counts=12, saturated_frames=self.saturated_frames,
            lift_sequence='vertical_coordinated' if self.vertical else 'id3_then_id4' if self.elbow_first else 'coordinated',
            max_measured_axis_error_rad=self.max_axis_error,
            lead_clearance_m=self.lead_clearance if self.elbow_first else None,
            id3_lead_confirmations=self.lead_releases,
            missing_feedback_hold_frames=self.missing_feedback_holds, clearance_checks=self.clearance_checks,
            clearance_wait_frames=self.clearance_wait_frames, clearance_confirmations=self.clearance_confirmations,
            scope='encoder model closed-loop release; no physical contact sensor or following-error abort')
