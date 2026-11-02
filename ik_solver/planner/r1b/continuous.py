"""C1 cubic / C2 quintic interpolation with bounded derivatives and FK probes."""
import math
import numpy as np
from .path import axis_parameters, interpolate_axes
from .geometry import measure_segments


def coefficients(a, b, va, vb, duration):
    delta = b-a
    return np.array([a, va*duration, 3*delta-(2*va+vb)*duration,
                     -2*delta+(va+vb)*duration])


def evaluate(c, u, duration):
    if len(c) == 6:
        return (c[0]+u*(c[1]+u*(c[2]+u*(c[3]+u*(c[4]+u*c[5])))),
                (c[1]+u*(2*c[2]+u*(3*c[3]+u*(4*c[4]+u*5*c[5]))))/duration,
                (2*c[2]+u*(6*c[3]+u*(12*c[4]+u*20*c[5])))/duration**2)
    return (c[0]+u*(c[1]+u*(c[2]+u*c[3])),
            (c[1]+u*(2*c[2]+u*3*c[3]))/duration,
            (2*c[2]+u*6*c[3])/duration**2)


def derivative_bounds(c, duration):
    if len(c) == 6:
        v = np.arange(1, 6)[:, None]*c[1:]/duration
        a = np.arange(1, 5)[:, None]*v[1:]/duration
        return float(np.max(np.abs(_HULL4 @ v))), float(np.max(np.abs(_HULL3 @ a)))
    peak_v = max(np.max(np.abs(evaluate(c, u, duration)[1])) for u in (0., 1.))
    for axis in range(5):
        if abs(c[3, axis]) > 1e-15:
            u = -c[2, axis]/(3*c[3, axis])
            if 0 < u < 1:
                peak_v = max(peak_v, abs(evaluate(c, u, duration)[1][axis]))
    peak_a = max(np.max(np.abs(evaluate(c, u, duration)[2])) for u in (0., 1.))
    return float(peak_v), float(peak_a)


def quintic_coefficients(a, b, va, vb, duration):
    """Shared velocities and zero acceleration at both ends give global C2.

    Monotone endpoint slopes <= each secant keep all six Bezier controls
    inside the endpoint box, so the polynomial cannot overshoot joint limits.
    """
    d, x, y = b-a, va*duration, vb*duration
    return np.array([a, x, np.zeros_like(a), 10*d-6*x-4*y, -15*d+8*x+7*y, 6*d-3*x-3*y])


def _subdivided_hull(degree):
    # Power -> Bernstein -> four de Casteljau subintervals. The convex hull
    # bounds the ENTIRE derivative curve, not just sampled extrema.
    matrix = np.array([[math.comb(i,k)/math.comb(degree,k) if k <= i else 0.
                        for k in range(degree+1)] for i in range(degree+1)])
    blocks = [matrix]
    for _ in range(2):
        halves = []
        for block in blocks:
            levels = [block]
            for _ in range(degree):
                levels.append((levels[-1][:-1]+levels[-1][1:])*.5)
            halves.extend([np.array([v[0] for v in levels]), np.array([v[-1] for v in levels[::-1]])])
        blocks = halves
    return np.vstack(blocks)


_HULL4, _HULL3 = _subdivided_hull(4), _subdivided_hull(3)


def interpolate(model, joints, targets, cfg, cancel=None):
    """Stop at pen transitions and sharp corners; carry velocity through smooth DRAW knots.

    Joint components use monotone slopes, so each segment stays within its joint
    endpoint box. Velocity/acceleration bounds are analytic; FK tracking is sampled.
    """
    if cfg.get('motion_profile') == 'continuous_quintic_vaj':
        from .smooth import interpolate as smooth_interpolate
        return smooth_interpolate(model, joints, targets, cfg, cancel)
    q = np.asarray(joints, dtype=float)
    profile = cfg.get('motion_profile', 'continuous_cubic')
    make = quintic_coefficients if profile == 'continuous_quintic' else coefficients
    delta = np.diff(q, axis=0)
    sizes = np.max(np.abs(delta), axis=1)
    h = np.maximum(cfg['min_segment_s'], np.maximum(
        1.5*sizes/cfg['max_velocity_rad_s'],
        np.sqrt(6*sizes/cfg['max_acceleration_rad_s2'])))
    slopes = np.zeros_like(q)
    for i in range(1, len(q)-1):
        a, b, c = targets[i-1:i+2]
        if b['phase'] != 'DRAW' or c['phase'] != 'DRAW' or b['stroke'] != c['stroke']:
            continue
        d1 = np.asarray(b['position'])-a['position']
        d2 = np.asarray(c['position'])-b['position']
        norm = np.linalg.norm(d1)*np.linalg.norm(d2)
        if norm < 1e-18 or np.dot(d1, d2)/norm < math.cos(math.radians(45)):
            continue
        v1, v2 = delta[i-1]/h[i-1], delta[i]/h[i]
        same = v1*v2 > 0
        slopes[i, same] = np.sign(v1[same])*np.minimum(np.abs(v1[same]), np.abs(v2[same]))
    if cancel and cancel():
        raise ValueError('ABORT')
    # Identical polynomial formulas, evaluated for all knots together.
    coeffs = np.moveaxis(make(q[:-1],q[1:],slopes[:-1],slopes[1:],h[:,None]),0,1)
    if profile == 'continuous_quintic':
        v=np.arange(1,6)[None,:,None]*coeffs[:,1:]/h[:,None,None]
        acceleration=np.arange(1,5)[None,:,None]*v[:,1:]/h[:,None,None]
        velocities=np.max(np.abs(_HULL4@v),axis=(1,2))
        accelerations=np.max(np.abs(_HULL3@acceleration),axis=(1,2))
    else:
        bounds=np.asarray([derivative_bounds(c,t) for c,t in zip(coeffs,h)])
        velocities,accelerations=bounds[:,0],bounds[:,1]
    dilation=max(1.,float(np.max(velocities/cfg['max_velocity_rad_s'])),
                 math.sqrt(float(np.max(accelerations/cfg['max_acceleration_rad_s2']))))
    times=h*dilation
    counts=[max(2,math.ceil(t/cfg['command_period_s'])) for t in times]
    if sum(counts)>cfg['max_commands']:
        raise ValueError('COMMAND_BUDGET')
    elapsed=np.concatenate(([0.],np.cumsum(times)))
    points=np.asarray([t['position'] for t in targets])
    deltas=np.diff(points,axis=0)
    axes=[axis_parameters(a['axis'],b['axis']) for a,b in zip(targets,targets[1:])]
    axis_starts=np.asarray([a[0] for a in axes]);axis_ends=np.asarray([a[1] for a in axes])
    angles=np.asarray([a[2] for a in axes])
    draw=np.asarray([t['phase']=='DRAW' for t in targets[1:]])
    commands=[]; maxima=np.zeros(5); geometry_samples=geometry_batches=0
    pending=[]; pending_size=0; grids={}; limit=1024
    probes=np.linspace(0,1,17)

    def flush():
        nonlocal pending_size,geometry_samples,geometry_batches
        if not pending:return
        if cancel and cancel():raise ValueError('ABORT')
        indexes=np.concatenate([np.full(len(us),i,dtype=int) for i,us,_ in pending])
        us=np.concatenate([us for _,us,_ in pending])
        issued=np.concatenate([mask for _,_,mask in pending])
        cs=np.moveaxis(coeffs[indexes],1,0)
        positions,vs,accs=evaluate(cs,us[:,None],times[indexes,None])
        emitted=positions[issued]
        if (not np.isfinite(emitted).all() or np.any(emitted<model.limits[:,0])
                or np.any(emitted>model.limits[:,1])):
            raise ValueError('INTERPOLATION_ERROR')
        starts=points[indexes];dp=deltas[indexes]
        desireds=starts+us[:,None]*dp
        axes=interpolate_axes(axis_starts[indexes],axis_ends[indexes],angles[indexes],us)
        path,requested,tilt=measure_segments(model,positions,starts,dp,desireds,axes)
        maxima[:3]=np.maximum(maxima[:3],(path.max(),requested.max(),tilt.max()))
        drawing=draw[indexes]
        if drawing.any():maxima[3:]=np.maximum(maxima[3:],(path[drawing].max(),tilt[drawing].max()))
        geometry_samples+=len(us);geometry_batches+=1
        # Convert rows together, keeping every original issued sample/order.
        stamp=(elapsed[indexes]+us*times[indexes])[issued].tolist()
        rows=zip(indexes[issued],stamp,emitted.tolist(),vs[issued].tolist(),accs[issued].tolist(),
                 desireds[issued].tolist(),axes[issued].tolist())
        for i,t,position,velocity,acceleration,desired,axis in rows:
            b=targets[i+1]
            commands.append(dict(t_s=t,q_rad=position,velocity_rad_s=velocity,
                acceleration_rad_s2=acceleration,tip_target_m=desired,axis_target=axis,
                phase=b['phase'],stroke=b['stroke'],pen_down=b['phase']=='DRAW',physical_authorized=False))
        pending.clear();pending_size=0

    for i,n in enumerate(counts):
        if cancel and cancel():raise ValueError('ABORT')
        grid=grids.get(n)
        if grid is None:
            issued=np.linspace(0,1,n+1)
            checked=np.unique(np.concatenate((issued,probes)))
            mask=np.zeros(len(checked),dtype=bool)
            mask[np.searchsorted(checked,issued[1:])]=True
            grid=checked,mask
            if n<=256 and len(grids)<128:grids[n]=grid
        checked,mask=grid
        start=0
        while start<len(checked):
            end=min(len(checked),start+limit-pending_size)
            pending.append((i,checked[start:end],mask[start:end]));pending_size+=end-start
            start=end
            if pending_size==limit:flush()
    flush()
    if len(times)>1:
        left=evaluate(np.moveaxis(coeffs[:-1],1,0),1.,times[:-1,None])[2]
        right=evaluate(np.moveaxis(coeffs[1:],1,0),0.,times[1:,None])[2]
        jump=float(np.max(np.abs(left-right)))
    else:jump=0.
    return commands, dict(duration_s=float(elapsed[-1]), commands=len(commands),
            motion_profile=profile, moving_draw_knots=int(np.sum(np.any(np.abs(slopes)>1e-12, axis=1))),
            max_knot_acceleration_jump_rad_s2=jump,
            derivative_check='subdivided Bernstein hull' if len(coeffs[0]) == 6 else 'analytic extrema',
            peak_velocity_rad_s=float(velocities.max())/dilation,
            peak_acceleration_rad_s2=float(accelerations.max())/dilation**2,
            max_interpolation_error_m=float(maxima[0]), max_tilt_rad=float(maxima[2]),
            max_requested_sample_error_m=float(maxima[1]),
            max_draw_path_error_m=float(maxima[3]),max_draw_tilt_rad=float(maxima[4]),
            geometry_samples=geometry_samples,
            geometry_fk_batches=geometry_batches,geometry_batch_limit=limit,
            geometry_check='batch FK: all command samples plus 17 probes per segment',
            geometry_scope='nominal model; path error is distance to intended segment, not physical pen measurement')
