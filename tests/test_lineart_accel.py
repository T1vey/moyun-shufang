import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import lineart_contract as c
from lineart_backend import LineartPL,thin_or_cpu,last_metrics
from stroke_paths import _thin_cpu,_graph_trails_python
from tools.lineart_vectors import passes

REG={'abi':c.ABI,'top':c.TOP,'return':16,'src':24,'dst':36,'width':48,'height':56,'deleted':64,'identity':72}
class Buffer(np.ndarray):
    def __new__(cls,n,address):
        obj=np.zeros(n,np.uint64).view(cls);obj.physical_address=address;obj.freed=False;obj.flushed=False;obj.invalidated=False;return obj
    def flush(self):self.flushed=True
    def invalidate(self):self.invalidated=True
    def freebuffer(self):self.freed=True
class Lease:
    pending=False;closed=False
    def claim(self,c):pass
    def release_claim(self,c):pass
    def assert_owned(self,base):assert base==c.BASE
    def mark_inflight(self,*args):self.pending=True
    def mark_drained(self):self.pending=False
    def close(self):self.closed=True
class Device:
    def __init__(self,hang=False):self.reg={0:4};self.buffers={};self.hang=hang
    def allocate(self,shape,dtype):
        a=Buffer(shape,0x100000+len(self.buffers)*0x100000);self.buffers[a.physical_address]=a;return a
    def read(self,address):
        value=self.reg.get(address,0)
        if address==0:self.reg[0]&=~2
        return value
    def write(self,address,value):
        self.reg[address]=value
        if address!=0:return
        if self.hang:self.reg[0]=0;return
        src=self.buffers[self.reg[REG['src']]];dst=self.buffers[self.reg[REG['dst']]]
        shape=(self.reg[REG['height']],self.reg[REG['width']]);mask=c.unpack_mask(src,shape)
        out=passes(mask,1);dst[:]=c.pack_mask(out)
        self.reg.update({REG['deleted']:int(mask.sum()!=out.sum()),REG['identity']:c.IDENTITY,REG['return']:0,0:6})

class LineartTransport(unittest.TestCase):
    def test_packing_nonbyte_rows(self):
        rng=np.random.default_rng(12)
        for shape in [(1,1),(2,7),(3,65),(64,1536),(1536,1)]:
            a=rng.random(shape)>.5;p=c.pack_mask(a)
            self.assertTrue(np.array_equal(c.unpack_mask(p,shape),a))
            self.assertFalse(np.unpackbits(p.view(np.uint8),bitorder='little')[a.size:].any())
    def test_convergence_and_dma_lifetime(self):
        a=np.ones((71,77),bool);dev=Device();lease=Lease()
        out,m=LineartPL(dev,REG,dev.allocate,lease).thin(a)
        np.testing.assert_array_equal(out,_thin_cpu(a));self.assertGreater(m['passes'],1)
        self.assertTrue(lease.closed);self.assertFalse(lease.pending)
        self.assertTrue(all(b.freed and b.flushed for b in dev.buffers.values()))
        self.assertTrue(any(b.invalidated for b in dev.buffers.values()))
    def test_timeout_pins_buffers_and_lease(self):
        dev=Device(hang=True);lease=Lease();core=LineartPL(dev,REG,dev.allocate,lease,timeout_s=.001)
        with self.assertRaises(TimeoutError):core.thin(np.ones((4,5),bool))
        self.assertTrue(lease.pending);self.assertFalse(lease.closed);self.assertTrue(core.poisoned)
        self.assertTrue(all(not b.freed for b in dev.buffers.values()))
    def test_fallback_from_missing_core_is_exact(self):
        a=np.ones((17,21),bool)
        with patch.dict(os.environ,{'TCB705_LINEART':'auto'}),patch('lineart_backend.capability',return_value={'available':True}),patch('lineart_backend.open_accelerator',side_effect=ValueError('old platform')):
            np.testing.assert_array_equal(thin_or_cpu(a,_thin_cpu),_thin_cpu(a))
            self.assertEqual(last_metrics()['fallback_reason'],'old platform')
        with patch.dict(os.environ,{'TCB705_LINEART':'pl'}),patch('lineart_backend.capability',return_value={'available':True}),patch('lineart_backend.open_accelerator',side_effect=ValueError('old platform')):
            with self.assertRaises(ValueError):thin_or_cpu(a,_thin_cpu)
    def test_mapping_rejects_overlap(self):
        bad={**REG,'dst':28}
        with self.assertRaises(ValueError):c.validate_registers(bad)
    def test_invalid_input_releases_claim_before_dma(self):
        dev=Device();lease=Lease();core=LineartPL(dev,REG,dev.allocate,lease)
        with self.assertRaises(ValueError):core.thin(np.ones((2,1537),bool))
        self.assertTrue(lease.closed);self.assertFalse(lease.pending)
        self.assertEqual(dev.buffers,{})
    def test_generated_hls_register_header(self):
        from scripts.export_lineart_register_map import extract
        header=ROOT/'hw/ip/lineart/drivers/tcb_lineart_accel_v1_0/src/xtcb_lineart_accel_hw.h'
        registers=extract(header)
        self.assertEqual(registers['return'],0x10)
        self.assertEqual(registers['src'],0x18);self.assertEqual(registers['dst'],0x24)
        self.assertEqual(registers['identity'],0x50)

class NativeLineart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from native.lineart import get_kernel
        cls.core=get_kernel()
        if cls.core is None:raise unittest.SkipTest('build native/build_lineart.py first')
    def test_random_masks_exact_thin_graph(self):
        rng=np.random.default_rng(20261020)
        for index in range(100):
            a=rng.random((int(rng.integers(1,60)),int(rng.integers(1,60))))>float(rng.uniform(.1,.9))
            expected=_thin_cpu(a);out,_=self.core.thin(a)
            np.testing.assert_array_equal(out,expected)
            self.assertEqual(self.core.graph(out),_graph_trails_python(out),index)
    def test_distance_equal(self):
        from path_quality import _max_distance_python
        rng=np.random.default_rng(51)
        for _ in range(20):
            a=rng.random((300,2));b=rng.random((80,2))
            self.assertEqual(self.core.distance(a,b,.2),_max_distance_python(a,b,.2))

if __name__=='__main__':unittest.main()
