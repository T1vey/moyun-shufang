"""Fit the controller<->URDF mapping from static joint/pose samples (Web feedback).

Unknowns: per-joint SDK sign (discrete) and zero offset, T_controller_base_from_model
(6 DoF), the controller TCP in the URDF flange frame (6 DoF) and, with geometry=True,
per-joint link-geometry corrections (J2..J7 origin dx,dy,dz,rx,ry; regularised toward
0 with sigma 3 mm / 0.5 deg). Rotations about a joint axis duplicate its zero offset
and J1's correction duplicates the base, so those are not fitted. The controller's
r_world_fb_pos (tool as configured on the controller, usually tool 0) is the TCP.
Validation: fit on the first 2/3 of the samples, check the rest. Nothing is applied
unless every hold-out sample is within the thresholds.
"""
import copy
import itertools
import math
import numpy as np
from .model import Model, rpy_matrix, transform

LIMITS = dict(position_mm=0.5, angle_deg=0.2)
NB = 19                      # basic parameters: 7 offsets + base 6 + tool 6
NG = NB + 7 * 5              # + per-joint origin corrections (dx, dy, dz, rx, ry)
SIGMA_MM, SIGMA_MRAD = 3.0, 8.7


def _axis_rot(axes, angles):
    # axes (7,3) unit, angles (N,7) -> (N,7,3,3) Rodrigues
    x, y, z = axes[:, 0], axes[:, 1], axes[:, 2]
    k = np.zeros((7, 3, 3)); k[:, 0, 1] = -z; k[:, 0, 2] = y; k[:, 1, 0] = z; k[:, 1, 2] = -x; k[:, 2, 0] = -y; k[:, 2, 1] = x
    s = np.sin(angles)[..., None, None]; c = np.cos(angles)[..., None, None]
    return np.eye(3) + s * k + (1 - c) * (k @ k)


def _exp6(v):
    r = rpy_matrix(v[3:]); t = np.eye(4); t[:3, :3] = r; t[:3, 3] = v[:3]; return t


class Fitter:
    def __init__(self, model, q_deg, poses):
        self.data = model.data; self.n = len(q_deg)
        self.origins = self.data[:, :16].reshape(7, 4, 4)
        self.axes = self.data[:, 16:19] / np.linalg.norm(self.data[:, 16:19], axis=1)[:, None]
        self.q = np.radians(np.asarray(q_deg, dtype=float))
        self.T = np.array([_pose(p) for p in poses])

    def fk(self, q, corr=None):
        rot = _axis_rot(self.axes, q)
        t = np.tile(np.eye(4), (len(q), 1, 1))
        for j in range(7):
            r = np.tile(np.eye(4), (len(q), 1, 1)); r[:, :3, :3] = rot[:, j]
            o = self.origins[j] if corr is None else self.origins[j] @ corr[j]
            t = t @ o @ r
        return t

    @staticmethod
    def corrections(x):
        if len(x) <= NB:
            return None
        c = x[NB:NG].reshape(7, 5)
        return [_exp6(np.r_[c[j, :3], c[j, 3:5], 0.0]) for j in range(7)]

    def predict(self, sign, x, rows=None):
        q = self.q if rows is None else self.q[rows]
        model_q = q * sign + x[:7]
        return _exp6(x[7:13]) @ self.fk(model_q, self.corrections(x)) @ _exp6(x[13:19])

    def residual(self, sign, x, rows=None):
        T = self.T if rows is None else self.T[rows]; P = self.predict(sign, x, rows)
        dp = (P[:, :3, 3] - T[:, :3, 3]) * 1000.0  # mm
        # full matrix difference: unlike the skew part it does not vanish at 180 deg
        dr = (P[:, :3, :3] - T[:, :3, :3]) * (1000.0 / math.sqrt(2.0))  # ~1 mm per mrad
        out = [dp.ravel(), dr.ravel()]
        if len(x) > NB:  # ridge prior keeps the geometry corrections small and identifiable
            c = x[NB:NG].reshape(7, 5)
            out.append(np.r_[(c[1:, :3] * 1000.0 / SIGMA_MM).ravel(), (c[1:, 3:] * 1000.0 / SIGMA_MRAD).ravel()])
        return np.concatenate(out)

    # J1 zero == base yaw and J7 zero == tool roll (gauge freedoms): keep them at 0.
    FREE = [k for k in range(19) if k not in (0, 6)]
    FREE_GEOMETRY = FREE + [NB + 5 * j + k for j in range(1, 7) for k in range(5)]

    def lm(self, sign, x0, rows, iters=200):
        x = np.array(x0, float); x[0] = x[6] = 0.0; r = self.residual(sign, x, rows); cost = r @ r; lam = 1e-3
        free = self.FREE_GEOMETRY if len(x) > NB else self.FREE
        for _ in range(iters):
            J = np.empty((len(r), len(free)))
            for c, k in enumerate(free):
                d = np.zeros(len(x)); d[k] = 1e-7
                J[:, c] = (self.residual(sign, x + d, rows) - r) / 1e-7
            g = J.T @ r; H = J.T @ J
            step = np.zeros(len(x)); step[free] = np.linalg.solve(H + lam * np.diag(np.diag(H) + 1e-9), -g)
            xn = x + step; rn = self.residual(sign, xn, rows); cn = rn @ rn
            if cn < cost:
                x, r, cost, lam = xn, rn, cn, lam * 0.3
                if np.linalg.norm(step) < 1e-12:
                    break
            else:
                lam *= 10
                if lam > 1e10:
                    break
        return x, cost


def _pose(p):
    t = np.eye(4); t[:3, :3] = rpy_matrix(np.radians(p[3:6])); t[:3, 3] = np.asarray(p[:3]) / 1000.0; return t


def errors(fitter, sign, x, rows):
    T = fitter.T[rows]; P = fitter.predict(sign, x, rows); out = []
    for a, b in zip(P, T):
        d = a[:3, :3] @ b[:3, :3].T
        out.append((float(np.linalg.norm(a[:3, 3] - b[:3, 3]) * 1000), math.degrees(math.acos(max(-1, min(1, (np.trace(d) - 1) / 2))))))
    return out


def fit(config, samples, signs=None, geometry=False):
    q = [s['joint_degrees'] for s in samples]; p = [s['world_mm_deg'] for s in samples]
    if len(samples) < 12:
        raise ValueError('至少需要 12 个静止样本')
    spread = np.ptp(np.asarray(q), axis=0)
    if np.any(spread < 4):
        raise ValueError('每个关节至少需要 4 度变化：%s' % np.round(spread, 2).tolist())
    model = Model(config); f = Fitter(model, q, p)
    n = len(samples); fit_rows = np.arange(n) < (2 * n + 2) // 3; hold = ~fit_rows
    best = None
    combos = [np.asarray(signs, float)] if signs is not None else [np.array(c, float) for c in itertools.product((1, -1), repeat=7)]
    starts = []
    grid = (0.0, math.pi / 2, -math.pi / 2, math.pi)
    for s in combos:
        for yaw, o2, o4, o6 in itertools.product((0.0, math.pi), grid, grid, grid):
            x0 = np.zeros(19); x0[12] = yaw; x0[1] = o2; x0[3] = o4; x0[5] = o6
            # coarse: base translation from mean position difference
            P = f.predict(s, x0, fit_rows); x0[7:10] = (f.T[fit_rows, :3, 3] - P[:, :3, 3]).mean(axis=0)
            starts.append((float(f.residual(s, x0, fit_rows) @ f.residual(s, x0, fit_rows)), s, x0))
    starts.sort(key=lambda v: v[0])
    cands = []
    for _, s, x0 in starts[:64]:
        x, cost = f.lm(s, x0, fit_rows)
        cands.append((cost, s, x))
    cands.sort(key=lambda c: c[0])
    _, s, x = cands[0]
    x, best_cost = f.lm(s, x, fit_rows, iters=400)
    basic = x.copy()
    if geometry:  # refine link geometry from the basic solution
        x, _ = f.lm(s, np.r_[x, np.zeros(NG - NB)], fit_rows, iters=400)
    # Mirror/equivalent solutions can fit a small joint range almost equally well.
    # Compare every near-equal candidate on a wider range; disagreement = ambiguous.
    rng = np.random.default_rng(0); qc = np.asarray(q, float).mean(axis=0)
    wide = qc + rng.uniform(-25, 25, (200, 7))
    probe = Fitter(model, wide, [[0] * 6] * len(wide)); ref = probe.predict(s, x)
    rivals = []
    ref = probe.predict(s, basic)
    for cost, s2, x2 in cands[1:]:
        if cost > max(4.0 * best_cost, best_cost + 1.0 * f.n):
            continue
        d = np.linalg.norm(probe.predict(s2, x2)[:, :3, 3] - ref[:, :3, 3], axis=1).max() * 1000
        rivals.append(float(d))
    ambiguous = bool(rivals) and max(rivals) > 1.0
    fit_err = errors(f, s, x, fit_rows); hold_err = errors(f, s, x, hold)
    ok = all(e[0] <= LIMITS['position_mm'] and e[1] <= LIMITS['angle_deg'] for e in hold_err) and not ambiguous
    return dict(schema='tcb705-kinematic-fit-v1', samples=n, fit_samples=int(fit_rows.sum()), holdout_samples=int(hold.sum()),
                sign=s.astype(int).tolist(), offset_rad=x[:7].tolist(),
                T_controller_base_from_model=_exp6(x[7:13]).tolist(), T_flange_tcp=_exp6(x[13:19]).tolist(),
                fit_max_mm=max(e[0] for e in fit_err), fit_max_deg=max(e[1] for e in fit_err),
                holdout_max_mm=max(e[0] for e in hold_err), holdout_max_deg=max(e[1] for e in hold_err),
                holdout=hold_err, limits=LIMITS, ambiguous=ambiguous, rival_max_divergence_mm=max(rivals) if rivals else 0.0,
                accepted=ok, geometry=bool(geometry),
                model_corrections=None if len(x) <= NB else dict(
                    origin_xyz_m=x[NB:NG].reshape(7, 5)[:, :3].tolist(),
                    origin_rpy_rad=np.c_[x[NB:NG].reshape(7, 5)[:, 3:], np.zeros(7)].tolist()))


def apply(config, result, contact_z_mm=None):
    if not result.get('accepted'):
        raise ValueError('标定未通过留出检验，不能写入配置')
    c = copy.deepcopy(config)
    c['sdk_mapping'] = dict(sdk_to_model_index=list(range(7)), sign=result['sign'], offset_rad=result['offset_rad'])
    c['T_controller_base_from_model'] = transform(result['T_controller_base_from_model']).tolist()
    c['T_flange_tcp'] = transform(result['T_flange_tcp']).tolist()
    c['sdk_mapping_verified'] = True
    if result.get('model_corrections'):
        c['model_corrections'] = result['model_corrections']
    else:
        c.pop('model_corrections', None)
    c['kinematic_fit'] = {k: result[k] for k in ('samples', 'holdout_max_mm', 'holdout_max_deg', 'sign')}
    return c
