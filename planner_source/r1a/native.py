"""Host DLL adapter. No FPGA/MMIO/serial/motor access."""
import ctypes
from pathlib import Path
import numpy as np
from .linear import inputs, step


def quantized(j, e, w, s, mu, mode="wls"):
    j,e,w,s,mu=inputs(j,e,w,s,mu,mode)
    with np.errstate(over="raise", invalid="raise"):
        return [np.ascontiguousarray(v,dtype=np.float32) for v in (j,e,w,s)], np.float32(mu)


def python_f32_inputs(j,e,w,s,mu,mode="wls"):
    arrays,mu=quantized(j,e,w,s,mu,mode)
    return step(*[a.astype(np.float64) for a in arrays],float(mu),mode)


class NativeStep:
    def __init__(self, dll):
        self.library=ctypes.CDLL(str(Path(dll).resolve()))
        self.fn=self.library.z20_wls_step
        pointer=ctypes.POINTER(ctypes.c_float)
        self.fn.argtypes=[pointer]*4+[ctypes.c_float,ctypes.c_int,pointer]
        self.fn.restype=ctypes.c_int
        self.pointer=pointer
        self.calls=0

    def __call__(self,j,e,w,s,mu,mode="wls"):
        arrays,mu=quantized(j,e,w,s,mu,mode)
        output=np.full(5,np.nan,dtype=np.float32)
        status=self.fn(*[a.ctypes.data_as(self.pointer) for a in arrays],
                       float(mu),0 if mode=="wls" else 1,output.ctypes.data_as(self.pointer))
        self.calls+=1
        if status!=0:
            if np.any(output!=0): raise FloatingPointError("native failure retained output")
            raise FloatingPointError(f"native status={status}")
        if not np.isfinite(output).all(): raise FloatingPointError("native non-finite increment")
        return output.astype(np.float64)
