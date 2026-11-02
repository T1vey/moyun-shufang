"""Bounded quintic motion mathematics. No hardware or optional dependencies."""
import math
import numpy as np
from .continuous import _HULL4, _HULL3, _subdivided_hull

MOTION_VERSION = 'motion-smooth-v1'
PROFILE = 'continuous_quintic_vaj'
_HULL5 = _subdivided_hull(5)


def normalize_motion_limits(cfg):
    result = []
    for field, old, default in (
            ('joint_max_velocity_rad_s', 'max_velocity_rad_s', .12),
            ('joint_max_acceleration_rad_s2', 'max_acceleration_rad_s2', .3),
            ('joint_max_jerk_rad_s3', 'max_jerk_rad_s3', 20.)):
        values = np.asarray(cfg.get(field, cfg.get(old, default)), dtype=float)
        if values.ndim == 0:
            values = np.full(5, float(values))
        if values.shape != (5,) or not np.isfinite(values).all() or np.any(values <= 0):
            raise ValueError('invalid ' + field)
        result.append(values)
    return tuple(result)


def quintic_full(qa, qb, va, vb, aa, ab, duration):
    d = qb-qa
    x, y = va*duration, vb*duration
    a0, a1 = aa*duration**2, ab*duration**2
    return np.array([qa, x, a0/2,
                     10*d-6*x-4*y-1.5*a0+.5*a1,
                     -15*d+8*x+7*y+1.5*a0-a1,
                     6*d-3*x-3*y-.5*a0+.5*a1])


def derivative_bounds_many(coeffs, durations):
    c, t = np.asarray(coeffs, dtype=float), np.asarray(durations, dtype=float)
    if (c.ndim != 3 or c.shape[1:] != (6, 5) or t.shape != (len(c),)
            or not np.isfinite(c).all() or not np.isfinite(t).all() or np.any(t <= 0)):
        raise ValueError('invalid polynomial segments')
    v = np.arange(1, 6)[None, :, None]*c[:, 1:]/t[:, None, None]
    a = np.arange(1, 5)[None, :, None]*v[:, 1:]/t[:, None, None]
    pv = np.max(np.abs(_HULL4 @ v), axis=1)
    pa = np.max(np.abs(_HULL3 @ a), axis=1)
    j0 = 6*c[:, 3]/t[:, None]**3
    j1 = (6*c[:, 3]+24*c[:, 4]+60*c[:, 5])/t[:, None]**3
    pj = np.maximum(np.abs(j0), np.abs(j1))
    u = np.zeros_like(c[:, 5])
    moving = np.abs(c[:, 5]) > 1e-18
    np.divide(-c[:, 4], 5*c[:, 5], out=u, where=moving)
    vertex = (moving & (u > 0) & (u < 1))
    u = np.clip(u, 0, 1)
    candidate = np.abs((6*c[:, 3]+24*c[:, 4]*u+60*c[:, 5]*u*u)/t[:, None]**3)
    pj = np.maximum(pj, np.where(vertex, candidate, 0.))
    return pv, pa, pj


def legal_segments(coeffs, limits):
    """Conservative whole-curve joint limits from subdivided Bezier hulls."""
    controls = _HULL5 @ coeffs
    return np.all((controls >= limits[:, 0]-1e-12) &
                  (controls <= limits[:, 1]+1e-12), axis=(1, 2))


def time_ratios(coeffs, durations, limits):
    v, a, j = derivative_bounds_many(coeffs, durations)
    vm, am, jm = limits
    return np.maximum(1., np.maximum(np.max(v/vm, axis=1),
        np.maximum(np.sqrt(np.max(a/am, axis=1)), np.cbrt(np.max(j/jm, axis=1)))))


def stop_blocks(targets, cfg):
    """Cuts refer to joint knots: knot i terminates segment i-1."""
    cuts, reasons = [0], {0: 'start'}
    threshold = float(cfg.get('corner_stop_angle_deg', 45.))
    if not math.isfinite(threshold) or not 0 < threshold < 180:
        raise ValueError('invalid corner_stop_angle_deg')
    for i in range(1, len(targets)-1):
        a, b, c = targets[i-1:i+2]
        reason = None
        if b['phase'] != c['phase'] or b['stroke'] != c['stroke']:
            reason = 'phase_or_stroke_boundary'
        elif b.get('must_stop'):
            reason = b.get('stop_reason', 'explicit')
        else:
            d1 = np.asarray(b['position'])-a['position']
            d2 = np.asarray(c['position'])-b['position']
            norm = float(np.linalg.norm(d1)*np.linalg.norm(d2))
            if norm < 1e-18:
                reason = 'zero_geometry'
            elif float(d1@d2)/norm < math.cos(math.radians(threshold)):
                reason = 'sharp_corner'
        if reason:
            cuts.append(i); reasons[i] = reason
    cuts.append(len(targets)-1); reasons[len(targets)-1] = 'end'
    return list(zip(cuts[:-1], cuts[1:])), reasons


def _band_solve(matrix, rhs):
    """Scaled SPD LDL^T, half bandwidth 3; O(N) memory/work for fixed width."""
    a, b = matrix.copy(), rhs.copy()
    n, width = a.shape[0], a.shape[1]-1
    scales = np.sqrt(a[:, 0])
    if not np.isfinite(scales).all() or np.any(scales <= 0):
        raise ValueError('DERIVATIVE_SOLVER_FAILURE')
    for k in range(width+1):
        a[k:, k] /= scales[k:]*scales[:n-k]
    b /= scales[:, None]
    lower = np.zeros_like(a); diagonal = np.empty(n)
    for i in range(n):
        start = max(0, i-width)
        for j in range(start, i):
            value = a[i, i-j]
            for k in range(start, j):
                value -= lower[i, i-k]*diagonal[k]*lower[j, j-k]
            lower[i, i-j] = value/diagonal[j]
        diagonal[i] = a[i, 0]-sum(lower[i, i-k]**2*diagonal[k] for k in range(start, i))
        if not math.isfinite(diagonal[i]) or diagonal[i] <= 1e-12:
            raise ValueError('DERIVATIVE_SOLVER_FAILURE')
        for k in range(start, i):
            b[i] -= lower[i, i-k]*b[k]
    b /= diagonal[:, None]
    for i in range(n-1, -1, -1):
        for k in range(i+1, min(n, i+width+1)):
            b[i] -= lower[k, k-i]*b[k]
    result = b/scales[:, None]
    if not np.isfinite(result).all():
        raise ValueError('DERIVATIVE_SOLVER_FAILURE')
    return result


def minimum_jerk_nodes(q, times, cancel=None):
    """Positions fixed; shared v/a minimise exact integral of squared jerk.

    Endpoints rest. A component reversing its secants has v=0 (not a=0).
    The unconstrained minimum is subsequently checked/retimed by the caller.
    """
    q, times = np.asarray(q, dtype=float), np.asarray(times, dtype=float)
    n = len(times)
    if (q.shape != (n+1, 5) or n < 1 or times.shape != (n,)
            or not np.isfinite(q).all() or not np.isfinite(times).all() or np.any(times <= 0)):
        raise ValueError('DERIVATIVE_SOLVER_FAILURE')
    if n == 1 or np.max(np.abs(q-q[0])) < 1e-14:
        return np.zeros_like(q), np.zeros_like(q)
    if cancel and cancel():
        raise ValueError('ABORT')
    reference_time = float(np.median(times))
    t = times[:, None]
    basis = np.empty((n, 3, 4))
    basis[:, 0] = np.concatenate((-36*t, -9*t*t, -24*t, 3*t*t), axis=1)
    basis[:, 1] = np.concatenate((192*t, 36*t*t, 168*t, -24*t*t), axis=1)
    basis[:, 2] = np.concatenate((-180*t, -30*t*t, -180*t, 30*t*t), axis=1)
    basis /= np.array([reference_time, reference_time**2, reference_time, reference_time**2])
    integral = 1./(np.arange(3)[:, None]+np.arange(3)[None, :]+1)
    base = np.array([60., -360., 360.])[None, :, None]*np.diff(q, axis=0)[:, None, :]
    weights = (reference_time/times)**5
    hessian = (np.transpose(basis, (0, 2, 1)) @ integral @ basis)*weights[:, None, None]
    linear = -(np.transpose(basis, (0, 2, 1)) @ integral @ base)*weights[:, None, None]
    size = 2*(n+1)
    band, rhs = np.zeros((size, 4)), np.zeros((size, 5))
    indices = 2*np.arange(n)
    for i in range(4):
        np.add.at(rhs, indices+i, linear[:, i])
        for j in range(i+1):
            np.add.at(band[:, i-j], indices+i, hessian[:, i, j])
    fixed = np.zeros((size, 5), dtype=bool)
    fixed[:2] = True; fixed[-2:] = True
    delta = np.diff(q, axis=0)
    fixed[2:-2:2] = delta[:-1]*delta[1:] <= 0
    result = np.zeros_like(rhs)
    groups = {}
    for axis in range(5):
        groups.setdefault(fixed[:, axis].tobytes(), []).append(axis)
    for axes in groups.values():
        if cancel and cancel():
            raise ValueError('ABORT')
        h, r = band.copy(), rhs[:, axes].copy()
        for i in np.flatnonzero(fixed[:, axes[0]]):
            for j in range(max(0, i-3), min(size, i+4)):
                h[max(i, j), abs(i-j)] = 0.
            h[i, 0] = 1.; r[i] = 0.
        result[:, axes] = _band_solve(h, r)
    return result[0::2]/reference_time, result[1::2]/reference_time**2


def rest_move(start, end, cfg):
    """Synchronous bounded rest-to-rest q(t), including explicit jerk bound."""
    start, end = np.asarray(start, dtype=float), np.asarray(end, dtype=float)
    if start.shape != (5,) or end.shape != (5,) or not np.isfinite([start, end]).all():
        raise ValueError('invalid joint move')
    v, a, j = normalize_motion_limits(cfg)
    distance = np.abs(end-start)
    period = float(cfg.get('command_period_s', .05))
    if not math.isfinite(period) or period <= 0:
        raise ValueError('invalid command_period_s')
    duration = max(2*period, float(np.max(1.875*distance/v)),
                   math.sqrt(float(np.max((10/math.sqrt(3))*distance/a))),
                   float(np.cbrt(np.max(60*distance/j))))
    duration = math.ceil(duration/period)*period
    zero = np.zeros(5)
    return quintic_full(start, end, zero, zero, zero, zero, duration), duration
