"""Measured paper XY calibration and drawing placement; no motor I/O."""
import copy
import numpy as np


def paper_frame(paper):
    """One effective 3D frame shared by planning, transfers and feedback.

    Four-corner records use the fitted centre and affine 3D axes. Archived
    C/X/Y records retain their historical frame for prediction/review.
    Normalising measured axes would undo the physical scale correction.
    Legacy XY-only records remain supported until their contact is confirmed.
    """
    matrix, translation, placement = geometry_parameters(paper)
    origin = np.asarray(paper['origin_m'], dtype=float)
    basis = np.asarray([paper[k] for k in ('u', 'v', 'normal')], dtype=float)
    if (origin.shape != (3,) or basis.shape != (3,3) or not np.isfinite(origin).all()
            or not np.isfinite(basis).all() or not np.allclose(basis@basis.T,np.eye(3),atol=1e-6)
            or not np.allclose(np.cross(basis[0],basis[1]),basis[2],atol=1e-6)):
        raise ValueError('纸面坐标必须是有限的正交单位向量')
    u,v,n=basis
    height=float(paper.get('draw_height_offset_m',0.) or 0.)
    calibration=paper.get('xy_calibration') or {}
    if calibration.get('contact_plane_enabled') is True:
        from four_point_calibration import SCHEMA
        if calibration.get('schema') == SCHEMA:
            c=np.asarray(calibration['fit']['origin_m'],dtype=float)
            axes=np.asarray(calibration['fit']['axes_m_per_m'],dtype=float)
        else:
            points=calibration['model_points_m'];distance=float(calibration['distance_mm'])/1000
            c,x,y=[np.asarray(points[k],dtype=float) for k in ('C','X','Y')]
            axes=np.column_stack(((x-c)/distance,(y-c)/distance))
        if axes.shape!=(3,2) or not np.isfinite(axes).all() or np.linalg.matrix_rank(axes)<2:
            raise ValueError('标定接触平面无效')
        u=axes[:,0]/np.linalg.norm(axes[:,0]);n=np.cross(axes[:,0],axes[:,1]);n/=np.linalg.norm(n)
        if calibration.get('schema') == SCHEMA and np.dot(n,paper['normal'])<0.:
            n=-n
        v=np.cross(n,u)
        matrix=np.asarray([u,v])@axes
        origin=c
        height+=float(paper.get('contact_height_offset_m',0.))
        axis=-n
    else:
        origin=origin+.001*(translation[0]*u+translation[1]*v)
        axis=np.asarray(paper['pen_axis'],dtype=float)
    if not np.isfinite(height):raise ValueError('落笔高度必须是有限数')
    shift=matrix@placement
    origin=origin+height*n+.001*(shift[0]*u+shift[1]*v)
    return dict(origin=origin,u=u,v=v,normal=n,matrix=matrix,placement=placement,pen_axis=axis,
                contact_plane_enabled=calibration.get('contact_plane_enabled') is True)


def enable_contact_plane(machine):
    """Migrate confirmed existing contact captures without changing XY data."""
    updated=copy.deepcopy(machine)
    calibration=updated['paper']['xy_calibration']
    calibration['contact_plane_enabled']=True
    calibration['contact_scope']='confirmed light contact C/X/Y; full 3D model plane'
    # The old offset was relative to the arbitrary original paper Z, not C.
    # Applying it again would move the pen away from the confirmed contacts.
    calibration.setdefault('previous_draw_height_offset_m',updated['paper'].get('draw_height_offset_m',0.))
    updated['paper']['draw_height_offset_m']=0.
    updated['paper'].setdefault('contact_height_offset_m',0.)
    paper_frame(updated['paper'])
    return updated


def geometry_parameters(paper):
    calibration=paper.get('xy_calibration') or {}
    matrix=np.asarray(calibration.get('matrix',[[1.,0.],[0.,1.]]),dtype=float)
    translation=np.asarray(calibration.get('translation_mm',[0.,0.]),dtype=float)
    offset=np.asarray(paper.get('drawing_offset_mm',[0.,0.]),dtype=float)
    if (matrix.shape!=(2,2) or translation.shape!=(2,) or offset.shape!=(2,)
            or not np.isfinite(matrix).all() or not np.isfinite(translation).all() or not np.isfinite(offset).all()
            or abs(np.linalg.det(matrix))<1e-6 or np.linalg.cond(matrix)>1e4):
        raise ValueError('绘画位置或几何标定无效')
    return matrix,translation,offset


def inverse_projection(spec):
    matrix=np.asarray(spec.get('canvas_to_plane_matrix',[[1.,0.],[0.,1.]]),dtype=float)
    if matrix.shape!=(2,2) or not np.isfinite(matrix).all() or abs(np.linalg.det(matrix))<1e-6:
        raise ValueError('规划几何投影无效')
    return np.linalg.inv(matrix)


def calibration_signature(machine):
    import hashlib,json
    # Drawing placement and pen pressure may change without changing encoder FK.
    identity=dict(joints=machine['joints'],model=machine['model'],
        basis={k:machine['paper'][k] for k in ('origin_m','u','v','normal')})
    return hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def calibrate_three_points(machine, captures, distance_mm):
    """Physical marks C, X (right), Y (canvas positive-Y), at known spacing.

    Human-confirmed physical points supply the otherwise missing geometry.
    Captures are user-confirmed light contacts. Their full XYZ coordinates
    define the effective paper plane; encoder and tool calibration remain.
    """
    import planning
    from motion import angles_from_counts
    distance=float(distance_mm)
    if not np.isfinite(distance) or distance<=0:raise ValueError('标定点间距需要正的毫米值')
    model=planning.Model(machine['model']);paper=machine['paper']
    basis=np.asarray([paper['u'],paper['v']],dtype=float);origin=np.asarray(paper['origin_m'])
    positions={}
    for name in ('C','X','Y'):
        capture=captures.get(name)
        if not capture:raise ValueError('请先记录 C、X、Y 三个实物点')
        if capture.get('signature')!=calibration_signature(machine):raise ValueError('关节或模型标定已变化，请重新记录三个点')
        counts={int(k):v for k,v in capture['counts'].items()}
        positions[name]=model.pose(angles_from_counts(machine,counts))[:3,3]
    matrix=np.column_stack((basis@(positions['X']-positions['C']),
                             basis@(positions['Y']-positions['C'])))*1000/distance
    translation=basis@(positions['C']-origin)*1000
    updated=copy.deepcopy(machine)
    detail=dict(schema='so101-three-point-xy-v1',matrix=matrix.tolist(),translation_mm=translation.tolist(),
        distance_mm=distance,captures=copy.deepcopy(captures),model_points_m={k:v.tolist() for k,v in positions.items()},
        scope='human measured physical marks; affine XY compensation, not full robot or TCP calibration')
    updated['paper']['xy_calibration']=detail
    geometry_parameters(updated['paper'])
    updated=enable_contact_plane(updated)
    return updated,updated['paper']['xy_calibration']
