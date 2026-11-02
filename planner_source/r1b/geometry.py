"""Batch FK measurements against requested samples and the intended segment."""
import numpy as np


def measure_segments(model,joints,starts,deltas,desired,axes):
    """Per-sample errors for a batch containing several intended segments."""
    pose=model.pose_many(np.asarray(joints,dtype=float))
    actual=pose[:,:3,3]
    norm=np.einsum('ij,ij->i',deltas,deltas)
    progress=np.zeros(len(actual))
    moving=norm>1e-20
    progress[moving]=np.clip(np.einsum('ij,ij->i',actual[moving]-starts[moving],
                                     deltas[moving])/norm[moving],0,1)
    closest=starts+progress[:,None]*deltas
    current_axes=pose[:,:3,:3]@model.tool_axis
    tilt=np.arctan2(np.linalg.norm(np.cross(axes,current_axes),axis=1),
                    np.einsum('ij,ij->i',axes,current_axes))
    return (np.linalg.norm(actual-closest,axis=1),
            np.linalg.norm(actual-desired,axis=1),tilt)


def measure_segment(model,joints,p0,p1,desired,axes):
    pose=model.pose_many(np.asarray(joints,dtype=float))
    actual=pose[:,:3,3]
    dp=np.asarray(p1)-p0
    norm=float(dp@dp)
    progress=np.clip((actual-p0)@dp/norm,0,1) if norm > 1e-20 else np.zeros(len(actual))
    closest=np.asarray(p0)+progress[:,None]*dp
    current_axes=pose[:,:3,:3]@model.tool_axis
    tilt=np.arctan2(np.linalg.norm(np.cross(axes,current_axes),axis=1),
                    np.einsum('ij,ij->i',axes,current_axes))
    return dict(path=float(np.linalg.norm(actual-closest,axis=1).max()),
                requested=float(np.linalg.norm(actual-desired,axis=1).max()),
                tilt=float(tilt.max()))
