"""Bounded Q5 smoothing in millimetres; no joins, deletions or motor I/O."""
import math
import numpy as np
import cv2

VERSION = 'path-quality-sg-v1'


def resample(points, step=.5):
    p = np.asarray(points, dtype=float)
    ds = np.linalg.norm(np.diff(p, axis=0), axis=1)
    p = p[np.r_[True, ds > 1e-10]]
    if len(p) < 2:
        return p
    s = np.r_[0., np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
    at = np.r_[np.arange(0., s[-1], step), s[-1]]
    return np.column_stack([np.interp(at, s, p[:, k]) for k in (0, 1)])


def _max_distance_python(points, chain, stop):
    a, b = chain[:-1], chain[1:]
    v = b-a
    vv = np.maximum(np.sum(v*v, axis=1), 1e-20)
    worst = 0.
    for start in range(0, len(points), 128):
        d = points[start:start+128, None, :]-a[None, :, :]
        t = np.clip(np.sum(d*v[None, :, :], axis=2)/vv, 0., 1.)
        nearest = d-t[:, :, None]*v
        worst = max(worst, float(np.sqrt(np.min(np.sum(nearest*nearest, axis=2), axis=1)).max()))
        if worst > stop:
            break
    return worst


def _max_distance(points,chain,stop):
    from native.lineart import get_kernel
    core=get_kernel()
    if core is not None:
        try:return core.distance(points,chain,stop)
        except (ValueError,RuntimeError):pass
    return _max_distance_python(points,chain,stop)


def _deviation_bound(source, candidate, step=.1, limit=.2):
    # Distance to a polyline is 1-Lipschitz. A half-step margin covers the
    # unsampled interval, instead of claiming vertex-only tests prove a bound.
    worst = 0.
    for a, b in ((source, candidate), (candidate, source)):
        if np.linalg.norm(np.diff(a, axis=0), axis=1).sum()/step > 40000:
            return math.inf
        worst = max(worst, _max_distance(resample(a, step), b, limit))
        if worst+step/2 > limit:
            return worst+step/2
    return worst+step/2


def smooth_strokes(paths, step_mm=.5, window=7, tolerance_mm=.2, corner_deg=70.):
    """SG order 2 plus simplification; fixed endpoints and >70 degree corners.

    Every accepted chain is checked bidirectionally against its source within
    the combined smoothing/simplification tolerance. Failure retains the source.
    """
    if not (.1 <= step_mm <= 1 and window in (7, 9) and .05 <= tolerance_mm <= .2):
        raise ValueError('Invalid stroke smoothing parameters')
    radius = window//2
    x = np.arange(-radius, radius+1, dtype=float)
    weights = np.linalg.pinv(np.column_stack([np.ones(window), x, x*x]))[0]
    result, changed, fallback, upper = [], 0, 0, 0.
    for chain in paths:
        source = np.asarray(chain, dtype=float)
        if source.ndim != 2 or source.shape[1] != 2 or len(source) < 2 or not np.isfinite(source).all():
            raise ValueError('Invalid stroke points')
        source = source[np.r_[True, np.linalg.norm(np.diff(source, axis=0), axis=1) > 1e-10]]
        if len(source) < 2:
            raise ValueError('Zero-length stroke')
        d = np.diff(source, axis=0)
        cosine = np.sum(d[:-1]*d[1:], axis=1)/np.maximum(
            np.linalg.norm(d[:-1], axis=1)*np.linalg.norm(d[1:], axis=1), 1e-20)
        corners = np.flatnonzero(np.arccos(np.clip(cosine, -1., 1.)) > math.radians(corner_deg))+1
        breaks = [0]+corners.tolist()+[len(source)-1]
        pieces = []
        for lo, hi in zip(breaks, breaks[1:]):
            p = resample(source[lo:hi+1], step_mm)
            filtered = p.copy()
            if len(p) >= window:
                for i in range(radius, len(p)-radius):
                    filtered[i] = weights @ p[i-radius:i+radius+1]
            # Endpoints include actual sharp corners and must remain exact.
            simple = cv2.approxPolyDP(filtered.astype(np.float32).reshape(-1, 1, 2),
                                     tolerance_mm/2, False).reshape(-1, 2).astype(float)
            simple[0], simple[-1] = source[lo], source[hi]
            pieces.extend(simple.tolist() if not pieces else simple[1:].tolist())
        candidate = np.asarray(pieces)
        closed = np.linalg.norm(source[0]-source[-1]) < 1e-8
        if (len(candidate) < 2 or np.linalg.norm(np.diff(candidate, axis=0), axis=1).sum() <= 1e-8
                or (closed and len(np.unique(candidate[:-1], axis=0)) < 3)):
            result.append(source.tolist()); fallback += 1
            continue
        bound = _deviation_bound(source, candidate, limit=tolerance_mm)
        if bound > tolerance_mm:
            result.append(source.tolist()); fallback += 1
        else:
            result.append(candidate.tolist()); changed += 1; upper = max(upper, bound)
    return result, dict(version=VERSION, step_mm=step_mm, window=window, polynomial_order=2,
                        tolerance_mm=tolerance_mm, corner_preserve_deg=corner_deg,
                        accepted_strokes=changed, retained_source_strokes=fallback,
                        max_accepted_deviation_bound_mm=upper,
                        policy='fixed_endpoints_corners_bidirectional_total_error_no_deletion')
