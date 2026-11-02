"""Bounded directional stroke matching. Scores are distances, NOT probabilities."""
import ctypes as ct
import math
from functools import lru_cache
from pathlib import Path
import sys
import numpy as np
from .templates import CENTERLINES, VERSION

MAX_POINTS = 2048
N = 64

def points(value):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_POINTS:
        raise ValueError('每笔需 1～2048 个采样点')
    if any(not isinstance(p, (list, tuple)) or len(p) not in (2, 3) or
           any(type(v) not in (int, float) or not math.isfinite(v) for v in p) for p in value):
        raise ValueError('笔画坐标必须是有限数')
    a = np.asarray([p[:2] for p in value], dtype=float)
    if np.any(a < 0) or np.any(a > 1):raise ValueError('笔画超出字框')
    return a

def resample(a, n=N):
    a = np.asarray(a, dtype=float)
    a = a[np.r_[True, np.linalg.norm(np.diff(a, axis=0), axis=1) > 1e-10]]
    if len(a) == 1:return np.repeat(a, n, axis=0)
    s = np.r_[0., np.cumsum(np.linalg.norm(np.diff(a, axis=0), axis=1))]
    t = np.linspace(0, s[-1], n)
    return np.column_stack([np.interp(t, s, a[:, k]) for k in (0, 1)])

def normalized(a):
    lo, hi = a.min(axis=0), a.max(axis=0)
    return (a - (lo+hi)/2) / max(float((hi-lo).max()), 1e-8)

def features(a):
    d = a[-1]-a[0];d /= max(np.linalg.norm(d), 1e-8)
    v = np.diff(a[::4], axis=0);v /= np.maximum(np.linalg.norm(v, axis=1)[:, None], 1e-8)
    turn = np.arctan2(v[:-1, 0]*v[1:, 1]-v[:-1, 1]*v[1:, 0], (v[:-1]*v[1:]).sum(axis=1))
    extent = np.ptp(a, axis=0)
    return d, float(np.abs(turn).sum()/math.pi), float(extent[0]/max(extent.sum(), 1e-8))

@lru_cache(maxsize=1)
def bank():
    from calligraphy.library import STROKES
    if set(CENTERLINES) != set(STROKES):raise ValueError('识别与执行模板 ID 不一致')
    result = []
    for key, line in CENTERLINES.items():
        raw = np.asarray(line, dtype=float)
        for skew in (0., -.06, .06):
            a = raw.copy();a[:, 0] += skew*(a[:, 1]-a[0, 1])
            a = normalized(resample(a));a.setflags(write=False)
            result.append((key, a, features(a)))
    return tuple(result)

@lru_cache(maxsize=1)
def bank_arrays():
    rows=bank()
    return (np.stack([r[1] for r in rows]),np.stack([r[2][0] for r in rows]),
            np.array([r[2][1] for r in rows]),np.array([r[2][2] for r in rows]))

def dtw_python(a, b):
    costs = np.linalg.norm(a[:, None]-b[None, :], axis=2)
    prev = np.full(N+1, np.inf);prev[0] = 0.
    for i in range(1, N+1):
        row = np.full(N+1, np.inf)
        for j in range(max(1, i-8), min(N, i+8)+1):
            row[j] = costs[i-1, j-1]+min(prev[j], row[j-1], prev[j-1])
        prev = row
    return float(prev[-1]/N)

@lru_cache(maxsize=1)
def native():
    path = Path(__file__).resolve().parents[1]/'build/handwriting'/('handwriting.dll' if sys.platform=='win32' else 'libhandwriting.so')
    if not path.is_file():return None
    lib = ct.CDLL(str(path));lib.hw_dtw.argtypes = [ct.POINTER(ct.c_double)]*2
    lib.hw_dtw.restype = ct.c_double
    return lib

def dtw(a, b):
    lib = native()
    if lib is None:return dtw_python(a, b)
    a = np.ascontiguousarray(a);b = np.ascontiguousarray(b)
    return lib.hw_dtw(a.ctypes.data_as(ct.POINTER(ct.c_double)), b.ctypes.data_as(ct.POINTER(ct.c_double)))

def recognize(raw):
    from calligraphy.library import STROKES
    a = points(raw);extent = float(np.ptp(a, axis=0).max())
    length = float(np.linalg.norm(np.diff(a, axis=0), axis=1).sum())
    if extent < .018 and length < .055:
        return dict(module='dian', name=STROKES['dian'][0], score=0., ambiguous=False, version=VERSION)
    a = normalized(resample(a));direction, turns, aspect = features(a)
    templates,directions,all_turns,aspects=bank_arrays()
    extras=.15*np.linalg.norm(direction-directions,axis=1)/2+.15*np.minimum(abs(turns-all_turns)/3,1)+.10*abs(aspect-aspects)
    coarse=.60*np.linalg.norm(a[None]-templates,axis=2).mean(axis=1)+extras
    ranked=[(float(coarse[i]),key,template,float(extras[i])) for i,(key,template,_) in enumerate(bank())]
    ranked.sort(key=lambda x: x[0])
    # Compare distinct classes, so three perturbations cannot monopolise top 5.
    candidates = [];seen = set()
    for row in ranked:
        if row[1] not in seen:candidates.append(row);seen.add(row[1])
        if len(candidates) == 5:break
    scores = sorted((.60*dtw(a, t)+extra, i, k) for i, (_, k, t, extra) in enumerate(candidates))
    score, _, key = scores[0]
    if key in ('heng', 'duan_heng'):key = 'duan_heng' if extent < .32 else 'heng'
    if key in ('shu_chuilu', 'shu_xuanzhen', 'duan_shu'):key = 'duan_shu' if extent < .32 else 'shu_chuilu'
    if key in ('dian', 'chang_dian'):key = 'chang_dian' if extent > .32 else 'dian'
    return dict(module=key, name=STROKES[key][0], score=round(float(score), 6),
                ambiguous=bool(scores[1][0]-score < .025), version=VERSION)
