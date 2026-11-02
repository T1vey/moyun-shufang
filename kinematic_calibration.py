"""Offline SO101 joint-zero / axial TCP / rigid paper-frame calibration.

No transport, motor commands, or filesystem writes. ID1 is held fixed because
its zero and paper yaw have a gauge ambiguity. Source samples must be explicit
human-confirmed contacts; encoder FK alone cannot create a measured dataset.
"""
import copy
import hashlib
import json
import math
import numpy as np

SCHEMA = 'so101-kinematic-captures-v1'
REPORT_SCHEMA = 'so101-kinematic-calibration-v1'
RAD_PER_COUNT = 2 * math.pi / 4096
LIMIT_MM = 1.5


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def calibration_fingerprint(machine):
    """Only FK inputs: a subsequent four-point paper fit does not stale this."""
    model = machine['model']
    return _hash(dict(joints=machine['joints'], model={key: model[key] for key in
        ('axes', 'offsets_m', 'limits_rad', 'tool_translation_m', 'tool_axis_local', 'units')}))


def existing_calibration_fingerprint(machine):
    """Bind reuse to encoder/TCP and measured paper geometry, not speed settings."""
    paper = machine['paper']
    return _hash(dict(fk=calibration_fingerprint(machine), paper={key:paper.get(key) for key in
        ('origin_m','u','v','normal','pen_axis','geometry_mode','xy_calibration')}))


def reuse_existing_calibration(machine):
    """Explicit user choice; retain measured data without claiming a new fit."""
    from motion import validate_machine
    from four_point_calibration import validate
    validate_machine(machine, drawing=True)
    validate(machine, require_ready=True)
    out = copy.deepcopy(machine)
    maximum = float(out['paper']['xy_calibration']['fit']['max_fit_residual_mm'])
    out.setdefault('execution', {})['existing_calibration_compatibility'] = dict(
        schema='so101-existing-calibration-v1', user_requested=True,
        calibration_fingerprint=existing_calibration_fingerprint(out),
        status='EXISTING_COMPATIBILITY', accuracy_validated=False,
        max_fit_residual_mm=maximum,
        note='User selected reuse of existing calibration; no new measurements or precision acceptance.')
    out.setdefault('new_scheme', {}).update(calibration_policy='existing_user_selected',
        calibration_required=False, physical_acceptance='PENDING')
    return out


def validate_existing_calibration(machine):
    from motion import validate_machine
    from four_point_calibration import validate
    record = machine.get('execution', {}).get('existing_calibration_compatibility') or {}
    if (record.get('schema') != 'so101-existing-calibration-v1'
            or record.get('user_requested') is not True
            or record.get('status') != 'EXISTING_COMPATIBILITY'
            or record.get('accuracy_validated') is not False):
        raise ValueError('尚未选择沿用当前标定')
    if record.get('calibration_fingerprint') != existing_calibration_fingerprint(machine):
        raise ValueError('零位、笔轴或纸面标定已改变，请重新确认要沿用的标定')
    # Existing limits, geometry integrity and contact-capture validation remain.
    validate_machine(machine, drawing=True)
    validate(machine, require_ready=True)
    return record


def _rotation(vector):
    vector = np.asarray(vector, float)
    theta = np.linalg.norm(vector)
    x, y, z = vector
    cross = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    if theta < 1e-8:
        return np.eye(3) + cross + .5 * cross @ cross
    return np.eye(3) + math.sin(theta)/theta*cross + (1-math.cos(theta))/theta**2*cross@cross


def capture_template(side_mm=100.):
    """A blank grid is intentionally not a valid measured dataset."""
    side = float(side_mm)
    if not math.isfinite(side) or side <= 0:
        raise ValueError('side_mm must be positive')
    captures = []
    for y in (-side/2, 0., side/2):
        for x in (-side/2, 0., side/2):
            for label in ('vertical', 'forward', 'backward'):
                captures.append(dict(counts={str(i): None for i in range(1, 6)},
                                     xy_mm=[x, y], pose_label=label, split='fit'))
    return dict(schema=SCHEMA, source='measured', initial_pen_length_mm=95.,
                note='Replace each null with a real stationary light-contact encoder reading. '
                     'Add separate split=validation contacts; do not copy training readings.',
                captures=captures)


def _prepare(machine, dataset):
    from planning import Model
    from motion import validate_machine
    joints = validate_machine(machine)
    if [joint['id'] for joint in joints] != [1, 2, 3, 4, 5]:
        raise ValueError('This calibration requires kinematic joint order ID1..ID5')
    if dataset.get('schema') != SCHEMA or dataset.get('source') not in ('measured', 'simulation'):
        raise ValueError('Explicit captures schema and measured/simulation provenance required')
    captures = dataset.get('captures')
    if not isinstance(captures, list):
        raise ValueError('captures must be a list')
    counts, xy, fit_mask, validation_mask = [], [], [], []
    for row in captures:
        if not isinstance(row, dict):
            raise ValueError('Each capture must be an object')
        raw = row.get('counts', {})
        if not isinstance(raw, dict):
            raise ValueError('counts must map IDs to integer readings')
        converted = {str(key): value for key, value in raw.items()}
        if set(converted) != {'1', '2', '3', '4', '5'}:
            raise ValueError('Every capture requires all five joint readings')
        values = [converted[str(j['id'])] for j in joints]
        if any(type(v) is not int or not j['min_count'] <= v <= j['max_count']
               for v, j in zip(values, joints)):
            raise ValueError('Capture counts must be real integers within configured limits')
        point = np.asarray(row.get('xy_mm'), float)
        if point.shape != (2,) or not np.isfinite(point).all():
            raise ValueError('xy_mm must contain two finite measured grid coordinates')
        split = row.get('split', 'fit')
        if split not in ('fit', 'validation'):
            raise ValueError('split must be fit or validation')
        counts.append(values); xy.append(point / 1000.)
        fit_mask.append(split == 'fit'); validation_mask.append(split == 'validation')
    fit_mask = np.asarray(fit_mask, bool); validation_mask = np.asarray(validation_mask, bool)
    if sum(fit_mask) < 27:
        raise ValueError('Need at least 27 fitting contacts: nine grid points x three postures')
    counts = np.asarray(counts, float); xy = np.asarray(xy)
    q = (counts - np.array([j['zero_count'] for j in joints])) * RAD_PER_COUNT * np.array([j['direction'] for j in joints])
    points, groups = np.unique(xy[fit_mask], axis=0, return_inverse=True)
    if len(points) < 9 or np.linalg.matrix_rank(points - points.mean(axis=0)) != 2:
        raise ValueError('Need at least nine noncollinear paper points')
    for group in range(len(points)):
        qs = q[fit_mask][groups == group]
        if len(qs) < 3 or np.ptp(qs[:, 1:4].sum(axis=1)) < math.radians(5):
            raise ValueError('Each point needs three contacts with at least 5 degrees pitch spread')
    if validation_mask.any():
        training = {tuple(c) for c in counts[fit_mask]}
        if any(tuple(c) in training for c in counts[validation_mask]):
            raise ValueError('Validation must be a fresh reading, not a copied fitting sample')
    cfg = copy.deepcopy(machine['model']); cfg['tool_translation_m'] = [0., 0., 0.]
    model = Model(cfg)
    base = np.column_stack([machine['paper'][k] for k in ('u', 'v', 'normal')]).astype(float)
    if base.shape != (3, 3) or not np.allclose(base.T @ base, np.eye(3), atol=1e-6) or np.linalg.det(base) < .99:
        raise ValueError('Initial paper frame must be a right-handed orthonormal frame')
    origin = np.asarray(machine['paper']['origin_m'], float)
    if origin.shape != (3,) or not np.isfinite(origin).all():
        raise ValueError('Initial paper origin must be finite')
    return model, q, xy, fit_mask, validation_mask, base, origin


def _stats(errors):
    if len(errors) == 0:
        return dict(status='PENDING', count=0, max_mm=None, rms_mm=None, residual_mm=[])
    norm = np.linalg.norm(errors, axis=1) * 1000
    return dict(status='PASS' if max(norm) <= LIMIT_MM else 'FAIL', count=len(norm),
                max_mm=float(max(norm)), rms_mm=float(np.sqrt(np.mean(norm**2))), residual_mm=norm.tolist())


def fit_calibration(machine, dataset, max_iterations=150):
    """Fit ten parameters, with bounded multi-start LM and integer-zero recheck.

    Zero convention: q=d*(counts-zero_count)*2*pi/4096. We fit additive dq,
    hence zero_new=zero_old-d*dq/RAD_PER_COUNT. ID1 and ID5 remain fixed.
    The axial TCP model L*tool_axis_local assumes the tip lies on the mounted
    pen axis through the model flange origin; lateral offset is not fitted.
    """
    if type(max_iterations) is not int or not 1 <= max_iterations <= 1000:
        raise ValueError('max_iterations must be an integer in [1, 1000]')
    model, q, xy, fit_mask, validation_mask, base, origin = _prepare(machine, dataset)
    length = float(dataset.get('initial_pen_length_mm', 95.)) / 1000.
    if not math.isfinite(length) or not 0 <= length <= .2:
        raise ValueError('initial_pen_length_mm must be in [0, 200]')
    # Scaled coordinates keep angular/linear unknowns similarly conditioned.
    scale = np.array([.1]*3 + [.1] + [.1]*3 + [.2]*3)
    lo = np.array([-math.radians(15)]*3 + [0.] + [-.2]*3 + [-math.radians(30)]*3) / scale
    hi = np.array([math.radians(15)]*3 + [.2] + [.2]*3 + [math.radians(30)]*3) / scale

    def residual(x, rounded=False):
        p = x * scale
        delta = p[:3].copy()
        if rounded:
            zeros = np.array([j['zero_count'] for j in machine['joints'][1:4]])
            directions = np.array([j['direction'] for j in machine['joints'][1:4]])
            target = np.rint(zeros-directions*delta/RAD_PER_COUNT)
            delta = directions*(zeros-target)*RAD_PER_COUNT
        angles = q.copy(); angles[:, 1:4] += delta
        poses = model.pose_many(angles)
        actual = poses[:, :3, 3] + poses[:, :3, :3] @ (model.tool_axis*p[3])
        rotation = _rotation(p[7:]) @ base
        expected = origin + p[4:7] + xy @ rotation[:, :2].T
        return actual - expected

    def jacobian(x):
        eps = 1e-5
        cols = []
        for i in range(10):
            dx = np.zeros(10); dx[i] = eps
            cols.append(((residual(x+dx)[fit_mask]-residual(x-dx)[fit_mask])/(2*eps)).ravel())
        return np.column_stack(cols)

    best = None
    for start_length in sorted(set((length, .05, .15))):
        x = np.zeros(10); x[3] = start_length/scale[3]
        damping = 1e-3; converged = False
        for iteration in range(int(max_iterations)):
            r = residual(x)[fit_mask].ravel(); cost = float(r@r)
            j = jacobian(x); gradient = j.T @ r
            if np.linalg.norm(gradient, np.inf) < 1e-10:
                converged = True; break
            hessian = j.T @ j
            step = np.linalg.solve(hessian+damping*np.diag(np.maximum(np.diag(hessian), 1e-9)), -gradient)
            trial = np.clip(x+step, lo, hi)
            candidate = residual(trial)[fit_mask].ravel(); new_cost = float(candidate@candidate)
            if new_cost < cost:
                x = trial; damping = max(damping/3, 1e-10)
                if abs(cost-new_cost) < 1e-14 and np.linalg.norm(step) < 1e-5:
                    converged = True; break
            else:
                damping *= 10
                if damping > 1e12:
                    break
        cost = float(np.sum(residual(x)[fit_mask]**2))
        if best is None or cost < best[0]:
            best = (cost, x.copy(), converged, iteration+1)
    _, x, converged, iterations = best
    values = x*scale; errors = residual(x); rounded_errors = residual(x, rounded=True)
    j = jacobian(x); singular = np.linalg.svd(j, compute_uv=False)
    rank = int(np.sum(singular > singular[0]*1e-7))
    condition = float(singular[0]/max(singular[-1], 1e-30))
    fit = _stats(errors[fit_mask]); validation = _stats(errors[validation_mask])
    integer_fit = _stats(rounded_errors[fit_mask]); integer_validation = _stats(rounded_errors[validation_mask])
    zeros = {str(joint['id']): int(joint['zero_count']) for joint in machine['joints']}
    correction = {}
    for joint, delta in zip(machine['joints'][1:4], values[:3]):
        value = joint['zero_count']-joint['direction']*delta/RAD_PER_COUNT
        zeros[str(joint['id'])] = int(round(float(value)))
        correction[str(joint['id'])] = float(value-joint['zero_count'])
    rotation = _rotation(values[7:]) @ base
    reasons = []
    if not converged: reasons.append('solver_not_converged')
    if rank != 10 or condition > 1e7: reasons.append('parameters_not_identifiable')
    if np.any(x-lo < 1e-5) or np.any(hi-x < 1e-5): reasons.append('parameter_at_bound')
    if any(not 0 <= count <= 4095 for count in zeros.values()): reasons.append('zero_out_of_range')
    for label, stats in [('fit', fit), ('validation', validation), ('quantized_fit', integer_fit), ('quantized_validation', integer_validation)]:
        if stats['status'] == 'FAIL': reasons.append(label+'_residual_above_1.5mm')
    report = dict(schema=REPORT_SCHEMA, status='REJECT' if reasons else 'ACCEPT', reasons=reasons,
        source=dataset['source'], applicable_to_hardware=dataset['source']=='measured' and not reasons,
        independent_validation='PENDING' if not validation_mask.any() else integer_validation['status'],
        original_calibration_fingerprint=calibration_fingerprint(machine), dataset_sha256=_hash(dataset),
        fit=fit, validation=validation, quantized_fit=integer_fit, quantized_validation=integer_validation,
        solver=dict(converged=converged, iterations=iterations, jacobian_rank=rank, scaled_condition=condition),
        parameters=dict(zero_count=zeros, zero_correction_counts=correction,
            additive_angle_correction_deg={str(i+2):float(math.degrees(v)) for i,v in enumerate(values[:3])},
            pen_length_mm=float(values[3]*1000), tool_translation_m=(model.tool_axis*values[3]).tolist(),
            paper=dict(origin_m=(origin+values[4:7]).tolist(),u=rotation[:,0].tolist(),v=rotation[:,1].tolist(),
                       normal=rotation[:,2].tolist(),pen_axis=(-rotation[:,2]).tolist())),
        limits=dict(max_residual_mm=LIMIT_MM, zero_correction_max_deg=15, pen_length_range_mm=[0,200]),
        gauge='ID1 and ID5 zero fixed; ID1 yaw is absorbed by paper pose',
        scope='Axial TCP only. Does not validate real vertical direction, mechanical play, pen pressure or motion safety.',
        physical_motion_sent=False)
    return report


def make_candidate(machine, dataset, report=None):
    """Produce a reviewed-by-user candidate; never write live machine.json."""
    report = fit_calibration(machine, dataset) if report is None else copy.deepcopy(report)
    if (report.get('schema') != REPORT_SCHEMA or report.get('status') != 'ACCEPT'
            or report.get('applicable_to_hardware') is not True or dataset.get('source') != 'measured'):
        raise ValueError('Only ACCEPT from real measured contacts can create a hardware candidate')
    if report.get('dataset_sha256') != _hash(dataset) or report.get('original_calibration_fingerprint') != calibration_fingerprint(machine):
        raise ValueError('Dataset or original FK configuration changed; refit first')
    candidate = copy.deepcopy(machine)
    p = report['parameters']
    for joint in candidate['joints']:
        joint['zero_count'] = int(p['zero_count'][str(joint['id'])])
    candidate['model']['tool_translation_m'] = list(p['tool_translation_m'])
    candidate['model']['model_status'] = 'measured_axial_tcp_joint_zero_fit'
    candidate['model']['tool_note'] = 'Axial TCP L*tool_axis_local fitted from real contact samples; lateral mount offset is not fitted.'
    paper = candidate['paper']
    for stale in ('xy_calibration', 'contact_height_calibration'):
        paper.pop(stale, None)
    paper.update(copy.deepcopy(p['paper']))
    paper.update(geometry_mode='four_point', drawing_offset_mm=[0.,0.],
                 draw_height_offset_m=0., contact_height_offset_m=0.)
    candidate.setdefault('checks', {})['kinematics'] = False
    candidate.get('execution', {}).pop('existing_calibration_compatibility', None)
    report['calibration_fingerprint'] = calibration_fingerprint(candidate)
    report['requires_four_point_recalibration'] = True
    report['requires_physical_validation'] = True
    candidate['kinematic_calibration'] = report
    return candidate


def validate_acceptance(machine):
    """Validate the measured fit only; callers still enforce normal motion gates."""
    report = machine.get('kinematic_calibration') or {}
    if (report.get('schema') != REPORT_SCHEMA or report.get('status') != 'ACCEPT'
            or report.get('source') != 'measured' or report.get('applicable_to_hardware') is not True):
        raise ValueError('糖画运动需要真实多点运动学标定 ACCEPT；仿真数据不能启用实机')
    if report.get('calibration_fingerprint') != calibration_fingerprint(machine):
        raise ValueError('关节零位或 TCP 已变化，请重新执行多点标定')
    for key in ('fit', 'quantized_fit'):
        detail = report.get(key) or {}
        maximum = detail.get('max_mm')
        if detail.get('count',0) < 27 or maximum is None or not math.isfinite(maximum) or maximum > LIMIT_MM:
            raise ValueError('多点标定残差必须全部不超过 1.5 mm')
    for key in ('validation','quantized_validation'):
        detail = report.get(key) or {}
        if detail.get('count',0) and (detail.get('status') != 'PASS' or detail.get('max_mm', math.inf) > LIMIT_MM):
            raise ValueError('独立验证点残差超过 1.5 mm，请重新标定')
    return report


def fit_pen_axis(machine, captures, world_axis=(0., 0., -1.)):
    """Estimate local pen axis from >=3 externally confirmed upright postures.

    Caller must confirm a level base and real vertical pen with a level; the
    encoded orientations by themselves do not establish gravity direction.
    This returns a candidate only and intentionally does not change a machine.
    """
    from planning import Model
    from motion import angles_from_counts
    if not isinstance(captures, list) or len(captures)<3:
        raise ValueError('At least three independently level-confirmed poses required')
    axis=np.asarray(world_axis,float)
    if axis.shape!=(3,) or not np.isfinite(axis).all() or not np.isclose(np.linalg.norm(axis),1.,atol=1e-8):
        raise ValueError('world_axis must be a finite unit vector')
    model=Model(machine['model']); rotations=[]; estimates=[]; readings=set()
    for capture in captures:
        if capture.get('source')!='measured' or capture.get('externally_vertical_confirmed') is not True:
            raise ValueError('Each axis capture needs a real external vertical confirmation')
        counts={int(k):v for k,v in capture['counts'].items()}
        if set(counts)!={j['id'] for j in machine['joints']} or any(type(counts[j['id']]) is not int or not j['min_count']<=counts[j['id']]<=j['max_count'] for j in machine['joints']):
            raise ValueError('Axis capture encoder readings incomplete or out of bounds')
        reading=tuple(counts[j['id']] for j in machine['joints'])
        if reading in readings:raise ValueError('Axis fitting needs distinct confirmed postures')
        readings.add(reading)
        rotation=model.pose(angles_from_counts(machine,counts))[:3,:3]
        rotations.append(rotation);estimates.append(rotation.T@axis)
    result=np.mean(estimates,axis=0)
    if np.linalg.norm(result)<.1:raise ValueError('Inconsistent confirmed vertical poses')
    result/=np.linalg.norm(result)
    residual=[float(math.degrees(math.acos(float(np.clip((r@result)@axis,-1.,1.))))) for r in rotations]
    return dict(status='ACCEPT' if max(residual)<=.5 else 'REJECT',tool_axis_local=result.tolist(),
                residual_deg=residual,max_residual_deg=max(residual),limit_deg=.5,
                physical_motion_sent=False,requires_new_kinematic_calibration=True)


def assert_sugar_calibration(machine, require_four_point=False):
    try:
        report = validate_acceptance(machine)
    except ValueError:
        if machine.get('execution', {}).get('existing_calibration_compatibility'):
            return validate_existing_calibration(machine)
        raise
    from four_point_calibration import validate
    validate(machine, require_ready=require_four_point)
    fit = ((machine.get('paper') or {}).get('xy_calibration') or {}).get('fit') or {}
    value = fit.get('max_fit_residual_mm', 0.)
    if not math.isfinite(float(value)) or float(value) > 5.:
        raise ValueError('糖画模式禁止四点残差超过 5 mm，不能强制应用')
    return report
