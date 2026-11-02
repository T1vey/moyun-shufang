import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pl_contract import ABI, TOP, ARRAYS, validate_ip, validate_registers
from pl_backend import PynqStep
from scripts.export_register_map import extract

REGS = dict(j=0x100,e=0x200,w=0x240,scales=0x280,mu=0x300,mode=0x308,dq=0x340)
REGS['return'] = 0x10


def header_text():
    rows = []
    for field, offset in REGS.items():
        suffix = 'ADDR_AP_RETURN' if field == 'return' else 'ADDR_'+field.upper()+('_BASE' if field in ARRAYS else '_DATA')
        rows.append('#define XZ20_WLS_STEP_CONTROL_'+suffix+' '+hex(offset))
    for field, count in ARRAYS.items():
        rows.extend(['#define XZ20_WLS_STEP_CONTROL_DEPTH_'+field.upper()+' '+str(count),
                     '#define XZ20_WLS_STEP_CONTROL_WIDTH_'+field.upper()+' 32'])
    return '\n'.join(rows)


class ContractTests(unittest.TestCase):
    def test_generated_map_carries_identity_and_shape_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'hw.h'
            path.write_text(header_text(),encoding='utf-8')
            actual = extract(path)
            self.assertEqual(actual['abi'],ABI)
            self.assertEqual(actual['top'],TOP)
            self.assertEqual({k:actual[k] for k in REGS},REGS)
            path.write_text(header_text().replace('CONTROL_DEPTH_J 30','CONTROL_DEPTH_J 29'),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'尺寸'):
                extract(path)

    def test_original_kernel_header_does_not_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'old_hw.h'
            path.write_text('#define XXF_SOLVER_LM_SO101_CONTROL_ADDR_SIN0_DATA 0x10',encoding='utf-8')
            with self.assertRaises(ValueError):
                extract(path)
        with self.assertRaisesRegex(ValueError,'重新导出'):
            validate_registers(REGS,require_identity=True)

    def test_ip_name_alone_cannot_spoof_kernel_type(self):
        with self.assertRaisesRegex(ValueError,'不能通过改 IP'):
            validate_ip({'type':'xilinx.com:hls:xf_solver_lm_so101:1.0','addr_range':4096},1024)
        with self.assertRaisesRegex(ValueError,'窗口'):
            validate_ip({'type':'xilinx.com:hls:z20_wls_step:1.0','addr_range':256},1024)
        validate_ip({'type':'xilinx.com:hls:z20_wls_step:1.0','addr_range':4096},1024)

    def test_bad_hwh_is_rejected_before_programming_fpga(self):
        events = []
        class Overlay:
            def __init__(self, path, download=True):
                events.append(('construct',download))
                self.ip_dict = {'z20_wls_step_0':dict(type='xilinx.com:hls:xf_solver_lm_so101:1.0',addr_range=4096)}
            def download(self):
                events.append(('download',True))
        with tempfile.TemporaryDirectory() as folder:
            bit = Path(folder)/'drawing.bit'; bit.write_bytes(b'fixture')
            bit.with_suffix('.hwh').write_text('fixture')
            bit.with_suffix('.registers.json').write_text(json.dumps(dict(REGS,abi=ABI,top=TOP)))
            with patch.dict(sys.modules,pynq=SimpleNamespace(Overlay=Overlay)):
                with self.assertRaisesRegex(ValueError,'xf_solver_lm_so101'):
                    PynqStep(bit)
        self.assertEqual(events,[('construct',False)])

    def test_validated_identity_programs_once_then_uses_matching_ip(self):
        events = []
        class Overlay:
            def __init__(self, path, download=True):
                events.append(('construct',download))
                self.ip_dict = {'z20_wls_step_0':dict(type='xilinx.com:hls:z20_wls_step:1.0',addr_range=4096)}
                self.z20_wls_step_0 = SimpleNamespace(mmio=SimpleNamespace())
            def download(self):
                events.append(('download',True))
        with tempfile.TemporaryDirectory() as folder:
            bit = Path(folder)/'drawing.bit'; bit.write_bytes(b'fixture')
            bit.with_suffix('.hwh').write_text('fixture')
            bit.with_suffix('.registers.json').write_text(json.dumps(dict(REGS,abi=ABI,top=TOP)))
            with patch.dict(sys.modules,pynq=SimpleNamespace(Overlay=Overlay)):
                core = PynqStep(bit)
        self.assertEqual(events,[('construct',False),('download',True)])
        self.assertEqual(core.calls,0)


if __name__ == '__main__':
    unittest.main()
