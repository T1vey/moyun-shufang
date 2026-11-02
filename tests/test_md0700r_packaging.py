"""No-device-tree userspace platform contract and packaging regression tests."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import md0700r_contract as display
from platform_runtime import validate_manifest


def make_fixture(folder):
    # Share only the synthetic accelerator fixture; no real bitstream is needed.
    spec=importlib.util.spec_from_file_location('planner_platform_fixture',ROOT/'tests/test_planner_platform.py')
    fixture_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture_module)
    bit,_,_=fixture_module.fixture(folder)
    tree=ET.parse(bit.with_suffix('.hwh'));root=tree.getroot()
    params={
        'clock':{'C_CLKOUT0_ACTUAL_FREQ':'51.20000','C_NUM_OUT_CLKS':'1'},
        'lcd_id':{'C_GPIO_WIDTH':'3','C_IS_DUAL':'0'},
        'pwm':{'NUM_PWM':'1','C_PWM_AXI_DATA_WIDTH':'32'},
        'vtc':{'C_GENERATE_EN':'1','C_HAS_AXI4_LITE':'1'},
        'framebuffer':{'C_M_AXI_MM_VIDEO_ADDR_WIDTH':'32','SAMPLES_PER_CLOCK':'1','HAS_BGR8':'1','MAX_DATA_WIDTH':'8'},
        'reset_touch':{'C_IS_DUAL':'1','C_GPIO_WIDTH':'3','C_ALL_OUTPUTS':'1','C_GPIO2_WIDTH':'32','C_ALL_INPUTS_2':'1'},
    }
    modules={}
    for key,(name,base,vlnv) in display._IPS.items():
        module=ET.SubElement(root,'MODULE',INSTANCE=name,VLNV=vlnv);modules[key]=module
        values=ET.SubElement(module,'PARAMETERS')
        for name,value in params[key].items():ET.SubElement(values,'PARAMETER',NAME=name,VALUE=value)
        ET.SubElement(root,'MEMRANGE',INSTANCE=module.get('INSTANCE'),BASEVALUE=hex(base),HIGHVALUE=hex(base+65535))
    module=ET.SubElement(root,'MODULE',INSTANCE='touch_pl',VLNV='xilinx.com:module_ref:gt911_pl_bridge:1.0')
    ports=ET.SubElement(module,'PORTS')
    ET.SubElement(ports,'PORT',NAME='packet',DIR='O',LEFT='31',RIGHT='0',SIGNAME='touch_packet')
    ET.SubElement(ports,'PORT',NAME='clk',CLKFREQUENCY='100000000')
    ET.SubElement(ET.SubElement(modules['reset_touch'],'PORTS'),'PORT',NAME='gpio2_io_i',DIR='I',LEFT='31',RIGHT='0',SIGNAME='touch_packet')
    ET.SubElement(ET.SubElement(modules['vtc'],'PORTS'),'PORT',NAME='clk',CLKFREQUENCY='51200000')
    tree.write(bit.with_suffix('.hwh'))
    return bit


class MD0700RContractTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.folder=Path(tmp.name)
        self.bit=make_fixture(self.folder);self.hwh=self.bit.with_suffix('.hwh')

    def test_valid_and_fresh_contract(self):
        value=display.validate_hwh(self.hwh)
        self.assertEqual(value,display.expected_contract())
        value['ips']['clock']['base']=0
        self.assertEqual(display.expected_contract()['ips']['clock']['base'],0x43C30000)

    def test_rejects_wrong_register_window_gpio_clock_format_and_touch_connection(self):
        original=self.hwh.read_bytes()
        for failure in ('address','dual_gpio','bgr8','pixel_clock','packet','missing_touch','duplicate_module'):
            with self.subTest(failure=failure):
                root=ET.fromstring(original)
                if failure=='address':
                    next(r for r in root.iter('MEMRANGE') if r.get('INSTANCE')=='rest_gpio').set('BASEVALUE','0x41230000')
                elif failure in ('dual_gpio','bgr8','pixel_clock'):
                    key={'dual_gpio':'C_IS_DUAL','bgr8':'HAS_BGR8','pixel_clock':'C_CLKOUT0_ACTUAL_FREQ'}[failure]
                    instance={'dual_gpio':'rest_gpio','bgr8':'lcd_out_v_frmbuf_rd_0','pixel_clock':'clk_wiz_0'}[failure]
                    module=next(m for m in root.iter('MODULE') if m.get('INSTANCE')==instance)
                    next(p for p in module.iter('PARAMETER') if p.get('NAME')==key).set('VALUE','0')
                elif failure=='packet':
                    next(p for p in root.iter('PORT') if p.get('NAME')=='gpio2_io_i').set('SIGNAME','unrelated')
                else:
                    module=next(m for m in root.iter('MODULE') if m.get('INSTANCE')=='touch_pl')
                    if failure=='missing_touch':root.remove(module)
                    else:root.append(ET.fromstring(ET.tostring(module)))
                ET.ElementTree(root).write(self.hwh)
                with self.assertRaises(ValueError):display.validate_hwh(self.hwh)

    def packager_args(self):
        export=self.folder/'export';export.mkdir()
        for suffix in ('.bit','.hwh'):(export/('drawing_planner'+suffix)).write_bytes(self.bit.with_suffix(suffix).read_bytes())
        (export/'timing_summary.rpt').write_text('UNIT TEST FIXTURE NOT ACTUAL TIMING')
        (export/'accelerator_mode.txt').write_text('planner\n')
        return [sys.executable,str(ROOT/'hw/md0700r/package_platform.py'),'--export',str(export),
                '--registers',str(self.bit.with_suffix('.registers.json')),'--build-id','unit-test',
                '--output',str(self.folder/'package'),'--accelerator-mode','planner']

    def test_default_userspace_package_is_complete_without_dtbo_or_kernel_binding(self):
        result=subprocess.run(self.packager_args(),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        folder=self.folder/'package'
        cfg,_,dtbo,*_=validate_manifest(folder/'platform.json','any-running-kernel')
        self.assertEqual(cfg['display_backend'],'pynq-mmio')
        self.assertEqual(cfg['touch_backend'],'gt911-pl-gpio')
        self.assertEqual(cfg['display_contract'],display.expected_contract())
        self.assertEqual(cfg['board_acceptance'],'NOT_RUN')
        self.assertIsNone(cfg['kernel_release']);self.assertIsNone(cfg['dtbo']);self.assertIsNone(dtbo)
        self.assertFalse(list(folder.glob('*.dtbo')))

    def test_userspace_rejects_dtbo_and_kernel_binding_before_creating_output(self):
        args=self.packager_args()
        for extra in (['--dtbo',str(self.folder/'display.dtbo')],['--kernel-release','unverified']):
            result=subprocess.run(args+extra,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('must not include',result.stderr)
            self.assertFalse((self.folder/'package').exists())


if __name__=='__main__':unittest.main()
