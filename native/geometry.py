"""Optional bounded FP64 C kernels; authoritative polynomial/count code stays Python.

SO101_NATIVE_GEOMETRY=off disables loading. SO101_NATIVE_LIBRARY overrides the
local native/build library. Missing/incompatible libraries safely use NumPy.
Model/data buffers are copied and frozen before releasing the GIL into ctypes.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import numpy as np

ABI = 0x534e0101
MAX_ROWS = 1024
_lock = threading.RLock()
_key = None
_kernel = None
_reason = 'not loaded'


class Kernel:
    def __init__(self, path):
        self.path = str(Path(path).resolve())
        source = Path(__file__).with_suffix('.cpp')
        manifest = json.loads(Path(self.path+'.json').read_text(encoding='utf-8'))
        if (manifest.get('source_sha256') != hashlib.sha256(source.read_bytes()).hexdigest()
                or manifest.get('library_sha256') != hashlib.sha256(Path(self.path).read_bytes()).hexdigest()):
            raise ValueError('native geometry build manifest/source mismatch')
        self.lib = ctypes.CDLL(self.path)
        self.lib.so101_geometry_abi.argtypes = []
        self.lib.so101_geometry_abi.restype = ctypes.c_uint32
        self.lib.so101_geometry_fp64.argtypes = []
        self.lib.so101_geometry_fp64.restype = ctypes.c_int
        if self.lib.so101_geometry_abi() != ABI or self.lib.so101_geometry_fp64() != 1:
            raise ValueError('native geometry ABI/FP64 environment mismatch')
        self.ptr = ctypes.POINTER(ctypes.c_double)
        self.pose_fn = self.lib.so101_pose_rows
        self.pose_fn.argtypes = [self.ptr, self.ptr, ctypes.c_uint32, self.ptr]
        self.pose_fn.restype = ctypes.c_int
        self.geometry_fn = self.lib.so101_geometry_rows
        self.geometry_fn.argtypes = [self.ptr]*6+[ctypes.c_uint32, self.ptr]
        self.geometry_fn.restype = ctypes.c_int

    def pointer(self, a):
        return a.ctypes.data_as(self.ptr)


def get_kernel():
    global _key, _kernel, _reason
    mode = os.environ.get('SO101_NATIVE_GEOMETRY', 'auto').lower()
    filename = ('so101_geometry.dll' if sys.platform == 'win32' else
                'libso101_geometry.dylib' if sys.platform == 'darwin' else 'libso101_geometry.so')
    path = os.environ.get('SO101_NATIVE_LIBRARY') or str(Path(__file__).parent/'build'/filename)
    key = mode, path
    with _lock:
        if key != _key:
            _key, _kernel = key, None
            if mode == 'off':
                _reason = 'disabled'
            else:
                try:
                    _kernel = Kernel(path)
                    _reason = 'FP64 C ABI loaded'
                except (OSError, AttributeError, ValueError) as exc:
                    _reason = str(exc)
        return _kernel


def status():
    core = get_kernel()
    return dict(enabled=core is not None, abi=ABI, precision='float64',
                library=core.path if core else None, reason=_reason, batch_limit=MAX_ROWS)


def _frozen(value, shape):
    a = np.array(value, dtype=np.float64, order='C', copy=True)
    if a.shape != shape or not np.isfinite(a).all():
        raise ValueError('invalid native geometry input')
    a.flags.writeable = False
    return a


def _model(model):
    # Do not retain an old snapshot when callers deliberately edit a model.
    values = [_frozen(v, shape).reshape(-1) for v, shape in
              ((model.offsets, (5, 3)), (model.axes, (5, 3)),
               (model.tool, (3,)), (model.tool_axis, (3,)))]
    frozen = np.concatenate(values)
    frozen.flags.writeable = False
    return frozen


def pose_many(model, joints):
    core = get_kernel()
    if core is None:
        return None
    n = len(joints)
    q = _frozen(joints, (n, 5)); m = _model(model)
    result = np.empty((n, 4, 4), dtype=np.float64)
    for start in range(0, n, MAX_ROWS):
        end = min(n, start+MAX_ROWS)
        if core.pose_fn(core.pointer(m), core.pointer(q[start:end]), end-start,
                        core.pointer(result[start:end])) != 0:
            return None  # Never expose partial/invalid native output.
    return result


def geometry_rows(model, joints, starts, deltas, desired, axes):
    core = get_kernel()
    if core is None:
        return None
    n = len(joints); m = _model(model)
    arrays = [_frozen(v, (n, width)) for v, width in
              ((joints, 5), (starts, 3), (deltas, 3), (desired, 3), (axes, 3))]
    result = np.empty((n, 6), dtype=np.float64)
    for start in range(0, n, MAX_ROWS):
        end = min(n, start+MAX_ROWS)
        args = [core.pointer(m)]+[core.pointer(a[start:end]) for a in arrays]
        if core.geometry_fn(*args, end-start, core.pointer(result[start:end])) != 0:
            return None
    return result[:, :3], result[:, 3], result[:, 4], result[:, 5]
