"""Explicit W/mu semantics. Legacy mode emulates upstream RHS-only weighting.

Legacy mode is a single-step formula oracle, NOT upstream's complete HLS or
iteration wrapper. Non-unit S is a paired ablation, not an upstream default.
"""
import numpy as np
from .model import finite_array


def inputs(j, e, w, scales, mu, mode="wls"):
    j = finite_array(j, (6, 5), "J")
    e = finite_array(e, (6,), "e")
    w = finite_array(w, (6,), "W")
    scales = finite_array(scales, (6,), "S")
    if np.any(w < 0) or np.any(scales <= 0) or not np.isfinite(mu) or mu <= 0:
        raise ValueError("W >= 0, S > 0 and finite mu > 0 required")
    if mode not in ("wls", "rhs_only"):
        raise ValueError("unknown weighting mode")
    return j, e, w, scales, float(mu)


def system(j, e, w, scales, mu, mode="wls"):
    j, e, w, scales, mu = inputs(j, e, w, scales, mu, mode)
    with np.errstate(over="raise", invalid="raise"):
        js, es = j * scales[:, None], e * scales
        lhs = js.T @ ((w if mode == "wls" else np.ones(6))[:, None] * js) + mu * np.eye(5)
        rhs = js.T @ (w * es)
    if not np.isfinite(lhs).all() or not np.isfinite(rhs).all():
        raise FloatingPointError("normal equation overflow")
    return lhs, rhs


def step(j, e, w, scales, mu, mode="wls"):
    a, b = system(j, e, w, scales, mu, mode)
    lower = np.linalg.cholesky(a)
    dq = np.linalg.solve(lower.T, np.linalg.solve(lower, b))
    if not np.isfinite(dq).all():
        raise FloatingPointError("non-finite increment")
    return dq


def independent_wls(j, e, w, scales, mu):
    """Augmented least-squares/SVD oracle, does not form normal equations."""
    j, e, w, scales, mu = inputs(j, e, w, scales, mu)
    s = scales * np.sqrt(w)
    augmented = np.vstack((j * s[:, None], np.sqrt(mu) * np.eye(5)))
    rhs = np.r_[e * s, np.zeros(5)]
    return np.linalg.lstsq(augmented, rhs, rcond=None)[0]
