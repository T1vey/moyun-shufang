"""FP32 wire capabilities and version-bound platform checks; no hardware access."""
import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import xml.etree.ElementTree as ET
import sys
import numpy as np
from tcb705 import accel_contract as c
from tcb705 import accel_runtime as runtime
from scripts.export_tcb_register_map import extract


class CompletionTests(unittest.TestCase):
    def fixture(self,caps=3,status=0,count=3):
        ctx=np.zeros(1,dtype=c.CONTEXT);ctx['context_id']=42;ctx['options'][0,2]=20
        inputs=np.zeros(count,dtype=c.IK_INPUT);inputs['id']=np.arange(count)
        rows=np.zeros(count,dtype=c.IK_OUTPUT);rows['id']=inputs['id'];rows['generation']=7;rows['context_id']=42
        if caps==3:rows['stats'][:,:2]=np.nan
        if status==1:rows['status'][-1]=1;rows['stats'][-1]=0
        header=np.zeros(1,dtype=c.HEADER)
        values=dict(abi=c.MAGIC,status=status,job_id=8,generation=7,context_id=42,mode=c.IK_CHAIN,
                    requested=count,done_count=count,first_error=count-1 if status==1 else 0xffffffff,
                    capabilities=caps)
        for key,value in values.items():header[key]=value
        return header,rows,inputs,ctx
    def verify(self,items,expected=None):
        return c.validate_completion(*items,c.IK_CHAIN,8,7,expected_capabilities=expected)
    def test_old_finite_rows_remain_supported(self):
        h,rows=self.verify(self.fixture(0),0);self.assertEqual(h['capabilities'],0);self.assertEqual(len(rows),3)
    def test_fp32_quiet_nan_means_unknown_and_preserves_prefix(self):
        h,rows=self.verify(self.fixture(status=1),3)
        self.assertEqual(h['done_count'],3);self.assertTrue(np.isnan(rows['stats'][:2,:2]).all())
        self.assertTrue((rows['stats'][2]==0).all());self.assertEqual(rows['status'][-1],1)
    def test_identity_cannot_be_switched_by_header_flags(self):
        for wire,expected in [(3,0),(0,3)]:
            with self.subTest(wire=wire),self.assertRaisesRegex(FloatingPointError,'capability'):
                self.verify(self.fixture(wire),expected)
    def test_unknown_or_partial_capabilities_rejected(self):
        for cap in [1,2,4,0xffffffff]:
            with self.subTest(cap=cap),self.assertRaisesRegex(FloatingPointError,'capability'):
                self.verify(self.fixture(cap))
    def test_legacy_nan_and_new_infinity_or_fabricated_zero_rejected(self):
        for caps,bad in [(0,np.nan),(3,np.inf),(3,-np.inf),(3,0.)]:
            data=self.fixture(caps);data[1]['stats'][1,0]=bad
            with self.subTest(caps=caps,bad=bad),self.assertRaises(FloatingPointError):self.verify(data,caps)
    def test_signaling_nan_or_unexpected_payload_rejected(self):
        for bits in [0x7ff0000000000001,0x7ff8000000000001,0xfff8000000000000]:
            data=self.fixture();data[1]['stats'].view('<u8')[1,0]=np.uint64(bits)
            with self.subTest(bits=bits),self.assertRaises(FloatingPointError):self.verify(data,3)
    def test_nonfinite_joint_and_iteration_rejected(self):
        for field,index,bad in [('q',(0,2),np.nan),('q',(0,2),np.inf),('stats',(0,2),np.nan),('stats',(0,2),1.)]:
            data=self.fixture();data[1][field][index]=bad
            with self.subTest(field=field,bad=bad),self.assertRaises(FloatingPointError):self.verify(data,3)
    def test_reserved_header_bytes_rejected(self):
        data=self.fixture();data[0].view(np.uint8)[55]=1
        with self.assertRaisesRegex(FloatingPointError,'reserved'):self.verify(data,3)
    def test_failed_row_cannot_use_success_nan_statistics(self):
        data=self.fixture(status=1);data[1]['stats'][-1,0]=np.nan
        with self.assertRaises(FloatingPointError):self.verify(data,3)


class IdentityTests(unittest.TestCase):
    def header(self,prefix):
        lines=[];address=16
        for name,words in c.FIELDS.items():
            lines.extend([f'#define {prefix}ADDR_{name.upper()}_DATA 0x{address:x}',
                          f'#define {prefix}BITS_{name.upper()}_DATA {words*32}'])
            address+=words*4+4
        return '\n'.join(lines)
    def test_export_selects_exact_old_or_new_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'header.h'
            for prefix,abi,top in [('XTCB_PLANNER_ACCEL_CONTROL_',c.ABI,c.TOP),('XTCB_PLANNER_PARALLEL_CONTROL_',c.ABI_FP32,c.TOP_FP32)]:
                path.write_text(self.header(prefix));regs=extract(path)
                self.assertEqual((regs['abi'],regs['top']),(abi,top));c.validate_registers(regs,True)
                if abi==c.ABI_FP32:self.assertEqual(regs['supported_modes'],[1])
            regs['abi']=c.ABI
            with self.assertRaisesRegex(ValueError,'identity'):c.validate_registers(regs,True)
    def test_fp32_metadata_requires_explicit_ik_only_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'header.h';path.write_text(self.header('XTCB_PLANNER_PARALLEL_CONTROL_'))
            regs=extract(path);regs['supported_modes']=[1,2]
            with self.assertRaisesRegex(ValueError,'IK-only'):c.validate_registers(regs,True)
    def test_clock_ranges_are_bound_to_top_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.hwh'
            for top,rate,ok in [(c.TOP,76923076,True),(c.TOP,100000000,False),(c.TOP_FP32,100000000,True),(c.TOP_FP32,76923076,False)]:
                root=ET.Element('SYSTEM');m=ET.SubElement(root,'MODULE',INSTANCE=top+'_0')
                ports=ET.SubElement(m,'PORTS');ET.SubElement(ports,'PORT',NAME='ap_clk',CLKFREQUENCY=str(rate),SIGNAME='fclk1')
                ps=ET.SubElement(root,'MODULE',INSTANCE='processing_system7_0');pars=ET.SubElement(ps,'PARAMETERS')
                ET.SubElement(pars,'PARAMETER',NAME='PCW_FCLK1_PERIPHERAL_CLKSRC',VALUE='IO PLL')
                pp=ET.SubElement(ps,'PORTS');ET.SubElement(pp,'PORT',NAME='FCLK_CLK1',SIGNAME='fclk1')
                ET.ElementTree(root).write(path)
                with self.subTest(top=top,rate=rate):
                    if ok:self.assertEqual(c.clock_hz(path),rate)
                    else:
                        with self.assertRaises(ValueError):c.clock_hz(path)
    def test_physical_100mhz_is_only_allowed_for_new_identity(self):
        reader=SimpleNamespace(get_pl_clk=Mock(side_effect=[100,100]),PL_CLK_CTRLS=[None,SimpleNamespace(SRCSEL=0)])
        ps=SimpleNamespace(_ClocksZynq=Mock(return_value=reader));mmio=SimpleNamespace(read=Mock(return_value=0))
        with patch.dict(sys.modules,{'pynq.ps':ps,'pynq':SimpleNamespace(MMIO=Mock(return_value=mmio))}):
            self.assertEqual(runtime.verify_planner_clock(100000000,c.ABI_FP32),100000000)
            reader.get_pl_clk.side_effect=[100,100]
            with self.assertRaises(ValueError):runtime.verify_planner_clock(100000000,c.ABI)


class PackageIdentityTests(unittest.TestCase):
    def run_package(self, folder, prefix, export_stem):
        from scripts import package_tcb705_platform as package
        export=folder/'export';export.mkdir();out=folder/'sealed'
        (export/'build_verified.json').write_text(json.dumps(dict(setup_slack_ns=.1,hold_slack_ns=.1,drc_errors=0)))
        for stem in ('tcb705_planner','tcb705_planner_fp32'):
            if stem!=export_stem:continue
            for suffix in ('.bit','.hwh'):(export/(stem+suffix)).write_bytes((stem+suffix).encode())
        header=folder/'header.h';header.write_text(IdentityTests().header(prefix))
        argv=['package','--export',str(export),'--header',str(header),'--output',str(out),'--build-id','fixture']
        # Peripheral HWH verification is covered by platform tests; here inspect
        # actual file selection, emitted registers and manifest identity.
        with patch.object(sys,'argv',argv),patch.object(package,'validate_overlay_files',return_value=({},{})), \
             patch.object(package,'clock_hz',return_value=100000000),patch.object(package,'validate_hwh',return_value={}), \
             patch.object(package,'validate_manifest'):
            package.main()
        return out

    def test_new_and_legacy_exports_keep_distinct_names_and_identity(self):
        for prefix,stem,abi in [('XTCB_PLANNER_PARALLEL_CONTROL_','tcb705_planner_fp32',c.ABI_FP32),
                                ('XTCB_PLANNER_ACCEL_CONTROL_','tcb705_planner',c.ABI)]:
            with self.subTest(abi=abi),tempfile.TemporaryDirectory() as folder:
                out=self.run_package(Path(folder),prefix,stem)
                manifest=json.loads((out/'platform.json').read_text())
                self.assertEqual(manifest['bitfile'],stem+'.bit');self.assertEqual(manifest['accelerator_abi'],abi)
                self.assertEqual((out/(stem+'.bit')).read_bytes(),(stem+'.bit').encode())
                self.assertEqual(json.loads((out/(stem+'.registers.json')).read_text())['abi'],abi)

    def test_new_header_cannot_silently_package_legacy_bitfile(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'Missing accelerator artifact: tcb705_planner_fp32'):
                self.run_package(Path(folder),'XTCB_PLANNER_PARALLEL_CONTROL_','tcb705_planner')
            self.assertFalse((Path(folder)/'sealed').exists())


if __name__=='__main__':unittest.main()
