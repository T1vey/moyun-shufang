"""Use the team's R1b planner in source checkout or release bundle."""
import copy
import json
from pathlib import Path
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parent
# Layout adapter: this module ships both as the package root (release bundle:
# planning.py next to planner_source/) and inside app/ in the source checkout
# (app/planning.py with planner_source one level up).  Keep the same planner in
# both layouts instead of hard-coding one of them.
_CANDIDATES = (
    ROOT / "planner_source",                    # release: <root>/planning.py
    ROOT.parent / "planner_source",             # checkout: <proj>/app/planning.py
    ROOT / "so101_r1ab" / "source",             # release, r1ab naming
    ROOT.parent / "so101_r1ab" / "source",      # checkout, r1ab naming
    ROOT / "ik_solver" / "planner",             # legacy checkout layout
    ROOT.parent / "ik_solver" / "planner",      # legacy checkout layout
)
SOURCE = next((c for c in _CANDIDATES if (c / "r1a").is_dir()), _CANDIDATES[0])
sys.path.insert(0, str(SOURCE))
from r1a.model import Model
from r1a.native import python_f32_inputs
from r1b.fixtures import drawings
from r1b.planner import plan
from r1b.cli import preview


def load(name):
    return json.loads((SOURCE / "config" / name).read_text(encoding="utf-8"))


def nominal():
    model = Model(load("nominal_so101.json"))
    fixture = drawings(model)[0]
    return model, dict(origin_m=fixture["plane_origin_m"], u=[1, 0, 0], v=[0, 1, 0],
                       normal=[0, 0, 1], pen_axis=fixture["pen_axis"]), fixture["q0"]


def home_pose(model, paper, q0, height_offset_m=0.0, backend=None):
    """起始姿态沿纸面法向抬高 height_offset_m 后的关节角。

    用与规划器相同的 IK 求解，笔轴对准当前标定纸面的法向。
    即使高度偏移为 0，也修正旧初始姿态的笔杆倾角。
    """
    q0 = np.asarray(q0, dtype=float)
    lift = float(height_offset_m or 0.0)
    if not np.isfinite(lift):
        raise ValueError("home_height_offset_m 必须是有限数")
    from r1a.solve import solve
    from drawing_geometry import paper_frame
    frame = paper_frame(paper)
    normal = frame['normal']
    pose = model.pose(q0)
    target = pose[:3, 3] + normal*lift
    axis = frame['pen_axis']
    if lift == 0.0 and np.allclose(pose[:3,:3]@model.tool_axis,axis,atol=1e-10,rtol=0.):
        return q0
    if hasattr(backend, 'solve_target'):
        r = backend.solve_target(model, target, axis, q0, load('contract.json'))
    else:
        r = solve(model, target, axis, q0, load("contract.json"), backend=backend)
    if r.status != "OK" or r.q_solution is None:
        raise ValueError("起始姿态抬高 %.0f mm 的 IK 求解失败 (%s)" % (lift*1000, r.status))
    return np.asarray(r.q_solution, dtype=float)


def drawing_spec(paths, paper, q0):
    from drawing_geometry import paper_frame
    from four_point_calibration import ready
    if paper.get('geometry_mode') == 'four_point' and not ready(paper):
        raise ValueError('四点标定尚未完成，请记录并应用 A、B、C、D 后重新规划')
    frame=paper_frame(paper)
    origin,u,v,n,matrix,placement=[frame[k] for k in ('origin','u','v','normal','matrix','placement')]
    def point(p):
        x, y = p
        xy=matrix@np.asarray([x-paths['width_mm']/2,y-paths['height_mm']/2])
        return (origin + xy[0]*.001*u + xy[1]*.001*v).tolist()
    strokes = []
    for chain in paths["paths"]:
        pts = [point(p) for p in chain]
        strokes.append(dict(segments=[dict(type="line", start_m=a, end_m=b) for a, b in zip(pts, pts[1:])]))
    return dict(name="armvision_drawing", units="m_rad", plane_origin_m=origin.tolist(),
                plane_normal=n.tolist(), plane_u=u.tolist(), plane_v=v.tolist(),
                canvas_to_plane_matrix=matrix.tolist(),drawing_offset_mm=placement.tolist(),
                contact_plane_enabled=frame['contact_plane_enabled'],
                pen_axis=frame['pen_axis'].tolist(), q0=list(q0), strokes=strokes)


def quantization_report(model, machine, commands, cancel=None, segments=None, *, original_positions=None):
    """Measure the commanded integer-count path, independently of the IK residual."""
    from motion import quantized_angles_many
    maximum = displacement = tilt_max = path_max = 0.
    air_clearance_min = float('inf')
    air_chord_max = 0.
    # This cache is supplied only by build() for its freshly generated plan.
    # Standalone callers and restored plans still recompute both FK paths.
    if original_positions is not None:
        original_positions=np.asarray(original_positions,dtype=np.float64)
        if original_positions.shape!=(len(commands),3) or not np.isfinite(original_positions).all():
            raise ValueError('invalid original FK cache')
    # Keep the exact servo rounding/limit checks, but evaluate FK in bounded
    # batches. The old loop computed two small chains per command on the ARM.
    batch = []
    def measure(rows):
        nonlocal air_clearance_min,air_chord_max
        q = np.asarray([row[0] for row in rows], dtype=np.float64)
        quantized = quantized_angles_many(machine,q)
        targets = np.asarray([row[1] for row in rows], dtype=np.float64)
        axes = np.asarray([row[2] for row in rows], dtype=np.float64)
        if (np.any(quantized < model.limits[:, 0])
                or np.any(quantized > model.limits[:, 1])):
            raise ValueError('计数量化后超出模型关节限位')
        if (targets.shape != (len(rows), 3) or axes.shape != (len(rows), 3)
                or not np.isfinite(targets).all() or not np.isfinite(axes).all()):
            raise ValueError('计数量化校验需要有限的三维目标与笔轴')
        poses = model.pose_many(quantized)
        original = (model.pose_many(q)[:, :3, 3] if original_positions is None
                    else original_positions[[row[4] for row in rows]])
        current_axes = poses[:, :3, :3] @ model.tool_axis
        errors = np.linalg.norm(targets-poses[:, :3, 3], axis=1)
        shifts = np.linalg.norm(poses[:, :3, 3]-original, axis=1)
        tilts = np.arctan2(np.linalg.norm(np.cross(axes, current_axes), axis=1),
                          np.einsum('ij,ij->i', axes, current_axes))
        path_error=0.
        if segments is not None:
            indexes=[row[3] for row in rows]
            starts=np.asarray([segments[i]['segment_start_m'] for i in indexes])
            delta=np.asarray([segments[i]['segment_end_m'] for i in indexes])-starts
            squared=np.einsum('ij,ij->i',delta,delta)
            fraction=np.zeros(len(rows)); valid=squared>1e-20
            fraction[valid]=np.clip(np.einsum('ij,ij->i',poses[valid,:3,3]-starts[valid],delta[valid])/squared[valid],0,1)
            distances=np.linalg.norm(poses[:,:3,3]-starts-fraction[:,None]*delta,axis=1)
            for local,index in enumerate(indexes):
                row=segments[index]
                if row.get('joint_space_air'):
                    clearance=float((poses[local,:3,3]-row['air_plane_origin_m'])@np.asarray(row['air_plane_normal']))
                    if clearance < float(row['air_min_clearance_m'])-1e-9:
                        raise ValueError('整数计数空中轨迹净空不足')
                    air_clearance_min=min(air_clearance_min,clearance)
                    air_chord_max=max(air_chord_max,float(distances[local]))
                    distances[local]=0.  # Air uses its checked clearance corridor.
            path_error=float(distances.max())
        return float(errors.max()), float(shifts.max()), float(tilts.max()), path_error
    for index,command in enumerate(commands):
        if cancel and cancel():
            raise InterruptedError('ABORT')
        batch.append((command['q_rad'],command['tip_target_m'],command['axis_target'],command.get('path_segment_index'),index))
        if len(batch) == 256:
            error, shift, tilt, path_error = measure(batch)
            maximum, displacement, tilt_max = max(maximum, error), max(displacement, shift), max(tilt_max, tilt)
            path_max=max(path_max,path_error)
            batch.clear()
    if batch:
        error, shift, tilt, path_error = measure(batch)
        maximum, displacement, tilt_max = max(maximum, error), max(displacement, shift), max(tilt_max, tilt)
        path_max=max(path_max,path_error)
    report=dict(max_target_error_m=maximum, max_rounding_displacement_m=displacement,
                max_tilt_rad=tilt_max, count_resolution_rad=2*np.pi/4096,
                scope='model prediction at integer command samples; not measured pen accuracy')
    if segments is not None:
        report['max_source_path_error_m']=path_max
    if np.isfinite(air_clearance_min):
        report.update(min_air_clearance_m=air_clearance_min,max_air_chord_deviation_m=air_chord_max,
                      source_path_scope='DRAW and vertical/approach lines; joint-space air checked against paper clearance')
    return report


MOTION_PRESETS = {
    'sugar_fast': dict(max_velocity_rad_s=.9, max_acceleration_rad_s2=4., max_jerk_rad_s3=200.,retime_max_passes=1,
        draw=dict(tip_speed_m_s=.028,tip_acc_m_s2=.30,lateral_acc_m_s2=.15),
        travel=dict(tip_speed_m_s=.12,tip_acc_m_s2=.80),
        lift=dict(height_m=.006,duration_s=.22),lower=dict(height_m=.006,duration_s=.28,slow_last_m=.0015)),
    'classic_fast': dict(max_velocity_rad_s=.24, max_acceleration_rad_s2=.6, max_jerk_rad_s3=200.,retime_max_passes=1),
    'gentle': dict(max_velocity_rad_s=.12, max_acceleration_rad_s2=.3, max_jerk_rad_s3=20.,retime_max_passes=4),
    'smooth_fast': dict(max_velocity_rad_s=.36, max_acceleration_rad_s2=.9, max_jerk_rad_s3=10.,retime_max_passes=2),
    'speed_priority': dict(max_velocity_rad_s=.72, max_acceleration_rad_s2=4., max_jerk_rad_s3=200.,retime_max_passes=1),
}


def motion_config(cfg, mode):
    """Explicit profile selection; legacy callers retain exact old trajectories."""
    if mode is None or mode == 'standard':
        return dict(cfg)
    if mode not in MOTION_PRESETS:
        raise ValueError('unknown motion_mode')
    from r1b.retiming import PROFILE, MOTION_VERSION, normalize_motion_limits
    selected = dict(cfg)
    old_v = float(cfg['max_velocity_rad_s'])
    old_a = float(cfg['max_acceleration_rad_s2'])
    old_j = float(cfg.get('max_jerk_rad_s3',20.))
    if not np.isfinite([old_v,old_a,old_j]).all() or min(old_v,old_a,old_j)<=0:
        raise ValueError('motion limits must be positive and finite')
    preset = MOTION_PRESETS[mode]
    # Speed priority explicitly replaces the old conservative scalar settings.
    # Actual per-joint limits remain in force when separately configured.
    if mode in ('speed_priority','classic_fast','sugar_fast'):
        old_v, old_a, old_j = (preset[k] for k in ('max_velocity_rad_s','max_acceleration_rad_s2','max_jerk_rad_s3'))
    selected.update(motion_profile=PROFILE, motion_algorithm_version=MOTION_VERSION,
        max_velocity_rad_s=min(preset['max_velocity_rad_s'], old_v),
        max_acceleration_rad_s2=min(preset['max_acceleration_rad_s2'], old_a),
        max_jerk_rad_s3=min(preset['max_jerk_rad_s3'], old_j),
        command_period_s=float(cfg.get('command_period_s', .05)),
        retime_max_passes=cfg.get('retime_max_passes', preset['retime_max_passes']),
        runtime_reserve_ratio=cfg.get('runtime_reserve_ratio', .9), corner_policy='preserve')
    if mode == 'speed_priority':
        selected.update(retime_max_passes=1, runtime_reserve_ratio=1., motion_node_policy='secant')
    if mode == 'classic_fast':
        selected.update(retime_max_passes=1,runtime_reserve_ratio=1.,motion_node_policy='classic_draw')
    if mode == 'sugar_fast':
        selected.update(retime_max_passes=1,runtime_reserve_ratio=1.,motion_node_policy='arc_length',
            cartesian_limits=dict(draw=dict(preset['draw']),travel=dict(preset['travel'])),
            planned_vertical=True,joint_space_air=True,command_period_s=.02,lift_m=.006,
            min_lift_motion_s=.22,min_lower_motion_s=.28,soft_lower_last_m=.0015,
            lift_ready_pause_s=0.,lower_ready_pause_s=.05,travel_ready_pause_s=0.,stroke_end_pause_s=0.,
            corner_stop_angle_deg=70.,min_segment_s=.002)
        overrides=cfg.get('sugar_fast_overrides',{})
        ranges=dict(lift_m=(.002,.05),command_period_s=(.01,.1),
            min_lift_motion_s=(.04,5.),min_lower_motion_s=(.04,5.),
            stroke_end_pause_s=(0.,5.),lift_ready_pause_s=(0.,5.),
            lower_ready_pause_s=(0.,5.),travel_ready_pause_s=(0.,5.))
        if not isinstance(overrides,dict) or set(overrides)-set(ranges):
            raise ValueError('invalid sugar_fast_overrides keys')
        for key,value in overrides.items():
            if isinstance(value,bool):raise ValueError('invalid sugar_fast_overrides.'+key)
            try:value=float(value)
            except (ValueError,TypeError):raise ValueError('invalid sugar_fast_overrides.'+key) from None
            lo,hi=ranges[key]
            if not np.isfinite(value) or not lo<=value<=hi:
                raise ValueError('invalid sugar_fast_overrides.'+key)
            selected[key]=value
    # Existing explicit per-joint restrictions can only tighten the preset.
    for key, cap in (('joint_max_velocity_rad_s', selected['max_velocity_rad_s']),
                     ('joint_max_acceleration_rad_s2', selected['max_acceleration_rad_s2']),
                     ('joint_max_jerk_rad_s3', selected['max_jerk_rad_s3'])):
        if key in cfg:
            selected[key] = np.minimum(np.asarray(cfg[key], dtype=float), cap).tolist()
    normalize_motion_limits(selected)
    return selected


def build(paths, output, machine=None, counts=None, cancel=None, backend=None, motion_mode=None, persist=True):
    build_started=time.perf_counter()
    from stroke_paths import path_digest, PIPELINE_VERSION
    if paths.get('engine') == 'local_opencv_edge':
        raise ValueError('旧边缘轮廓路径存在重复描线，请用新版 GUI 重新提取中心线')
    from motion import angles_from_counts
    if machine:
        model = Model(machine["model"])
        paper = machine["paper"]
        q0 = angles_from_counts(machine, counts)
    else:
        model, paper, q0 = nominal()
    spec = drawing_spec(paths, paper, q0)
    if motion_mode == 'sugar_fast' or ((machine or {}).get('execution') or {}).get('vertical_pen_lift') is True:
        # Use one world-vertical posture throughout contact and release; do not
        # rotate the pen into this posture while it is still touching the paper.
        # The measured paper frame and all contact positions remain unchanged.
        spec['pen_axis'] = [0., 0., -1.]
        spec['lift_direction'] = [0., 0., 1.]
    cfg = load("trajectory.json")
    cfg.update(max_velocity_rad_s=1.05, max_acceleration_rad_s2=19.2, command_period_s=.05, min_segment_s=.015,
               motion_profile='continuous_quintic', max_targets=10000, max_total_ik_iterations=120000)
    if machine:
        cfg.update(machine["trajectory"])
    cfg = motion_config(cfg, motion_mode)
    ik_cfg = load("contract.json")
    if motion_mode == 'sugar_fast' or ((machine or {}).get('execution') or {}).get('vertical_pen_lift') is True:
        ik_cfg = dict(ik_cfg, tilt_tolerance_rad=min(float(ik_cfg['tilt_tolerance_rad']), .002))
        cfg['tilt_tolerance_rad'] = min(float(cfg['tilt_tolerance_rad']), .01)
        # The calibrated tool axis may need a larger wrist-roll change for a
        # small world-axis rotation. Subdivide it without relaxing joint limits.
        cfg['approach_axis_step_rad'] = min(float(cfg['approach_axis_step_rad']), .01)
    backend_before=backend.metrics() if hasattr(backend,'metrics') else {}
    result = plan(model, spec, q0, ik_cfg, cfg, backend or python_f32_inputs, cancel=cancel)
    if cfg.get('joint_space_air') and result.status == 'AIR_CLEARANCE_ERROR':
        # The endpoint-only air arc is allowed only inside a checked corridor.
        # Retry with a raised midpoint; failed checks still reject the plan.
        cfg=dict(cfg,air_raise_retry_m=float(cfg['lift_m']))
        result=plan(model,spec,q0,ik_cfg,cfg,backend or python_f32_inputs,cancel=cancel)
        result.metrics['air_retry']='raised_midpoint'
    if result.status=='OK' and result.trajectory_segments:
        from pen_transitions import add_endpoint_pauses
        pause_started=time.perf_counter()
        add_endpoint_pauses(result,cfg,consume=True)
        result.metrics.setdefault('timing',{})['pause_insert_s']=time.perf_counter()-pause_started
    result.metrics['planning_engine_version']='planning-sugar-v4' if cfg.get('planned_vertical') else 'planning-speed-v3'
    try:
        from native.geometry import status as native_status
        result.metrics['native_geometry']=native_status()
    except ImportError:
        result.metrics['native_geometry']=dict(enabled=False,reason='native module unavailable')
    result.metrics['motion_mode'] = motion_mode or ('gentle' if cfg.get('motion_profile') == 'continuous_quintic_vaj' else 'standard')
    if result.status == 'OK' and result.trajectory_segments:
        freeze_execution_contract(result,machine,cfg)
    result.metrics['drawing_pipeline_version']=PIPELINE_VERSION
    result.metrics['path_source']=dict(engine=paths.get('engine','external_vector'),
        width_mm=paths['width_mm'],height_mm=paths['height_mm'],
        drawing_offset_mm=spec['drawing_offset_mm'],xy_calibrated=bool((machine or {}).get('paper',{}).get('xy_calibration')),
        algorithm_version=paths.get('algorithm_version'),source_sha256=paths.get('source_sha256'),
        path_sha256=path_digest(paths),coordinate_system=paths.get('coordinate_system'),
        strokes=len(paths.get('paths',[])),segments=sum(len(p)-1 for p in paths.get('paths',[])),
        draw_length_mm=paths.get('draw_length_mm'),ordering=paths.get('ordering'))
    result.metrics['ik_backend'] = getattr(backend, 'name', 'PS_float32_inputs')
    if hasattr(backend, 'metrics'):
        result.metrics['pl_session'] = backend.metrics()
        result.metrics['pl_job']={k:result.metrics['pl_session'][k]-backend_before.get(k,0)
            for k in ('calls','evaluations','total_s','write_s','wait_s','read_s','validate_s','inputs_s',
                      'pose_cache_s','input_words','output_words','cached_successes','input_cache_hits','input_cache_misses',
                      'batch_calls','fk_rows_checked')
            if k in result.metrics['pl_session']}
    original_positions=None
    if result.status=='OK' and result.commands and all('tip_reference_m' in c for c in result.commands):
        reuse_started=time.perf_counter()
        original_positions=np.asarray([c['tip_reference_m'] for c in result.commands],dtype=np.float64)
        # Holds evaluate the polynomial at u=1; do not assume the preceding
        # sampled q and its reference tip are bit-identical to that endpoint.
        pause_indexes=[i for i,c in enumerate(result.commands) if c.get('endpoint_pause')]
        for start in range(0,len(pause_indexes),256):
            indexes=pause_indexes[start:start+256]
            if cancel and cancel():
                result.status,result.commands='ABORT',None
                result.trajectory_segments=result.execution_contract=None
                original_positions=None
                break
            original_positions[indexes]=model.pose_many(np.asarray([result.commands[i]['q_rad'] for i in indexes]))[:, :3, 3]
        result.metrics.setdefault('timing',{})['original_fk_reuse_s']=time.perf_counter()-reuse_started
    if machine and result.status == 'OK':
        quantization_started=time.perf_counter()
        try:
            quantized = quantization_report(model, machine, result.commands, cancel, result.trajectory_segments,
                                           original_positions=original_positions)
            result.metrics['quantization'] = quantized
            limit = cfg.get('quantized_tracking_error_m')
            if limit is not None:
                if not np.isfinite(limit) or limit <= 0:
                    raise ValueError('quantized_tracking_error_m 必须为正数（米）')
                if quantized.get('max_source_path_error_m',quantized['max_target_error_m']) > limit:
                    raise ValueError('整数计数轨迹超过 quantized_tracking_error_m；检查标定或调整验收阈值')
        except ValueError as exc:
            result.status, result.commands = 'QUANTIZATION_ERROR', None
            result.trajectory_segments = result.execution_contract = None
            result.metrics['detail'] = str(exc)
        except InterruptedError:
            result.status, result.commands = 'ABORT', None
            result.trajectory_segments = result.execution_contract = None
        result.metrics.setdefault('timing',{})['quantization_s']=time.perf_counter()-quantization_started
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result.metrics['effective_trajectory']=dict(cfg)
    result.metrics['runtime_source']=str(SOURCE)
    save_started=time.perf_counter()
    (output / "drawing.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    # Only this freshly generated invocation supplies cached FK to preview.
    if original_positions is not None and result.status=='OK':
        from r1b.cli import preview_positions
        preview_positions(spec,result,output/'preview.svg',original_positions)
    else:
        preview(model, spec, result, output / "preview.svg")
    result.metrics.setdefault('timing',{})['drawing_preview_s']=time.perf_counter()-save_started
    serialized_started=time.perf_counter()
    # Plan fields already contain JSON-native lists/dicts. Recursive asdict()
    # copied the entire command stream, and indentation dominated ARM save time.
    from plan_storage import publish_execution_plan
    if persist or result.status != 'OK':
        publish_execution_plan(output/'plan.json',result,cancelled=cancel if result.status=='OK' else None)
    result.metrics['plan_persistence'] = 'synchronous' if persist else 'background'
    # Include actual plan serialization/write time in a separate timing artifact
    # and the in-memory result, avoiding a second serialization of the plan.
    result.metrics['timing']['plan_save_s']=time.perf_counter()-serialized_started
    result.metrics['timing']['build_total_s']=time.perf_counter()-build_started
    result.metrics['planning_goal']=dict(target_s=30.,scope='build including checks, preview and plan save',
        measured_s=result.metrics['timing']['build_total_s'],
        met=result.status=='OK' and result.metrics['timing']['build_total_s']<=30.)
    (output / 'timing.json').write_text(json.dumps(result.metrics['timing'],indent=2),encoding='utf-8')
    return result, spec, cfg


def freeze_execution_contract(result,machine,cfg):
    from r1b.retiming import normalize_motion_limits,MOTION_VERSION
    v,a,j=normalize_motion_limits(cfg)
    servo=dict(((machine or {}).get('execution') or {}).get('servo_profile') or {})
    if result.metrics['motion_mode']=='classic_fast':servo.setdefault('speed_codes',100)
    result.execution_contract=dict(schema='so101-motion-execution-v1',motion_mode=result.metrics['motion_mode'],
        motion_algorithm_version=MOTION_VERSION,command_period_s=cfg['command_period_s'],
        joint_max_velocity_rad_s=v.tolist(),joint_max_acceleration_rad_s2=a.tolist(),joint_max_jerk_rad_s3=j.tolist(),
        runtime_reserve_ratio=cfg.get('runtime_reserve_ratio',.9),servo_profile=servo,
        geometry_tolerance_m=cfg['tracking_error_m'],tilt_tolerance_rad=cfg['tilt_tolerance_rad'])
    if ((machine or {}).get('execution') or {}).get('vertical_pen_lift') is True:
        result.execution_contract['pen_lift_policy'] = 'world_vertical_v1'
    if cfg.get('planned_vertical'):
        result.execution_contract['pen_lift_policy'] = 'planned_vertical_v2'
        result.execution_contract['planned_vertical'] = dict(axis=[0.,0.,-1.],lift_m=cfg['lift_m'],
            min_lift_motion_s=cfg['min_lift_motion_s'],min_lower_motion_s=cfg['min_lower_motion_s'],
            soft_lower_last_m=cfg['soft_lower_last_m'],coupled_joint_ids=[2,3,4],fixed_joint_ids=[1,5],
            duration_policy='minimum candidate; full velocity acceleration jerk checks may extend',
            scope='model posture preservation; physical axis and servo tracking require measurement')


def build_pen_up_transfer(machine,current,end,backend=None,cancel=None,motion_mode=None,
                          allow_low_endpoint=False,end_q_rad=None,joint_limits=None):
    """Lift in place, travel above the paper, then approach the endpoint vertically.

    Used for homing and a measured-start join; never contains DRAW targets.
    """
    from motion import angles_from_counts
    from r1b.path import line,lerp_axis
    from pen_transitions import add_endpoint_pauses
    from drawing_geometry import paper_frame
    if motion_mode is None:
        motion_mode='sugar_fast' if machine.get('execution',{}).get('default_motion_mode')=='sugar_fast' else 'speed_priority'
    model=Model(machine['model']);paper=machine['paper'];frame=paper_frame(paper)
    normal=frame['normal'];origin=frame['origin']
    q0=np.asarray(angles_from_counts(machine,current));q1=np.asarray(end_q_rad if end_q_rad is not None else angles_from_counts(machine,end))
    cfg=load('trajectory.json');cfg.update(max_targets=10000,max_total_ik_iterations=120000,min_segment_s=.015)
    cfg.update(machine['trajectory']);cfg=motion_config(cfg,motion_mode)
    ik_cfg=load('contract.json')
    if cfg.get('planned_vertical'):
        # Match drawing's posture resolution when approaching an exact stored
        # home pose: a small axis change can require a much larger wrist roll.
        ik_cfg=dict(ik_cfg,tilt_tolerance_rad=min(float(ik_cfg['tilt_tolerance_rad']),.002))
        cfg['tilt_tolerance_rad']=min(float(cfg['tilt_tolerance_rad']),.01)
        cfg['approach_axis_step_rad']=min(float(cfg['approach_axis_step_rad']),.01)
    if joint_limits is not None:
        for key,value in zip(('joint_max_velocity_rad_s','joint_max_acceleration_rad_s2','joint_max_jerk_rad_s3'),joint_limits):cfg[key]=np.asarray(value).tolist()
    p0=model.pose(q0);p1=model.pose(q1);height1=float((p1[:3,3]-origin)@normal)
    if not allow_low_endpoint and height1<cfg['lift_m']:
        q1=home_pose(model,paper,q1,cfg['lift_m']-height1,backend=backend);p1=model.pose(q1)
    height=max(float((p0[:3,3]-origin)@normal),float((p1[:3,3]-origin)@normal),cfg['lift_m'])
    lift_direction=normal
    if cfg.get('planned_vertical'):
        projection=float(normal[2])
        if projection<=.1:raise ValueError('world-vertical lift cannot provide paper clearance')
        lift_direction=np.array([0.,0.,1.])/projection
    start=p0[:3,3]+lift_direction*(height-float((p0[:3,3]-origin)@normal))
    finish=p1[:3,3]+lift_direction*(height-float((p1[:3,3]-origin)@normal))
    a0=p0[:3,:3]@model.tool_axis;a1=p1[:3,:3]@model.tool_axis
    travel_axis=np.array([0.,0.,-1.]) if cfg.get('planned_vertical') else -normal
    targets=[dict(position=start.tolist(),axis=travel_axis.tolist(),phase='APPROACH',stroke=-1)]
    samples=np.asarray([start,finish]) if cfg.get('joint_space_air') else line(start,finish,cfg['max_cartesian_step_m'],cfg['max_targets'])
    for i,p in enumerate(samples[1:],1):
        targets.append(dict(position=p.tolist(),axis=travel_axis.tolist(),phase='TRAVEL',stroke=-1,
                            **({'joint_space_air':True} if cfg.get('joint_space_air') else {})))
    angle=float(np.arctan2(np.linalg.norm(np.cross(travel_axis,a1)),np.dot(travel_axis,a1)))
    if angle>1e-10:
        n=max(1,int(np.ceil(angle/cfg['approach_axis_step_rad'])))
        for i in range(1,n+1):
            targets.append(dict(position=finish.tolist(),axis=lerp_axis(travel_axis,a1,i/n).tolist(),phase='APPROACH',stroke=-1))
    if np.linalg.norm(p1[:3,3]-finish)>1e-10:
        phase='LOWER' if allow_low_endpoint else 'APPROACH'
        if cfg.get('planned_vertical'):
            from r1b.sugar import vertical_samples
            for p,t in vertical_samples(finish,p1[:3,3],'LOWER',cfg):
                targets.append(dict(position=p.tolist(),axis=a1.tolist(),phase=phase,stroke=-1,vertical_time_s=t))
        else:
            for p in line(finish,p1[:3,3],cfg['max_cartesian_step_m'],cfg['max_targets'])[1:]:
                targets.append(dict(position=p.tolist(),axis=a1.tolist(),phase=phase,stroke=-1))
    spec=dict(units='m_rad',plane_origin_m=origin.tolist(),plane_normal=normal.tolist(),pen_axis=a1.tolist())
    if cfg.get('planned_vertical'):
        spec.update(lift_direction=[0.,0.,1.],pen_axis=[0.,0.,-1.])
    result=plan(model,spec,q0,ik_cfg,cfg,backend or python_f32_inputs,cancel=cancel,
        targets_override=targets,final_q=q1)
    result.metrics['motion_mode']=motion_mode
    if result.status=='OK':
        add_endpoint_pauses(result,cfg);freeze_execution_contract(result,machine,cfg)
    return result,q0,cfg
