import hashlib,json,os,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch,Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import lineart_backend as b

class AttachmentCache(unittest.TestCase):
    def setUp(self):
        b._attachment=None
        b._capability_cache=None
    def tearDown(self):
        b._attachment=None
        b._capability_cache=None
    def test_metadata_reused_but_changes_force_validation(self):
        path=Path('/test/platform.json');cfg={'bitfile':'test.bit'}
        allocate=object();overlay=Mock();attached=Mock(return_value=(cfg,None,None,None,None))
        entry={'base':b.c.BASE,'size':65536}
        pynq=types.SimpleNamespace(Overlay=overlay)
        with patch.object(b,'_attachment_key',return_value=('boot-a',)) as key, \
             patch('tcb705.accel_runtime.attached_identity',attached), \
             patch('tcb705.accel_runtime.ps_ddr_allocator',return_value=allocate), \
             patch.object(b.c,'validate_manifest_section',return_value=(entry,{})), \
             patch.dict(sys.modules,{'pynq':pynq}):
            first=b._attached_metadata(path)
            self.assertIs(b._attached_metadata(path),first)
            self.assertEqual(attached.call_count,1)
            overlay.assert_called_once_with(str(path.parent/'test.bit'),download=False)
            key.return_value=('boot-b',)
            b._attached_metadata(path)
            self.assertEqual(attached.call_count,2)
            key.return_value=('changed-invalid',)
            attached.side_effect=ValueError('boot receipt rejected')
            with self.assertRaisesRegex(ValueError,'receipt'):b._attached_metadata(path)
    def test_change_during_attach_not_cached(self):
        cfg={'bitfile':'test.bit'}
        with patch.object(b,'_attachment_key',side_effect=[('a',),('b',)]), \
             patch('tcb705.accel_runtime.attached_identity',return_value=(cfg,None,None,None,None)), \
             patch('tcb705.accel_runtime.ps_ddr_allocator'), \
             patch.object(b.c,'validate_manifest_section',return_value=({},{})), \
             patch.dict(sys.modules,{'pynq':types.SimpleNamespace(Overlay=Mock())}):
            with self.assertRaisesRegex(ValueError,'changed while'):b._attached_metadata(Path('/test/platform.json'))
            self.assertIsNone(b._attachment)
    def test_every_access_rehashes_bytes_receipt_and_process(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();bit=root/'test.bit';bit.write_bytes(b'one')
            manifest=root/'platform.json'
            manifest.write_text(json.dumps({'files':{'test.bit':hashlib.sha256(b'one').hexdigest()}}))
            ready=root/'ready';ready.write_bytes(b'receipt-a');boot=root/'boot';boot.write_text('boot-a')
            original_stat=Path.stat
            def receipt_stat(path,*args,**kwargs):
                result=original_stat(path,*args,**kwargs)
                return types.SimpleNamespace(st_uid=0,st_mode=result.st_mode) if path==ready else result
            with patch('platform_runtime.READY',str(ready)),patch('platform_runtime.BOOT_ID',str(boot)), \
                 patch.object(Path,'stat',receipt_stat):
                with patch.object(b.os,'getpid',return_value=101):
                    a=b._attachment_key(manifest)
                    ready.write_bytes(b'receipt-b');self.assertNotEqual(a,b._attachment_key(manifest))
                    ready.write_bytes(b'receipt-a')
                    bit.write_bytes(b'two')
                    with self.assertRaisesRegex(ValueError,'hash mismatch'):b._attachment_key(manifest)
                    bit.write_bytes(b'one');self.assertEqual(a,b._attachment_key(manifest))
                with patch.object(b.os,'getpid',return_value=102):self.assertNotEqual(a,b._attachment_key(manifest))
    def test_prepare_does_not_start_dma_and_releases_lease(self):
        core=Mock()
        with patch.dict(os.environ,{'TCB705_LINEART':'auto'}),patch.object(b,'capability',return_value={'available':True}),patch.object(b,'open_accelerator',return_value=core):
            self.assertTrue(b.prepare()['ready'])
            core.thin.assert_not_called()
            core.lease.release_claim.assert_called_once_with(core)
            core.lease.close.assert_called_once()
    def test_prepare_failure_is_reported(self):
        with patch.dict(os.environ,{'TCB705_LINEART':'auto'}),patch.object(b,'capability',return_value={'available':True}),patch.object(b,'open_accelerator',side_effect=ValueError('unready')):
            result=b.prepare();self.assertFalse(result['ready']);self.assertEqual(result['reason'],'unready')
    def test_each_operation_owns_a_fresh_lease(self):
        leases=[Mock(),Mock()];entry={'base':b.c.BASE,'size':65536}
        registers={'abi':b.c.ABI,'top':b.c.TOP,'return':16,'src':24,'dst':36,'width':48,'height':56,'deleted':64,'identity':80}
        with patch('tcb705.accel_runtime.platform_manifest',return_value=Path('/test/platform.json')), \
             patch.object(b,'capability',return_value={'available':True}), \
             patch('tcb705.accel_runtime.ensure_event_loop'), \
             patch('tcb705.accel_runtime.verify_planner_clock') as clock, \
             patch('planner_accel_lease.acquire_planner_lease',side_effect=leases), \
             patch.object(b,'_attached_metadata',return_value=({'accelerator_clock_hz':76923080},entry,registers,Mock())), \
             patch.dict(sys.modules,{'pynq':types.SimpleNamespace(MMIO=Mock())}):
            first=b.open_accelerator();second=b.open_accelerator()
            self.assertIs(first.lease,leases[0]);self.assertIs(second.lease,leases[1])
            self.assertEqual(clock.call_count,2)

if __name__=='__main__':unittest.main()
