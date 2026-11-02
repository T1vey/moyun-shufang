"""Attach-only thinning. Timeout quarantines DMA memory until a platform reboot."""
import os
import hashlib
import json
from pathlib import Path
import stat
import threading
import time
import numpy as np
import lineart_contract as c

_quarantine=[]
_metrics=threading.local()
_attachment_lock=threading.Lock()
_attachment=None
_capability_lock=threading.Lock()
_capability_cache=None


def _file_signature(path):
    path=Path(path)
    try:
        info=path.stat()
        return (str(path),info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
    except OSError:
        return (str(path),None)


def capability():
    """Cheap, cached capability gate; never map registers or attach an overlay.

    An absent lineart block is a normal CPU configuration. Recheck only when
    the release, boot receipt, HWH or register metadata changes. A positive
    result is only eligibility: open_accelerator still verifies sealed bytes
    and the loaded platform identity before every hardware attachment.
    """
    global _capability_cache
    from tcb705.accel_runtime import platform_manifest
    from platform_runtime import READY,BOOT_ID
    manifest=platform_manifest()
    roots=(() if manifest is None else (manifest,))+(Path(READY),Path(BOOT_ID))
    # Linux/SD filesystems may give consecutive same-size writes identical
    # timestamps. Read only these tiny identity files, never the bitstream,
    # so a changed boot/receipt cannot reuse stale capability metadata.
    try:boot_id=Path(BOOT_ID).read_text().strip()
    except OSError:boot_id=None
    try:receipt_bytes=Path(READY).read_bytes()
    except OSError:receipt_bytes=None
    receipt_digest=hashlib.sha256(receipt_bytes).digest() if receipt_bytes is not None else None
    key=(os.getpid(),str(manifest),tuple(_file_signature(p) for p in roots),boot_id,receipt_digest)
    with _capability_lock:
        if _capability_cache is not None:
            saved,dependencies,fingerprints,result=_capability_cache
            if saved==key and fingerprints==tuple(_file_signature(p) for p in dependencies):
                return dict(result)
        dependencies=()
        try:
            if manifest is None:raise ValueError('lineart platform is not configured')
            raw=manifest.read_bytes();cfg=json.loads(raw)
            if cfg.get('lineart') is None:
                raise ValueError('loaded platform has no lineart accelerator; CPU selected')
            bit_name=cfg.get('bitfile','')
            if not bit_name or Path(bit_name).name!=bit_name:raise ValueError('invalid platform bitfile')
            bit=manifest.parent/bit_name
            dependencies=(bit.with_suffix('.hwh'),manifest.parent/'tcb_lineart.registers.json')
            loaded=json.loads(receipt_bytes)
            if (loaded.get('manifest_sha256')!=hashlib.sha256(raw).hexdigest() or
                    loaded.get('build_id')!=cfg.get('build_id') or
                    loaded.get('boot_id')!=boot_id or
                    loaded.get('self_test')!='PASS'):
                raise ValueError('lineart platform is not loaded for this boot/release')
            entry,_=c.validate_manifest_section(cfg,manifest.parent,bit)
            result=dict(available=True,backend='PL',ip_name=entry['ip_name'],build_id=cfg.get('build_id'))
        except Exception as exc:
            result=dict(available=False,backend='CPU',reason=str(exc))
        _capability_cache=(key,dependencies,tuple(_file_signature(p) for p in dependencies),result)
        return dict(result)

def _attachment_key(manifest):
    """Rehash sealed bytes and the boot receipt on every use, without XML parsing."""
    from platform_runtime import READY,BOOT_ID,digest
    raw=manifest.read_bytes();cfg=json.loads(raw)
    files=cfg.get('files')
    if not isinstance(files,dict) or not files:raise ValueError('platform files are not sealed')
    hashes=[]
    for name,expected in sorted(files.items()):
        candidate=(manifest.parent/name).resolve()
        if Path(name).name!=name or candidate.parent!=manifest.parent:
            raise ValueError('invalid sealed platform path')
        actual=digest(candidate)
        if actual!=expected:raise ValueError('platform file hash mismatch: '+name)
        hashes.append((name,actual))
    receipt=Path(READY);info=receipt.stat()
    if hasattr(os,'geteuid') and (info.st_uid!=0 or info.st_mode&(stat.S_IWGRP|stat.S_IWOTH)):
        raise ValueError('platform receipt must be root-owned and not publicly writable')
    return (os.getpid(),str(manifest),hashlib.sha256(raw).hexdigest(),tuple(hashes),
            hashlib.sha256(receipt.read_bytes()).hexdigest(),Path(BOOT_ID).read_text().strip())

def _attached_metadata(manifest):
    """Cache parsed/validated metadata only; DMA buffers and leases are never cached."""
    global _attachment
    from tcb705.accel_runtime import attached_identity,ps_ddr_allocator
    with _attachment_lock:
        key=_attachment_key(manifest)
        if _attachment is not None and _attachment[0]==key:return _attachment[1]
        cfg,_,_,_,_=attached_identity()
        bit=manifest.parent/cfg['bitfile']
        section=c.validate_manifest_section(cfg,manifest.parent,bit)
        if section is None:raise ValueError('loaded platform has no lineart accelerator')
        entry,registers=section
        from pynq import Overlay
        overlay=Overlay(str(bit),download=False)
        metadata=(cfg,entry,registers,ps_ddr_allocator(overlay))
        if _attachment_key(manifest)!=key:raise ValueError('platform changed while attaching lineart')
        _attachment=(key,metadata)
        return metadata
def last_metrics():return getattr(_metrics,'value',{}).copy()

class LineartPL:
    def __init__(self,mmio,registers,allocator,lease,timeout_s=2.):
        c.validate_registers(registers)
        if not np.isfinite(timeout_s) or timeout_s<=0:raise ValueError('invalid lineart timeout')
        self.mmio,self.regs,self.allocate,self.lease=mmio,registers,allocator,lease
        self.timeout_s=float(timeout_s);self.buffers=[];self.poisoned=False
        lease.claim(self)
    def write(self,name,value):self.mmio.write(self.regs[name],int(value))
    def read(self,name):return int(self.mmio.read(self.regs[name]))
    def address(self,name,buffer):
        address=int(buffer.physical_address)
        if address%8 or address<0 or address+buffer.nbytes>2**32:raise ValueError('invalid CMA address')
        self.write(name,address);self.mmio.write(self.regs[name]+4,0)
    def thin(self,mask):
        try:
            packed=c.pack_mask(mask);shape=np.asarray(mask).shape;started=time.perf_counter()
            self.lease.assert_owned(c.BASE)
            for _ in range(2):self.buffers.append(self.allocate(shape=packed.shape,dtype=np.uint64))
            a,b=self.buffers
            if np.shares_memory(a,b) or int(a.physical_address)==int(b.physical_address):raise ValueError('lineart buffers must be disjoint')
            a[:]=packed;a.flush()
            # Also evict dirty destination cache lines before hardware owns DDR.
            b[:]=0;b.flush()
            limit=(2*(max(shape)+2)+c.STAGES-1)//c.STAGES+1
            for iteration in range(limit):
                if not (self.mmio.read(0)&4):raise RuntimeError('lineart accelerator not idle')
                self.address('src',a);self.address('dst',b)
                self.write('width',shape[1]);self.write('height',shape[0])
                self.lease.mark_inflight(iteration+1,1)
                self.mmio.write(0,1)
                deadline=time.monotonic()+self.timeout_s
                while True:
                    control=self.mmio.read(0)
                    if control&2:
                        # ap_done confirms completion; independently require no pending AXI.
                        if not control&4:
                            while not self.mmio.read(0)&4:
                                if time.monotonic()>deadline:raise TimeoutError('lineart did not become idle')
                        break
                    if time.monotonic()>deadline:raise TimeoutError('lineart DMA timeout; reboot before PL reuse')
                    time.sleep(.0002)
                self.lease.mark_drained()
                if self.read('identity')!=c.IDENTITY or self.read('return')!=0:raise RuntimeError('lineart hardware identity/status mismatch')
                deleted=self.read('deleted')
                if deleted not in (0,1):raise RuntimeError('invalid lineart deletion flag')
                a,b=b,a
                if deleted==0:
                    a.invalidate()
                    result=c.unpack_mask(a,shape)
                    if np.any(result & ~np.asarray(mask,dtype=bool)):raise RuntimeError('PL added foreground pixels')
                    return result,dict(backend='PL',passes=iteration+1,subiterations=(iteration+1)*c.STAGES,seconds=time.perf_counter()-started)
            raise RuntimeError('lineart thinning did not converge')
        finally:
            if self.lease.pending:
                self.poisoned=True;_quarantine.append(self)
            else:
                for buffer in self.buffers:buffer.freebuffer()
                self.buffers=[]
                self.lease.release_claim(self);self.lease.close()

def open_accelerator():
    from tcb705.accel_runtime import platform_manifest,ensure_event_loop,verify_planner_clock
    from planner_accel_lease import acquire_planner_lease
    state=capability()
    if not state['available']:raise ValueError(state['reason'])
    ensure_event_loop()
    manifest=platform_manifest()
    if manifest is None:raise ValueError('lineart platform is not configured')
    lease=acquire_planner_lease(c.BASE)
    try:
        cfg,entry,registers,allocate=_attached_metadata(manifest)
        from pynq import MMIO
        verify_planner_clock(cfg['accelerator_clock_hz'],cfg.get('accelerator_abi','tcb705-planner-accel-v1'))
        return LineartPL(MMIO(entry['base'],entry['size']),registers,allocate,lease)
    except BaseException:
        lease.close();raise

def prepare():
    """Warm metadata in the service process before uploads; never start DMA."""
    if os.environ.get('TCB705_LINEART','auto').lower()=='cpu':return {'ready':False,'reason':'CPU selected'}
    started=time.perf_counter()
    state=capability()
    if not state['available']:
        return dict(ready=False,reason=state['reason'],seconds=time.perf_counter()-started)
    try:
        core=open_accelerator()
        core.lease.release_claim(core);core.lease.close()
        return {'ready':True,'seconds':time.perf_counter()-started}
    except Exception as exc:
        return {'ready':False,'reason':str(exc),'seconds':time.perf_counter()-started}

def thin_or_cpu(binary,cpu):
    source=np.asarray(binary,dtype=bool)
    if source.ndim!=2:raise ValueError('中心线输入必须是二维图像')
    mode=os.environ.get('TCB705_LINEART','auto').lower()
    if mode not in ('auto','cpu','pl'):raise ValueError('TCB705_LINEART must be auto/cpu/pl')
    started=time.perf_counter();reason=None
    if mode!='cpu' and source.size and all(d<=c.MAX_DIM for d in source.shape):
        state=capability()
        if not state['available']:
            reason=state['reason']
            if mode=='pl':raise ValueError(reason)
        else:
            try:
                result,metrics=open_accelerator().thin(source)
                _metrics.value=metrics;return result
            except Exception as exc:
                reason=str(exc)
                if mode=='pl':raise
    elif mode=='pl':raise ValueError('image exceeds lineart PL dimensions')
    result=cpu(source)
    _metrics.value=dict(backend='CPU',fallback_reason=reason,seconds=time.perf_counter()-started)
    return result
