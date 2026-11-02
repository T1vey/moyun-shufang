import hashlib,json,os,sys,tempfile,unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import lineart_backend as b


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.manifest=self.root/'platform.json'
        self.ready=self.root/'ready.json';self.boot=self.root/'boot_id';self.boot.write_text('boot-a')
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('tcb705.accel_runtime.platform_manifest',return_value=self.manifest))
        self.stack.enter_context(patch('platform_runtime.READY',str(self.ready)))
        self.stack.enter_context(patch('platform_runtime.BOOT_ID',str(self.boot)))
        self.stack.enter_context(patch.dict(os.environ,{'TCB705_LINEART':'auto'}))
        b._capability_cache=None;self.addCleanup(setattr,b,'_capability_cache',None)

    def write_platform(self,lineart=False):
        cfg={'build_id':'test-release','bitfile':'test.bit','files':{}}
        if lineart:
            hwh='''<SYSTEM><MODULES>
              <MODULE INSTANCE="tcb_lineart_accel_0" MODTYPE="tcb_lineart_accel"><PORTS>
              <PORT NAME="ap_clk" CLKFREQUENCY="100000000"/></PORTS></MODULE>
              <MODULE INSTANCE="processing_system7_0"><PARAMETERS>
              <PARAMETER NAME="C_USE_S_AXI_HP2" VALUE="1"/></PARAMETERS></MODULE>
              </MODULES><MEMRANGE INSTANCE="tcb_lineart_accel_0" BASEVALUE="0x40010000" HIGHVALUE="0x4001ffff"/></SYSTEM>'''
            (self.root/'test.hwh').write_text(hwh)
            name='tcb_lineart.registers.json'
            regs={'abi':b.c.ABI,'top':b.c.TOP,'return':16,'src':24,'dst':36,
                  'width':48,'height':56,'deleted':64,'identity':80}
            (self.root/name).write_text(json.dumps(regs))
            cfg['lineart']={**b.c.validate_hwh(self.root/'test.hwh'),'registers':name}
            cfg['files'][name]=hashlib.sha256((self.root/name).read_bytes()).hexdigest()
        raw=json.dumps(cfg).encode();self.manifest.write_bytes(raw)
        self.ready.write_text(json.dumps(dict(manifest_sha256=hashlib.sha256(raw).hexdigest(),
            build_id=cfg['build_id'],boot_id='boot-a',self_test='PASS')))

    def test_missing_ip_is_cached_and_never_attached_per_image(self):
        self.write_platform()
        source=np.eye(4,dtype=bool)
        reads=[];read_bytes=Path.read_bytes
        def read(path):
            if path==self.manifest:reads.append(path)
            return read_bytes(path)
        with patch.object(Path,'read_bytes',read), \
             patch.object(b,'open_accelerator') as attach, \
             patch('planner_accel_lease.acquire_planner_lease') as lease:
            for _ in range(3):np.testing.assert_array_equal(b.thin_or_cpu(source,lambda mask:mask.copy()),source)
            self.assertFalse(b.prepare()['ready'])
            self.assertEqual(len(reads),1)
            attach.assert_not_called();lease.assert_not_called()
        self.assertEqual(b.last_metrics()['backend'],'CPU')
        self.assertIn('no lineart',b.last_metrics()['fallback_reason'])

    def test_new_release_invalidates_missing_cache_and_validates_hwh(self):
        self.write_platform();self.assertFalse(b.capability()['available'])
        self.write_platform(lineart=True)
        with patch.object(b.c,'validate_manifest_section',wraps=b.c.validate_manifest_section) as validate:
            self.assertTrue(b.capability()['available']);self.assertTrue(b.capability()['available'])
            self.assertEqual(validate.call_count,1)
        (self.root/'test.hwh').write_text('<SYSTEM/>')
        with patch.object(b.c,'validate_manifest_section',wraps=b.c.validate_manifest_section) as validate:
            self.assertFalse(b.capability()['available']);self.assertFalse(b.capability()['available'])
            self.assertEqual(validate.call_count,1)

    def test_boot_and_receipt_changes_invalidate_positive_cache(self):
        self.write_platform(lineart=True);self.assertTrue(b.capability()['available'])
        self.boot.write_text('boot-b');self.assertFalse(b.capability()['available'])
        self.boot.write_text('boot-a');self.assertTrue(b.capability()['available'])
        receipt=json.loads(self.ready.read_text());receipt['self_test']='FAIL'
        self.ready.write_text(json.dumps(receipt));self.assertFalse(b.capability()['available'])

    def test_cpu_selection_never_probes_and_forced_pl_reports_absence(self):
        self.write_platform();source=np.eye(2,dtype=bool)
        with patch.dict(os.environ,{'TCB705_LINEART':'cpu'}),patch.object(b,'capability') as cap:
            b.thin_or_cpu(source,lambda mask:mask);b.prepare();cap.assert_not_called()
        with patch.dict(os.environ,{'TCB705_LINEART':'pl'}),patch.object(b,'open_accelerator') as attach:
            with self.assertRaisesRegex(ValueError,'no lineart'):b.thin_or_cpu(source,lambda mask:mask)
            attach.assert_not_called()

    def test_identity_changes_invalidate_even_with_coarse_file_timestamps(self):
        self.write_platform(lineart=True)
        with patch.object(b,'_file_signature',side_effect=lambda path:(str(path),0)):
            self.assertTrue(b.capability()['available'])
            self.boot.write_text('boot-b');self.assertFalse(b.capability()['available'])
            self.boot.write_text('boot-a');self.assertTrue(b.capability()['available'])
            receipt=json.loads(self.ready.read_text());receipt['self_test']='FAIL'
            self.ready.write_text(json.dumps(receipt));self.assertFalse(b.capability()['available'])

    def test_lineart_absence_does_not_disable_healthy_planner(self):
        from tcb705.accel_runtime import platform_health
        self.write_platform()
        cfg={'accelerator_abi':'tcb705-planner-parallel-fp32-v1','accelerator_clock_hz':100000000,'build_id':'test-release'}
        with patch('tcb705.accel_runtime.attached_identity',return_value=(cfg,{},None,0x40000000,65536)):
            state=platform_health()
        self.assertFalse(state['faulted']);self.assertFalse(state['lineart']['available'])


if __name__=='__main__':unittest.main()
