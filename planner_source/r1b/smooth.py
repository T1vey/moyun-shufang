"""C2 motion blocks, exact jerk checks, bounded retiming and fixed-time samples."""
import math
import time
import numpy as np
from r1a.model import Model
_STANDARD_POSE_MANY = Model.pose_many
try:
    from native.geometry import geometry_rows as _native_geometry_rows
except ImportError:
    _native_geometry_rows = None
from .continuous import quintic_coefficients, evaluate
from .path import axis_parameters, interpolate_axes
from .retiming import (MOTION_VERSION, PROFILE, normalize_motion_limits,
                       quintic_full, derivative_bounds_many, legal_segments,
                       time_ratios, minimum_jerk_nodes, stop_blocks)


def _old_slopes(q, times, targets):
    # Carry velocity within one phase. Rest at every phase/stroke boundary;
    # extra endpoint pauses must not become stops at every millimetre in air.
    slopes = np.zeros_like(q)
    delta = np.diff(q, axis=0)
    for i in range(1, len(q)-1):
        a, b, c = targets[i-1:i+2]
        if (b['phase'] not in ('DRAW','LIFT','LOWER','TRAVEL','APPROACH')
                or b['phase']!=c['phase'] or b['stroke'] != c['stroke']):
            continue
        d1, d2 = np.asarray(b['position'])-a['position'], np.asarray(c['position'])-b['position']
        norm = np.linalg.norm(d1)*np.linalg.norm(d2)
        if norm < 1e-18 or float(d1@d2)/norm < math.cos(math.radians(45)):
            continue
        v1, v2 = delta[i-1]/times[i-1], delta[i]/times[i]
        same = v1*v2 > 0
        slopes[i, same] = np.sign(v1[same])*np.minimum(np.abs(v1[same]), np.abs(v2[same]))
    return slopes


def _path_data(targets):
    points = np.asarray([t['position'] for t in targets])
    axes = [axis_parameters(a['axis'], b['axis']) for a, b in zip(targets, targets[1:])]
    return (points[:-1], np.diff(points, axis=0), np.asarray([a[0] for a in axes]),
            np.asarray([a[1] for a in axes]), np.asarray([a[2] for a in axes]))


def _measure_rows(model, coeffs, times, path, indexes, us):
    p0, delta, a0, a1, angles = path
    joints, velocity, acceleration = evaluate(np.moveaxis(coeffs[indexes], 1, 0),
                                             us[:, None], times[indexes, None])
    desired = p0[indexes]+us[:, None]*delta[indexes]
    axes = interpolate_axes(a0[indexes], a1[indexes], angles[indexes], us)
    # Preserve the original authoritative FP64 Horner samples and all probes.
    # An overridden pose_many (test oracle/custom model) must still be honored.
    if (_native_geometry_rows is not None and type(model) is Model
            and Model.pose_many is _STANDARD_POSE_MANY and 'pose_many' not in model.__dict__):
        measured = _native_geometry_rows(model, joints, p0[indexes], delta[indexes], desired, axes)
        if measured is not None:
            actual, distance, requested, tilt = measured
            return joints, velocity, acceleration, desired, axes, actual, distance, requested, tilt
    poses = model.pose_many(joints)
    actual = poses[:, :3, 3]
    dp, starts = delta[indexes], p0[indexes]
    squared = np.einsum('ij,ij->i', dp, dp)
    fraction = np.zeros(len(indexes)); valid = squared > 1e-20
    fraction[valid] = np.clip(np.einsum('ij,ij->i', actual[valid]-starts[valid], dp[valid])/squared[valid], 0, 1)
    distance = np.linalg.norm(actual-(starts+fraction[:, None]*dp), axis=1)
    orientation = poses[:, :3, :3] @ model.tool_axis
    tilt = np.arctan2(np.linalg.norm(np.cross(axes, orientation), axis=1),
                      np.einsum('ij,ij->i', axes, orientation))
    requested = np.linalg.norm(actual-desired, axis=1)
    return joints, velocity, acceleration, desired, axes, actual, distance, requested, tilt


def _probe_curve(model, coeffs, times, path, cfg, cancel=None, subset=None):
    count = len(coeffs)
    segments = np.arange(count) if subset is None else np.asarray(subset, dtype=int)
    errors = np.zeros((count, 3)); probes = np.linspace(0, 1, 17)
    total = len(segments)*len(probes); batches = 0
    for start in range(0, total, 1024):
        if cancel and cancel():
            raise ValueError('ABORT')
        rows = np.arange(start, min(total, start+1024))
        index, u = segments[rows//len(probes)], probes[rows % len(probes)]
        values = _measure_rows(model, coeffs, times, path, index, u)
        np.maximum.at(errors[:, 0], index, values[6])
        np.maximum.at(errors[:, 1], index, values[7])
        np.maximum.at(errors[:, 2], index, values[8])
        if cfg.get('_joint_air') is not None:
            air = cfg['_joint_air'][index]
            if air.any():
                clearance = (values[5][air]-cfg['air_plane_origin_m'])@cfg['air_plane_normal']
                if np.any(clearance < cfg['air_min_clearance_m']-1e-9):
                    raise ValueError('AIR_CLEARANCE_ERROR')
        batches += 1
    bad = ~legal_segments(coeffs, model.limits)
    # Every phase is checked; free node accelerations must not bend lifts/travel.
    geometry_bad = errors[:, 0] > cfg['tracking_error_m']
    if cfg.get('_joint_air') is not None:
        geometry_bad &= ~cfg['_joint_air']
    bad |= geometry_bad
    bad |= errors[:, 2] > cfg['tilt_tolerance_rad']
    return bad, errors, total, batches


def interpolate(model, joints, targets, cfg, cancel=None):
    started = time.perf_counter()
    q = np.asarray(joints, dtype=float)
    if q.shape != (len(targets), 5) or len(q) < 2 or not np.isfinite(q).all():
        raise ValueError('invalid smooth joint knots')
    limits = normalize_motion_limits(cfg)
    reserve = float(cfg.get('runtime_reserve_ratio', .9))
    if not math.isfinite(reserve) or not .1 <= reserve <= 1.:
        raise ValueError('invalid runtime_reserve_ratio')
    limits = tuple(x*reserve for x in limits)
    vm, am, jm = limits
    periods = float(cfg['command_period_s'])
    passes = cfg.get('retime_max_passes', 4)
    if type(passes) is not int or not 1 <= passes <= 4:
        raise ValueError('invalid retime_max_passes')
    blocks, reasons = stop_blocks(targets, cfg)
    segment_blocks = np.empty(len(q)-1, dtype=int)
    for number, (start, end) in enumerate(blocks):
        segment_blocks[start:end] = number
    for i, target in enumerate(targets):
        target.update(motion_block_id=int(segment_blocks[max(0, i-1)]),
                      must_stop=i in reasons, stop_reason=reasons.get(i))
    delta = np.abs(np.diff(q, axis=0))
    times = np.maximum(float(cfg['min_segment_s']), np.maximum(
        np.max(1.5*delta/vm, axis=1), np.sqrt(np.max(6*delta/am, axis=1))))
    if cfg.get('motion_node_policy') == 'arc_length':
        from .sugar import block_times
        times = block_times(q, targets, blocks, cfg, vm)
    path = _path_data(targets)
    air_segments = np.asarray([bool(t.get('joint_space_air')) for t in targets[1:]])
    if air_segments.any():
        cfg = dict(cfg, _joint_air=air_segments)
    blend = np.ones(len(blocks)); failures = {}; fk_samples = fk_batches = 0
    coefficients = None; errors = None
    for attempt in range(passes):
        if cancel and cancel():
            raise ValueError('ABORT')
        v, a = np.zeros_like(q), np.zeros_like(q)
        baseline = _old_slopes(q, times, targets)
        if cfg.get('motion_node_policy') == 'arc_length':
            from .sugar import node_velocities, vertical_derivatives
            baseline = node_velocities(q, times, blocks)
            baseline, a = vertical_derivatives(q, times, targets, blocks, baseline, a)
        if cfg.get('motion_node_policy')=='classic_draw':
            # v0.6.1 carries velocity only inside DRAW. Air/lift/lower
            # nodes rest; their Cartesian phases never blend together.
            baseline[np.asarray([t['phase']!='DRAW' for t in targets])]=0.
        for number, (start, end) in enumerate(blocks):
            # Explicit rest at every block boundary, including the LOWER endpoint.
            baseline[start] = baseline[end] = 0.
            if cfg.get('motion_node_policy') in ('secant','classic_draw','arc_length'):
                v[start:end+1] = baseline[start:end+1]
                continue
            if blend[number] == 0:
                continue
            try:
                vv, aa = minimum_jerk_nodes(q[start:end+1], times[start:end], cancel)
                v[start:end+1], a[start:end+1] = vv, aa
            except ValueError as exc:
                if str(exc) == 'ABORT':
                    raise
                blend[number] = 0.; failures[number] = str(exc)
        weights = np.ones(len(q))
        for number, (start, end) in enumerate(blocks):
            weights[start:end+1] = blend[number]
        node_v, node_a = v, a
        v = baseline+weights[:, None]*(node_v-baseline)
        a = node_a*weights[:, None]
        coefficients = np.moveaxis(quintic_full(q[:-1], q[1:], v[:-1], v[1:],
            a[:-1], a[1:], times[:, None]), 0, 1)
        bad, errors, samples, batches = _probe_curve(model, coefficients, times, path, cfg, cancel)
        fk_samples += samples; fk_batches += batches
        # Only recheck failing blocks; bounded attempts, no whole-picture FK loop.
        for factor in (.5, .25, 0.):
            failing = np.unique(segment_blocks[bad])
            if not len(failing):
                break
            selected = []
            for number in failing:
                start, end = blocks[number]
                blend[number] = min(blend[number], factor)
                failures[int(number)] = 'geometry_or_joint_hull'
                weights[start:end+1] = blend[number]
                selected.extend(range(start, end))
            vv = baseline+weights[:, None]*(node_v-baseline)
            aa = node_a*weights[:, None]
            for number in failing:
                start, end = blocks[number]
                vv[start] = vv[end] = 0.; aa[start] = aa[end] = 0.
                if factor == 0.:
                    # The baseline itself can leave the Cartesian line.
                    # Final fallback must actually rest at every knot in this
                    # failing block, not retain the same baseline velocities.
                    vv[start:end+1] = 0.; aa[start:end+1] = 0.
                    failures[int(number)] = 'geometry_rest_fallback'
            regenerated = np.moveaxis(quintic_full(q[:-1], q[1:], vv[:-1], vv[1:],
                aa[:-1], aa[1:], times[:, None]), 0, 1)
            coefficients[selected] = regenerated[selected]
            current, measured, samples, batches = _probe_curve(model, coefficients, times, path, cfg, cancel, selected)
            bad[selected], errors[selected] = current[selected], measured[selected]
            fk_samples += samples; fk_batches += batches
        if bad.any():
            raise ValueError('SMOOTH_GEOMETRY_ERROR')
        ratios = time_ratios(coefficients, times, limits)
        if ratios.max() <= 1.+1e-10:
            break
        if attempt+1 < passes:
            propagated = ratios.copy()
            for start, end in blocks:
                if end-start > 1:
                    propagated[start+1:end] = np.maximum(propagated[start+1:end], np.sqrt(ratios[start:end-1]))
                    propagated[start:end-1] = np.maximum(propagated[start:end-1], np.sqrt(ratios[start+1:end]))
            times *= propagated*(1.+1e-6)
    # Final block-wise dilation is exact: keep q(u) intact and all shared
    # derivatives coherent. It also places every rest boundary on the grid.
    ratios = time_ratios(coefficients, times, limits)
    block_cycles = []
    for start, end in blocks:
        ratio = max(1., float(ratios[start:end].max()))
        length = float(times[start:end].sum())
        cycles = max(2, int(math.ceil(length*ratio/periods)))
        phase=targets[start+1]['phase']
        if phase in ('LIFT','LOWER'):
            minimum=float(cfg.get('min_'+phase.lower()+'_motion_s',.6 if phase=='LIFT' else .4))
            if not math.isfinite(minimum) or minimum<0:raise ValueError('Invalid pen motion duration')
            cycles=max(cycles,int(math.ceil(minimum/periods)))
        block_cycles.append(cycles)
        times[start:end] *= cycles*periods/length
    total_cycles = sum(block_cycles)
    if total_cycles > cfg['max_commands']:
        raise ValueError('COMMAND_BUDGET')
    peak_v, peak_a, peak_j = derivative_bounds_many(coefficients, times)
    if (np.any(peak_v > vm*(1+1e-9)) or np.any(peak_a > am*(1+1e-9))
            or np.any(peak_j > jm*(1+1e-9))):
        raise ValueError('JERK_LIMIT')
    elapsed = np.concatenate(([0.], np.cumsum(times)))
    end_cycles = np.cumsum(block_cycles)
    # Fix accumulated floating error at exact stop boundaries before searching.
    for (_, end), cycle in zip(blocks, end_cycles):
        elapsed[end] = cycle*periods
    samples = np.arange(1, total_cycles+1, dtype=float)*periods
    indexes = np.clip(np.searchsorted(elapsed, samples, side='left')-1, 0, len(times)-1)
    us = np.clip((samples-elapsed[indexes])/times[indexes], 0, 1)
    commands = []; maximum = np.max(errors, axis=0)
    maximum[0] = float(errors[~air_segments,0].max()) if (~air_segments).any() else 0.
    air_deviation = float(errors[air_segments,0].max()) if air_segments.any() else 0.
    draw = np.asarray([t['phase'] == 'DRAW' for t in targets[1:]])
    draw_error = float(errors[draw, 0].max()) if draw.any() else 0.
    draw_tilt = float(errors[draw, 2].max()) if draw.any() else 0.
    for start in range(0, total_cycles, 1024):
        if cancel and cancel():
            raise ValueError('ABORT')
        end = min(total_cycles, start+1024)
        idx, u = indexes[start:end], us[start:end]
        rows = _measure_rows(model, coefficients, times, path, idx, u)
        joints, velocity, acceleration, desired, axes, reference, dist, requested, tilt = rows
        if (np.any(joints < model.limits[:, 0]) or np.any(joints > model.limits[:, 1])
                or np.any(dist[~air_segments[idx]] > cfg['tracking_error_m']) or np.any(tilt > cfg['tilt_tolerance_rad'])):
            raise ValueError('SMOOTH_GEOMETRY_ERROR')
        if air_segments[idx].any():
            clearance = (reference[air_segments[idx]]-cfg['air_plane_origin_m'])@cfg['air_plane_normal']
            if np.any(clearance < cfg['air_min_clearance_m']-1e-9):
                raise ValueError('AIR_CLEARANCE_ERROR')
        path_error=float(dist[~air_segments[idx]].max()) if (~air_segments[idx]).any() else 0.
        if air_segments[idx].any():air_deviation=max(air_deviation,float(dist[air_segments[idx]].max()))
        maximum = np.maximum(maximum, (path_error, requested.max(), tilt.max()))
        drawing = draw[idx]
        if drawing.any():
            draw_error = max(draw_error, float(dist[drawing].max()))
            draw_tilt = max(draw_tilt, float(tilt[drawing].max()))
        j = (6*coefficients[idx, 3]+24*coefficients[idx, 4]*u[:, None]
             +60*coefficients[idx, 5]*u[:, None]**2)/times[idx, None]**3
        for local, i in enumerate(idx):
            target = targets[i+1]; block = int(segment_blocks[i])
            sequence = start+local+1
            commands.append(dict(t_s=float(samples[start+local]), q_rad=joints[local].tolist(),
                velocity_rad_s=velocity[local].tolist(), acceleration_rad_s2=acceleration[local].tolist(),
                jerk_rad_s3=j[local].tolist(), tip_target_m=desired[local].tolist(),
                tip_reference_m=reference[local].tolist(), axis_target=axes[local].tolist(),
                phase=target['phase'], stroke=target['stroke'], pen_down=target['phase'] == 'DRAW',
                motion_block_id=block, path_segment_index=int(i),
                source_segment_id=target.get('source_segment_id'), hard_stop=sequence == int(end_cycles[block]),
                physical_authorized=False))
        fk_samples += end-start; fk_batches += 1
    left_v = (coefficients[:-1, 1]+2*coefficients[:-1, 2]+3*coefficients[:-1, 3]
              +4*coefficients[:-1, 4]+5*coefficients[:-1, 5])/times[:-1, None]
    right_v = coefficients[1:, 1]/times[1:, None]
    left_a = (2*coefficients[:-1, 2]+6*coefficients[:-1, 3]+12*coefficients[:-1, 4]
              +20*coefficients[:-1, 5])/times[:-1, None]**2
    right_a = 2*coefficients[1:, 2]/times[1:, None]**2
    left_j = (6*coefficients[:-1, 3]+24*coefficients[:-1, 4]+60*coefficients[:-1, 5])/times[:-1, None]**3
    right_j = 6*coefficients[1:, 3]/times[1:, None]**3
    stop_nodes = sorted(reasons)
    descriptors = [dict(coeffs=coefficient.tolist(), start_time_s=float(elapsed[i]),
        duration_s=float(duration), motion_block_id=int(segment_blocks[i]),
        phase=targets[i+1]['phase'], stroke=targets[i+1]['stroke'],
        source_segment_id=targets[i+1].get('source_segment_id'),
        segment_start_m=path[0][i].tolist(), segment_end_m=targets[i+1]['position'],
        axis_start=path[2][i].tolist(), axis_end=path[3][i].tolist(),
        hard_stop_end=i+1 in reasons, stop_reason=reasons.get(i+1))
        for i, (coefficient, duration) in enumerate(zip(coefficients, times))]
    for i in np.flatnonzero(air_segments):
        descriptors[i].update(joint_space_air=True,air_plane_origin_m=cfg['air_plane_origin_m'],
            air_plane_normal=cfg['air_plane_normal'],air_min_clearance_m=cfg['air_min_clearance_m'])
    actual_v = np.vstack((coefficients[0, 1]/times[0], left_v,
                          (coefficients[-1, 1]+2*coefficients[-1, 2]+3*coefficients[-1, 3]
                           +4*coefficients[-1, 4]+5*coefficients[-1, 5])/times[-1]))
    internal = np.ones(len(q), dtype=bool); internal[stop_nodes] = False
    metrics = dict(duration_s=float(samples[-1]), commands=len(commands), motion_profile=PROFILE,
        motion_algorithm_version=MOTION_VERSION, command_period_s=periods, runtime_reserve_ratio=reserve,
        peak_velocity_rad_s=float(peak_v.max()), peak_acceleration_rad_s2=float(peak_a.max()),
        peak_jerk_rad_s3=float(peak_j.max()), peak_velocity_by_joint=peak_v.max(axis=0).tolist(),
        peak_acceleration_by_joint=peak_a.max(axis=0).tolist(), peak_jerk_by_joint=peak_j.max(axis=0).tolist(),
        moving_draw_knots=int(sum(targets[i]['phase'] == 'DRAW' and np.any(np.abs(actual_v[i]) > 1e-10)
                                  for i in range(1, len(q)-1))),
        hard_stop_knots=len(stop_nodes), motion_blocks=len(blocks),
        avoidable_stop_knots=int(np.sum(internal & ~np.any(np.abs(actual_v) > 1e-10, axis=1))),
        max_knot_velocity_jump_rad_s=float(np.max(np.abs(left_v-right_v))) if len(left_v) else 0.,
        max_knot_acceleration_jump_rad_s2=float(np.max(np.abs(left_a-right_a))) if len(left_a) else 0.,
        max_knot_jerk_jump_rad_s3=float(np.max(np.abs(left_j-right_j))) if len(left_j) else 0.,
        max_interpolation_error_m=float(maximum[0]), max_requested_sample_error_m=float(maximum[1]),
        max_air_chord_deviation_m=air_deviation,air_motion_segments=int(air_segments.sum()),
        max_tilt_rad=float(maximum[2]), max_draw_path_error_m=draw_error, max_draw_tilt_rad=draw_tilt,
        derivative_check='subdivided Bernstein v/a hulls; exact quadratic jerk extrema',
        joint_limit_check='whole-curve subdivided Bernstein hull', retime_passes=attempt+1,
        fallback_blocks=int(np.sum(blend == 0)), blended_blocks=int(np.sum(blend < 1)),
        fallback_reasons={str(k): v for k, v in failures.items()},
        geometry_samples=fk_samples, geometry_fk_batches=fk_batches, geometry_batch_limit=1024,
        geometry_check='all issued fixed-period samples; 17 probes per segment; all phases',
        geometry_scope='nominal model; not physical pen measurement',
        retiming_s=time.perf_counter()-started, _trajectory_segments=descriptors)
    return commands, metrics
