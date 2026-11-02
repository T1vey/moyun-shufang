"""Optional C++ graph tracing / distance checks; exact Python fallback stays available."""
import ctypes as C
import hashlib,json,os,sys,threading
from pathlib import Path
import numpy as np
ABI=0x4c4e0101
_key=None;_kernel=None;_reason='not loaded';_lock=threading.Lock()
class Kernel:
    def __init__(self,path):
        self.path=Path(path);info=json.loads(Path(str(path)+'.json').read_text())
        if info['source_sha256']!=hashlib.sha256(Path(__file__).with_suffix('.cpp').read_bytes()).hexdigest() or info['library_sha256']!=hashlib.sha256(self.path.read_bytes()).hexdigest():raise ValueError('lineart native hash mismatch')
        self.lib=C.CDLL(str(self.path.resolve()))
        self.lib.tcb_lineart_native_abi.restype=C.c_uint32
        if self.lib.tcb_lineart_native_abi()!=ABI:raise ValueError('native lineart ABI mismatch')
        self.byte=C.POINTER(C.c_uint8);self.double=C.POINTER(C.c_double)
        self.lib.tcb_lineart_graph.argtypes=[self.byte,C.c_uint,C.c_uint];self.lib.tcb_lineart_graph.restype=C.c_void_p
        self.lib.tcb_lineart_native_free.argtypes=[C.c_void_p];self.lib.tcb_lineart_native_free.restype=None
        self.lib.tcb_lineart_thin.argtypes=[self.byte,self.byte,C.c_uint,C.c_uint];self.lib.tcb_lineart_thin.restype=C.c_int
        self.lib.tcb_lineart_max_distance.argtypes=[self.double,C.c_uint,self.double,C.c_uint,C.c_double];self.lib.tcb_lineart_max_distance.restype=C.c_double
    def graph(self,mask):
        a=np.array(mask,dtype=np.uint8,order='C',copy=True)
        if a.ndim!=2:raise ValueError('skeleton must be 2D')
        pointer=self.lib.tcb_lineart_graph(a.ctypes.data_as(self.byte),a.shape[1],a.shape[0])
        if not pointer:raise ValueError('native graph rejected input')
        try:data=json.loads(C.string_at(pointer))
        finally:self.lib.tcb_lineart_native_free(pointer)
        return data['trails'],data['graph']
    def thin(self,mask):
        a=np.array(mask,dtype=bool,order='C',copy=True).astype(np.uint8);out=np.zeros_like(a)
        if a.ndim!=2:raise ValueError('mask must be 2D')
        count=self.lib.tcb_lineart_thin(a.ctypes.data_as(self.byte),out.ctypes.data_as(self.byte),a.shape[1],a.shape[0])
        if count<0:raise ValueError('native thinning failed: '+str(count))
        return out.astype(bool),count
    def distance(self,points,chain,stop):
        a=np.array(points,dtype=np.float64,order='C',copy=True);b=np.array(chain,dtype=np.float64,order='C',copy=True)
        if a.ndim!=2 or b.ndim!=2 or a.shape[1]!=2 or b.shape[1]!=2 or len(b)<2:raise ValueError('invalid distance input')
        value=self.lib.tcb_lineart_max_distance(a.ctypes.data_as(self.double),len(a),b.ctypes.data_as(self.double),len(b),stop)
        if not np.isfinite(value):raise ValueError('native distance failed')
        return value
def get_kernel():
    global _key,_kernel,_reason
    path=os.environ.get('TCB705_NATIVE_LINEART_LIBRARY') or str(Path(__file__).parent/'build'/('tcb_lineart.dll' if sys.platform=='win32' else 'libtcb_lineart.so'))
    key=(os.environ.get('TCB705_NATIVE_LINEART','auto'),path)
    with _lock:
        if key!=_key:
            _key=key;_kernel=None
            try:
                if key[0]=='off':raise ValueError('disabled')
                _kernel=Kernel(path);_reason='C++ loaded'
            except (OSError,ValueError,KeyError,AttributeError) as exc:_reason=str(exc)
        return _kernel
def status():
    core=get_kernel();return dict(enabled=core is not None,reason=_reason,abi=ABI)
