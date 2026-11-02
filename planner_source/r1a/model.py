"""Frame-chain implementation. Geometry provenance: config/nominal_so101.json.

Joint transforms follow upstream's documented ET sequence. The implementation
uses a compact rotation/translation chain; upstream ET is the geometric oracle.
"""
import json
import math
from pathlib import Path
import numpy as np
try:
    from native.geometry import pose_many as _native_pose_many
except ImportError:  # Legacy release bundles can omit optional native support.
    _native_pose_many = None

_SO101_AXES_KEY=np.asarray([[0,0,1],[0,1,0],[0,1,0],[0,1,0],[1,0,0]],dtype=float).tobytes()


def finite_array(value, shape, label):
    a = np.asarray(value, dtype=np.float64)
    if a.shape != shape or not np.isfinite(a).all():
        raise ValueError(f"{label}: expected finite shape {shape}")
    return a


def skew(a):
    x, y, z = a
    return np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]], dtype=float)


class Model:
    def __init__(self, config):
        if config.get("units") != "m_rad":
            raise ValueError("model units must be m_rad")
        self.config = config
        self.offsets = finite_array(config["offsets_m"], (5, 3), "offsets")
        self.axes = finite_array(config["axes"], (5, 3), "axes")
        self.limits = finite_array(config["limits_rad"], (5, 2), "limits")
        self.tool = finite_array(config["tool_translation_m"], (3,), "tool")
        self.tool_axis = finite_array(config["tool_axis_local"], (3,), "tool axis")
        if not np.allclose(np.linalg.norm(self.axes, axis=1), 1, atol=1e-12, rtol=0):
            raise ValueError("joint axes must be unit vectors")
        if not np.isclose(np.linalg.norm(self.tool_axis), 1, atol=1e-12, rtol=0):
            raise ValueError("tool axis must be a unit vector")
        if np.any(self.limits[:, 0] >= self.limits[:, 1]):
            raise ValueError("empty joint interval")
        self._identity = np.eye(3)
        self._skews = np.array([skew(axis) for axis in self.axes])
        self._squares = self._skews @ self._skews

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8-sig")))

    def legal(self, q):
        q = np.asarray(q,dtype=np.float64)
        if q.shape!=(5,) or any(not math.isfinite(float(v)) for v in q):
            raise ValueError('q: expected finite shape (5,)')
        return all(lo<=v<=hi for v,lo,hi in zip(q,self.limits[:,0],self.limits[:,1]))

    def _forward(self, q, jacobian):
        q = finite_array(q, (5,), "q")
        rotation = np.eye(3)
        point = np.zeros(3)
        origins, world_axes = [], []
        rotations = self._identity + np.sin(q)[:, None, None]*self._skews + (1-np.cos(q))[:, None, None]*self._squares
        for i in range(5):
            point = point + rotation @ self.offsets[i]
            if jacobian:
                origins.append(point)
                world_axes.append(rotation @ self.axes[i])
            rotation = rotation @ rotations[i]
        point = point + rotation @ self.tool
        t = np.eye(4)
        t[:3, :3], t[:3, 3] = rotation, point
        if not jacobian:
            return t
        if jacobian == 'deferred':
            return t, (np.asarray(world_axes), np.asarray(origins))
        angular = np.asarray(world_axes).T
        linear = np.cross(world_axes, point-np.asarray(origins)).T
        return t, np.vstack((linear, angular))

    def evaluate(self, q):
        return self._forward(q, True)

    def pose(self, q):
        """FK only, for geometric probes that do not need a Jacobian."""
        if self.axes.shape==(5,3) and self.axes.tobytes()==_SO101_AXES_KEY:
            return self._so101_pose(q)
        return self._forward(q, False)

    def _so101_pose(self,q):
        """Scalar Rz/Ry/Ry/Ry/Rx chain; arbitrary offsets and calibrated tool.

        Used only when axes match exactly. Batch FK and Jacobian evaluation
        retain the generic chain, giving an independent numerical reference.
        """
        q=np.asarray(q,dtype=np.float64)
        if q.shape!=(5,) or any(not math.isfinite(float(v)) for v in q):
            raise ValueError('q: expected finite shape (5,)')
        c0,s0=math.cos(q[0]),math.sin(q[0])
        x,y,z=(float(v) for v in self.offsets[0])
        c,s=1.,0.
        for i in range(1,5):
            if i>1:
                ci,si=math.cos(q[i-1]),math.sin(q[i-1])
                c,s=c*ci-s*si,s*ci+c*si
            ox,oy,oz=self.offsets[i]
            radial=c*ox+s*oz
            x+=c0*radial-s0*oy;y+=s0*radial+c0*oy;z+=-s*ox+c*oz
        c4,s4=math.cos(q[4]),math.sin(q[4])
        rotation=np.array([[c0*c,-s0*c4+c0*s*s4,s0*s4+c0*s*c4],
                           [s0*c,c0*c4+s0*s*s4,-c0*s4+s0*s*c4],
                           [-s,c*s4,c*c4]])
        pose=np.eye(4);pose[:3,:3]=rotation
        pose[:3,3]=(x,y,z)+rotation@self.tool
        return pose

    def pose_many(self, qs):
        """FK for a finite (N, 5) joint array, returning (N, 4, 4).

        Each row follows the scalar pose() transform order, including calibrated
        joint axes, offsets and tool translation. Batching avoids a Python loop
        over every command when checking integer counts and drawing previews.
        """
        qs = np.asarray(qs, dtype=np.float64)
        if qs.ndim != 2 or qs.shape[1] != 5 or not np.isfinite(qs).all():
            raise ValueError("qs: expected finite shape (N, 5)")
        if _native_pose_many is not None:
            accelerated = _native_pose_many(self, qs)
            if accelerated is not None:
                return accelerated
        count = len(qs)
        rotation = np.broadcast_to(self._identity, (count, 3, 3)).copy()
        point = np.zeros((count, 3))
        sine, cosine = np.sin(qs), np.cos(qs)
        for i in range(5):
            point = point + rotation @ self.offsets[i]
            local = (self._identity + sine[:, i, None, None]*self._skews[i]
                     + (1-cosine[:, i, None, None])*self._squares[i])
            rotation = rotation @ local
        point = point + rotation @ self.tool
        poses = np.broadcast_to(np.eye(4), (count, 4, 4)).copy()
        poses[:, :3, :3], poses[:, :3, 3] = rotation, point
        return poses

    def pose_errors(self, pose, position, axis):
        """Position/axis errors from an already computed pose and validated targets."""
        current_axis = pose[:3, :3] @ self.tool_axis
        # Three scalar components avoid several NumPy dispatches per PL target.
        ax, ay, az = axis
        bx, by, bz = current_axis
        cx, cy, cz = ay*bz-az*by, az*bx-ax*bz, ax*by-ay*bx
        dx, dy, dz = position-pose[:3, 3]
        return (math.sqrt(dx*dx+dy*dy+dz*dz),
                math.atan2(math.sqrt(cx*cx+cy*cy+cz*cz), ax*bx+ay*by+az*bz))

    def task(self, q, position, axis):
        position = finite_array(position, (3,), "target position")
        axis = finite_array(axis, (3,), "target axis")
        if not np.isclose(np.linalg.norm(axis), 1, atol=1e-8, rtol=0):
            raise ValueError("target axis must be a unit vector")
        pose, geometric = self.evaluate(q)
        current_axis = pose[:3, :3] @ self.tool_axis
        # e(q+dq) ~= e(q) - J*dq, including the exact chord derivative.
        error = np.r_[position - pose[:3, 3], axis - current_axis]
        jacobian = np.vstack((geometric[:3], -skew(current_axis) @ geometric[3:]))
        tilt = float(np.arctan2(np.linalg.norm(np.cross(axis, current_axis)), np.dot(axis, current_axis)))
        return error, jacobian, float(np.linalg.norm(error[:3])), tilt

    def task_lazy(self, q, position, axis):
        """Keep FK metadata, build J only if a next solver step needs it.

        Rejected line-search candidates and already-converged candidates do
        not need the cross products/task Jacobian. No second FK is required.
        Inputs have already been validated by solve().
        """
        pose, (world_axes, origins) = self._forward(q, 'deferred')
        current_axis = pose[:3,:3] @ self.tool_axis
        error = np.r_[position-pose[:3,3], axis-current_axis]
        pe,te = self.pose_errors(pose,position,axis)
        def jacobian():
            linear = np.cross(world_axes,pose[:3,3]-origins).T
            return np.vstack((linear,-skew(current_axis) @ world_axes.T))
        return error,jacobian,pe,te
