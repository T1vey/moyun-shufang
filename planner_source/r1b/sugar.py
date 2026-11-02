"""Sugar drawing path timing and bounded, posture-preserving vertical IK.

All distances are metres; these routines plan commands and never drive hardware.
"""
import math
import numpy as np
from r1a.solve import Result


def lift_ik(model, q_start, height, *, seed=None, iterations=12, tolerance=1e-8):
    """Fixed ID1/5, solve ID2/3 and enforce q4 = pitch - q2 - q3.

    The actual starting axis is preserved. The caller independently verifies
    that it already matches the world-vertical requested axis.
    """
    q0 = np.asarray(q_start, dtype=float)
    if q0.shape != (5,) or not np.isfinite(q0).all() or not math.isfinite(float(height)):
        raise ValueError('VERTICAL_INVALID_INPUT')
    if type(iterations) is not int or not 1 <= iterations <= 100:
        raise ValueError('VERTICAL_INVALID_BUDGET')
    if not model.legal(q0):
        raise ValueError('VERTICAL_ILLEGAL_START')
    required = np.asarray([[0, 0, 1], [0, 1, 0], [0, 1, 0], [0, 1, 0], [1, 0, 0]])
    if not np.allclose(model.axes, required, atol=1e-12, rtol=0):
        raise ValueError('VERTICAL_UNSUPPORTED_AXES')
    goal = model.pose(q0)[:3, 3] + [0., 0., float(height)]
    pitch = float(q0[1:4].sum())
    q = q0.copy() if seed is None else np.asarray(seed, dtype=float).copy()
    if q.shape != (5,) or not np.isfinite(q).all():
        raise ValueError('VERTICAL_INVALID_SEED')
    q[[0, 4]] = q0[[0, 4]]
    q[3] = pitch-q[1]-q[2]
    error = float('inf')
    for k in range(iterations+1):
        pose, jac = model.evaluate(q)
        delta = goal-pose[:3, 3]
        error = float(np.linalg.norm(delta))
        if error <= tolerance and model.legal(q):
            return q, k, error
        if k == iterations:
            break
        # q4 cancels both unknowns: exact constrained translational Jacobian.
        reduced = jac[:3, [1, 2]]-jac[:3, 3, None]
        step = np.linalg.lstsq(reduced, delta, rcond=1e-10)[0]
        if not np.isfinite(step).all() or np.linalg.norm(step) > 1.:
            raise ValueError('VERTICAL_SINGULAR')
        accepted = False
        for scale in (1., .5, .25, .125, .0625):
            candidate = q.copy()
            candidate[1:3] += scale*step
            candidate[3] = pitch-candidate[1]-candidate[2]
            if model.legal(candidate) and np.linalg.norm(goal-model.pose(candidate)[:3, 3]) < error:
                q = candidate
                accepted = True
                break
        if not accepted:
            raise ValueError('VERTICAL_LIMIT_OR_STAGNATION')
    raise ValueError('VERTICAL_NO_CONVERGENCE')


def vertical_result(model, anchor_q, anchor_position, target, seed, ik_cfg):
    """R1a-compatible result for a single shared-height vertical sample."""
    try:
        position = np.asarray(target['position'])
        if np.linalg.norm(position[:2]-np.asarray(anchor_position)[:2]) > 1e-10:
            raise ValueError('VERTICAL_XY_TARGET_CHANGED')
        q, count, _ = lift_ik(model, anchor_q, position[2]-anchor_position[2], seed=seed,
                            iterations=min(12,int(ik_cfg['max_iterations'])))
        pose = model.pose(q)
        error = float(np.linalg.norm(position-pose[:3, 3]))
        axis = pose[:3, :3] @ model.tool_axis
        desired = np.asarray(target['axis'])
        tilt = float(np.arctan2(np.linalg.norm(np.cross(axis, desired)), axis@desired))
        status = 'OK' if error <= float(ik_cfg['position_tolerance_m']) and tilt <= float(ik_cfg['tilt_tolerance_rad']) else 'VERTICAL_ANCHOR_ERROR'
        return Result(status, q.tolist() if status == 'OK' else None, q.tolist(), count, error, tilt, [])
    except ValueError as exc:
        return Result(str(exc), None, np.asarray(seed).tolist(), 0, None, None, [])


def vertical_samples(start, end, phase, cfg):
    """Time-spaced h(t) knots; slowdown is smooth over the last 1.5 mm.

    A smooth coordinate warp allocates extra time to the contact end without
    introducing a velocity/acceleration discontinuity or a hidden stop.
    """
    start, end = np.asarray(start, float), np.asarray(end, float)
    duration = float(cfg['min_'+phase.lower()+'_motion_s'])
    n = max(8, int(math.ceil(duration/float(cfg['command_period_s']))))
    u = np.linspace(0., 1., n+1)
    s = 10*u**3-15*u**4+6*u**5
    if phase == 'LOWER':
        fraction = min(1., float(cfg.get('soft_lower_last_m', .0015))/max(float(np.linalg.norm(end-start)), 1e-12))
        # Time coordinate is integral of a smoothly increasing inverse speed.
        # The terminal 25% of distance has ~half the speed of the unwarped law.
        grid = np.linspace(0., 1., 1001)
        transition = np.clip((grid-(1-fraction))/max(fraction, 1e-9), 0., 1.)
        density = 1.+(3*transition**2-2*transition**3)
        cumulative = np.r_[0., np.cumsum((density[:-1]+density[1:])*.0005)]
        s = np.interp(s*cumulative[-1], cumulative, grid)
    return [(start+f*(end-start), float(t*duration)) for f, t in zip(s[1:], u[1:])]


def path_times(points, speed, acceleration, lateral=None):
    """Forward/backward arc-length envelope with exact short-block timing."""
    p = np.asarray(points, float)
    if p.ndim != 2 or p.shape[1] != 3 or len(p) < 2 or not np.isfinite(p).all():
        raise ValueError('invalid Cartesian timing points')
    if not math.isfinite(speed) or not math.isfinite(acceleration) or min(speed, acceleration) <= 0:
        raise ValueError('invalid Cartesian timing limits')
    ds = np.linalg.norm(np.diff(p, axis=0), axis=1)
    v = np.full(len(p), float(speed))
    if lateral is not None:
        if not math.isfinite(lateral) or lateral <= 0:
            raise ValueError('invalid lateral acceleration')
        if len(p) > 2:
            d = np.diff(p, axis=0)
            cosine = np.einsum('ij,ij->i', d[:-1], d[1:])/np.maximum(ds[:-1]*ds[1:], 1e-20)
            angle = np.arccos(np.clip(cosine, -1., 1.))
            radius = np.minimum(ds[:-1], ds[1:])/np.maximum(angle, 1e-9)
            v[1:-1] = np.minimum(v[1:-1], np.sqrt(lateral*radius))
    v[0] = v[-1] = 0.
    for i in range(1, len(v)):
        v[i] = min(v[i], math.sqrt(v[i-1]**2+2*acceleration*ds[i-1]))
    for i in range(len(v)-2, -1, -1):
        v[i] = min(v[i], math.sqrt(v[i+1]**2+2*acceleration*ds[i]))
    times = np.zeros(len(ds))
    for i, distance in enumerate(ds):
        # Integrate accelerate/cruise/decelerate, including a 2-node block.
        peak = min(speed, math.sqrt(max(0., acceleration*distance+(v[i]**2+v[i+1]**2)/2)))
        up = max(0., (peak**2-v[i]**2)/(2*acceleration))
        down = max(0., (peak**2-v[i+1]**2)/(2*acceleration))
        times[i] = (peak-v[i])/acceleration+(peak-v[i+1])/acceleration+max(0., distance-up-down)/max(peak, 1e-12)
    return times


def block_times(q, targets, blocks, cfg, velocity_limits):
    times = np.empty(len(q)-1)
    minimum = float(cfg['min_segment_s'])
    for start, end in blocks:
        phase = targets[start+1]['phase']
        temporal = all('vertical_time_s' in t for t in targets[start+1:end+1])
        if temporal:
            values = np.asarray([0.]+[t['vertical_time_s'] for t in targets[start+1:end+1]])
            local = np.diff(values)
        else:
            params = cfg['cartesian_limits']['draw' if phase == 'DRAW' else 'travel']
            local = path_times([t['position'] for t in targets[start:end+1]],
                params['tip_speed_m_s'], params['tip_acc_m_s2'], params.get('lateral_acc_m_s2'))
            local = np.maximum(local, minimum)
        if not np.isfinite(local).all() or np.any(local <= 0):
            raise ValueError('invalid arc length segment time')
        # Shared block dilation preserves the path velocity envelope.
        factor = max(1., float(np.max(np.abs(np.diff(q[start:end+1], axis=0))/local[:, None]/velocity_limits)))
        times[start:end] = local*factor
    return times


def node_velocities(q, times, blocks):
    """Nonuniform central slopes, bounded at reversals, shared across phases."""
    v = np.zeros_like(q)
    secant = np.diff(q, axis=0)/times[:, None]
    for start, end in blocks:
        for i in range(start+1, end):
            left, right = secant[i-1], secant[i]
            same = left*right > 0
            central = (times[i]*left+times[i-1]*right)/(times[i-1]+times[i])
            v[i] = np.where(same, np.sign(central)*np.minimum(np.abs(central), 3*np.minimum(abs(left), abs(right))), 0.)
    return v


def vertical_derivatives(q, times, targets, blocks, v, a):
    """Recover derivatives of the common h(t), with C2 resting endpoints."""
    for start, end in blocks:
        if not all('vertical_time_s' in t for t in targets[start+1:end+1]):
            continue
        ts = np.r_[0., np.cumsum(times[start:end])]
        for local in range(1, end-start):
            lo, hi = max(0, local-3), min(len(ts), local+4)
            # Fit in scaled local coordinates to avoid poorly conditioned powers.
            scale = max(float(ts[hi-1]-ts[lo]), 1e-12)
            x = (ts[lo:hi]-ts[local])/scale
            coefficients = np.polynomial.polynomial.polyfit(x, q[start+lo:start+hi], min(5, hi-lo-1))
            v[start+local] = coefficients[1]/scale
            a[start+local] = 2*coefficients[2]/scale**2
        # Make the sum q2+q3+q4 invariant in polynomial arithmetic as well.
        v[start:end+1, 3] = -v[start:end+1, 1]-v[start:end+1, 2]
        a[start:end+1, 3] = -a[start:end+1, 1]-a[start:end+1, 2]
    return v, a
