"""Manual pose calibration math. No serial writes and no inferred photo scale."""
import copy
import numpy as np


def calibrate_pen(machine, counts, kind):
    import planning
    from motion import angles_from_counts
    updated = copy.deepcopy(machine)
    model = planning.Model(updated['model'])
    q = angles_from_counts(updated, counts)
    pose = model.pose(q)
    from drawing_geometry import paper_frame
    normal = paper_frame(updated['paper'])['normal']
    if normal.shape != (3,) or not np.isfinite(normal).all() or not np.isclose(np.linalg.norm(normal), 1.):
        raise ValueError('纸面法向需要单位向量')
    detail = dict(kind=kind, measured_counts=dict(counts), model_tip_m=pose[:3,3].tolist(),
        scope='user-confirmed physical pose; encoder model calibration, no contact sensor')
    if kind == 'axis':
        # User has physically made the PEN vertical. The model's old +X tool
        # direction is therefore not assumed to match the installed pen.
        axis = pose[:3,:3].T @ (-normal)
        axis /= np.linalg.norm(axis)
        detail.update(previous_axis_local=copy.deepcopy(updated['model']['tool_axis_local']),
            tool_axis_local=axis.tolist(), paper_normal=normal.tolist())
        updated['model']['tool_axis_local'] = axis.tolist()
        updated['paper']['pen_axis'] = (-normal).tolist()
        updated['model']['pen_axis_calibration'] = detail
        # Changing the pen direction does not change encoder FK positions.
        # Preserve the existing physical C/X/Y marks under the new signature.
        from drawing_geometry import calibration_signature
        calibration=updated['paper'].get('xy_calibration') or {}
        for capture in calibration.get('captures',{}).values():
            capture['signature']=calibration_signature(updated)
    elif kind == 'contact_height':
        # A manually confirmed light contact defines an effective plane height
        # with the CURRENT tool model. This is not a full tool-length or tilted
        # paper calibration, and does not autonomously move downwards.
        from drawing_geometry import paper_frame
        frame=paper_frame(updated['paper'])
        if frame['contact_plane_enabled']:
            normal=frame['normal'];offset=float((pose[:3,3]-frame['origin'])@normal)
            updated['paper']['contact_height_offset_m']=float(updated['paper'].get('contact_height_offset_m',0.))+offset
            updated['paper']['draw_height_offset_m']=0.
            detail.update(origin_shift_m=offset,contact_plane_enabled=True)
            updated['paper']['contact_height_calibration']=detail
            return updated,detail
        origin = np.asarray(updated['paper']['origin_m'], dtype=float)
        offset = float((pose[:3,3]-origin) @ normal)
        detail.update(previous_origin_m=origin.tolist(),
            previous_draw_height_offset_m=updated['paper'].get('draw_height_offset_m',0.),
            origin_shift_m=offset)
        updated['paper']['origin_m'] = (origin+offset*normal).tolist()
        updated['paper']['draw_height_offset_m'] = 0.
        updated['paper']['contact_height_calibration'] = detail
    else:
        raise ValueError('不支持的笔尖标定类型')
    return updated, detail
