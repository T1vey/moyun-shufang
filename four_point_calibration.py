"""Four measured square corners -> one affine 3D paper frame. No motor I/O."""
import copy
import numpy as np

SCHEMA = 'so101-four-point-plane-v1'
POINTS = ('A', 'B', 'C', 'D')
LABELS = dict(A='左上', B='右上', C='右下', D='左下')
UNIT_CORNERS = np.array([[-.5, -.5], [.5, -.5], [.5, .5], [-.5, .5]])


def ready(paper):
    calibration = paper.get('xy_calibration') or {}
    return (paper.get('geometry_mode') == 'four_point' and
            calibration.get('schema') == SCHEMA and
            calibration.get('contact_plane_enabled') is True)


def begin_calibration(machine, side_mm=200.):
    side = float(side_mm)
    if not np.isfinite(side) or side <= 0:
        raise ValueError('正方形边长必须是正的毫米值')
    updated = copy.deepcopy(machine)
    paper = updated['paper']
    paper.pop('xy_calibration', None)
    paper.pop('contact_height_calibration', None)
    paper.update(geometry_mode='four_point', four_point_side_mm=side,
                 drawing_offset_mm=[0., 0.], draw_height_offset_m=0., contact_height_offset_m=0.)
    return updated


def fit_positions(positions, side_mm, normal_hint, allow_large_residual=False):
    """Use every corner equally; report non-affine/nonplanar residuals."""
    side = float(side_mm)
    if not np.isfinite(side) or side <= 0:
        raise ValueError('正方形边长必须是正的毫米值')
    p = np.asarray([positions[name] for name in POINTS], dtype=float)
    hint = np.asarray(normal_hint, dtype=float)
    if p.shape != (4, 3) or not np.isfinite(p).all() or hint.shape != (3,) or not np.isfinite(hint).all():
        raise ValueError('四点坐标或纸面方向无效')
    if any(np.linalg.norm(p[i]-p[j]) < .001 for i in range(4) for j in range(i)):
        raise ValueError('四点中有重复或过近的点，请分别记录四个角')
    design = np.column_stack((np.ones(4), UNIT_CORNERS))
    coefficients = np.linalg.lstsq(design, p, rcond=None)[0]
    origin = coefficients[0]
    axes = coefficients[1:].T / (side/1000.)
    if np.linalg.matrix_rank(axes) != 2 or np.linalg.cond(axes) > 20.:
        raise ValueError('四点退化或接近共线，请按 A左上 B右上 C右下 D左下重新采点')
    normal = np.cross(axes[:, 0], axes[:, 1]); normal /= np.linalg.norm(normal)
    # A crossed or concave quadrilateral must not silently become an average plane.
    for i in range(4):
        edge = p[(i+1)%4]-p[i]; after = p[(i+2)%4]-p[(i+1)%4]
        if np.dot(np.cross(edge, after), normal) <= 1e-8:
            raise ValueError('四点顺序交叉或形状退化，请核对四角位置')
    # Canvas Y points down, so corner winding need not match the robot's
    # right-handed XY basis. Keep the lift direction above the paper while
    # preserving the measured canvas axes, including a reflected mapping.
    if np.linalg.norm(hint)<1e-8 or abs(np.dot(normal,hint)/np.linalg.norm(hint))<1e-6:
        raise ValueError('四点纸面方向与当前抬笔方向垂直，请核对点位')
    if np.dot(normal,hint)<0.:normal=-normal
    predicted = design @ coefficients
    residual = np.linalg.norm(predicted-p, axis=1)
    tolerance = max(.002, side/1000.*.025)
    exceeded = bool(residual.max() > tolerance)
    if exceeded and allow_large_residual is not True:
        raise ValueError('四点拟合残差 %.2f mm 超过 %.2f mm，请复测间距、顺序和轻触姿态' %
                         (residual.max()*1000, tolerance*1000))
    return dict(origin_m=origin.tolist(), axes_m_per_m=axes.tolist(), normal=normal.tolist(),
                fit_residual_mm={name: float(value*1000) for name,value in zip(POINTS,residual)},
                max_fit_residual_mm=float(residual.max()*1000),
                rms_fit_residual_mm=float(np.sqrt(np.mean(residual**2))*1000),
                fit_limit_mm=tolerance*1000,
                residual_limit_exceeded=exceeded,
                residual_override_applied=exceeded and allow_large_residual is True,
                physical_points_mm={name: (xy*side).tolist() for name,xy in zip(POINTS,UNIT_CORNERS)})


def _positions(machine, captures, side):
    import planning
    from drawing_geometry import calibration_signature
    from motion import angles_from_counts
    if not isinstance(captures, dict) or set(captures) != set(POINTS):
        raise ValueError('请先记录 A、B、C、D 四个实物点')
    signature = calibration_signature(machine)
    model = planning.Model(machine['model']); positions = {}
    for name in POINTS:
        capture = captures[name]
        if not isinstance(capture, dict):
            raise ValueError('四点记录格式无效，请重新采点')
        if capture.get('signature') != signature:
            raise ValueError('关节、笔轴或模型标定已变化，请重新记录四个点')
        if float(capture.get('side_mm', side)) != side:
            raise ValueError('采点期间边长已变化，请按同一个实测边长重新记录四点')
        try: counts = {int(k): v for k,v in capture['counts'].items()}
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError('四点需要完整的五关节整数读数')
        if (set(counts) != {j['id'] for j in machine['joints']} or
                any(type(counts[j['id']]) is not int or not j['min_count'] <= counts[j['id']] <= j['max_count']
                    for j in machine['joints'])):
            raise ValueError('四点关节读数不完整或超出限位')
        positions[name] = model.pose(angles_from_counts(machine, counts))[:3, 3]
    return positions


def calibrate_four_points(machine, captures, side_mm=200., allow_large_residual=False):
    side = float(side_mm)
    positions = _positions(machine, captures, side)
    fit = fit_positions(positions, side, machine['paper']['normal'], allow_large_residual)
    updated = begin_calibration(machine, side)
    paper = updated['paper']; axes = np.asarray(fit['axes_m_per_m'])
    basis = np.asarray([paper['u'], paper['v']])
    detail = dict(schema=SCHEMA, distance_mm=side, captures=copy.deepcopy(captures),
                  model_points_m={name:p.tolist() for name,p in positions.items()},
                  matrix=(basis@axes).tolist(),
                  translation_mm=(basis@(np.asarray(fit['origin_m'])-paper['origin_m'])*1000).tolist(),
                  contact_plane_enabled=True, fit=fit,
                  contact_scope='four user-confirmed light contacts; affine 3D fit',
                  scope='A top-left B top-right C bottom-right D bottom-left; square centre is drawing origin')
    paper['xy_calibration'] = detail
    if fit['residual_override_applied']:
        detail['residual_override'] = dict(accepted=True, reason='user_requested',
            accepted_max_residual_mm=fit['max_fit_residual_mm'])
    paper['pen_axis'] = (-np.asarray(fit['normal'])).tolist()
    return updated, detail


def validate(machine, require_ready=False):
    paper = machine.get('paper') or {}
    if paper.get('geometry_mode') != 'four_point': return
    side_setting=float(paper.get('four_point_side_mm',200.))
    if not np.isfinite(side_setting) or side_setting<=0:
        raise ValueError('正方形边长必须是正的毫米值')
    detail = paper.get('xy_calibration')
    if detail is None:
        if require_ready: raise ValueError('四点标定尚未完成，请记录并应用 A、B、C、D 后重新规划')
        return
    if not ready(paper): raise ValueError('当前使用四点标定，不能恢复旧三点校正')
    side = float(detail['distance_mm'])
    if side != side_setting:raise ValueError('四点边长与当前配置不一致，请重新应用标定')
    positions = _positions(machine, detail['captures'], side)
    override = detail.get('residual_override') or {}
    allow_large = isinstance(override, dict) and override.get('accepted') is True
    fit = fit_positions(positions, side, paper['normal'], allow_large)
    if allow_large and not np.isclose(float(override.get('accepted_max_residual_mm',-1.)),
                                      fit['max_fit_residual_mm'],rtol=0.,atol=1e-6):
        raise ValueError('强制应用记录与当前四点残差不一致，请重新应用标定')
    for name in POINTS:
        if not np.allclose(positions[name], detail['model_points_m'][name], rtol=0., atol=1e-10):
            raise ValueError('四点坐标与关节读数不一致，请重新应用标定')
    for key in ('origin_m', 'axes_m_per_m', 'normal'):
        if not np.allclose(np.asarray(detail['fit'][key]), fit[key], rtol=0., atol=1e-10):
            raise ValueError('四点拟合结果不一致，请重新应用标定')

