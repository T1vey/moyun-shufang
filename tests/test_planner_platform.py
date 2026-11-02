"""Host-only platform identity/factory/self-test acceptance; no FPGA or serial I/O."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import planner_accel_contract as contract
from platform_runtime import accelerator_identity, digest, validate_manifest, validate_attached


def fixture(folder):
    folder=Path(folder);bit=folder/'drawing_planner.bit'
    bit.write_bytes(b'UNIT_TEST_ONLY_NOT_PROGRAMMABLE')
    regs=dict(abi=contract.ABI,top=contract.TOP);cursor=16
    doc=ET.Element('SYSTEMINFO')
    module=ET.SubElement(doc,'MODULE',INSTANCE=contract.TOP+'_0',VLNV='xilinx.com:hls:'+contract.TOP+':1.0')
    for field,count in contract.FIELDS.items():
        regs[field]=cursor
        reg=ET.SubElement(module,'REGISTER',NAME=field)
        ET.SubElement(reg,'PROPERTY',NAME='ADDRESS_OFFSET',VALUE=hex(cursor))
        ET.SubElement(reg,'PROPERTY',NAME='SIZE',VALUE=str(count*32))
        cursor+=4*count+4
    ET.SubElement(doc,'MEMRANGE',INSTANCE=contract.TOP+'_0',BASEVALUE='0x40000000',HIGHVALUE='0x4000ffff')
    ET.ElementTree(doc).write(bit.with_suffix('.hwh'))
    bit.with_suffix('.registers.json').write_text(json.dumps(regs))
    (folder/'display.dtbo').write_bytes(bytes.fromhex('d00dfeed')+b'UNIT_TEST_ONLY')
    cfg=dict(schema='so101-platform-v1',build_id='fixture-v2',display='md0700r-1024x600',
        kernel_release='test-kernel',bitfile=bit.name,dtbo='display.dtbo',
        accelerator_abi=contract.ABI,ip_name=contract.TOP+'_0',
        files={p.name:digest(p) for p in folder.iterdir() if p.is_file()})
    manifest=folder/'platform.json';manifest.write_text(json.dumps(cfg))
    return bit,manifest,cfg


class PlannerPlatformTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.bit,self.manifest,self.cfg=fixture(self.folder)

    def test_explicit_abi_and_complete_receipt_required(self):
        _,_,_,_,hashes,base,size=validate_manifest(self.manifest,'test-kernel')
        boot=self.folder/'boot';boot.write_text('current-boot')
        ready=self.folder/'ready.json'
        receipt=dict(schema='so101-platform-ready-v1',boot_id='current-boot',build_id='fixture-v2',
            manifest_sha256=digest(self.manifest),artifact_hashes=hashes,ip_name=contract.TOP+'_0',
            base=base,size=size,self_test='PASS',accelerator_abi=contract.ABI)
        ready.write_text(json.dumps(receipt))
        args=(self.bit,contract.TOP+'_0',hashes,self.manifest,ready,boot)
        self.assertEqual(validate_attached(*args,kernel_release='test-kernel'),(base,size))
        del receipt['accelerator_abi'];ready.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError,'not ready'):validate_attached(*args)

    def test_legacy_default_does_not_infer_planner_from_hwh_or_name(self):
        self.assertEqual(accelerator_identity({}),('so101-ik-target-v1','z20_ik_target_0'))
        for key in ('accelerator_abi','ip_name'):
            cfg=dict(self.cfg);del cfg[key];self.manifest.write_text(json.dumps(cfg))
            with self.assertRaises(ValueError):validate_manifest(self.manifest)
        cfg=dict(self.cfg,accelerator_abi='guessed-v3');self.manifest.write_text(json.dumps(cfg))
        with self.assertRaisesRegex(ValueError,'Unsupported'):validate_manifest(self.manifest)

    def test_hwh_rejects_pointer_scalar_missing_and_duplicate_width_metadata(self):
        hwh=self.bit.with_suffix('.hwh');original=hwh.read_bytes()
        for field,width in (('config_words','32'),('mode','64'),('config_words',None)):
            with self.subTest(field=field,width=width):
                tree=ET.fromstring(original)
                reg=next(r for r in tree.iter('REGISTER') if r.get('NAME')==field)
                prop=next(p for p in reg.findall('PROPERTY') if p.get('NAME')=='SIZE')
                if width is None:reg.remove(prop)
                else:prop.set('VALUE',width)
                ET.ElementTree(tree).write(hwh)
                with self.assertRaisesRegex(ValueError,'width mismatch'):
                    contract.validate_overlay_files(self.bit)
        tree=ET.fromstring(original);module=next(tree.iter('MODULE'))
        duplicate=ET.fromstring(ET.tostring(next(module.iter('REGISTER'))));module.append(duplicate)
        ET.ElementTree(tree).write(hwh)
        with self.assertRaisesRegex(ValueError,'duplicate HWH register'):
            contract.validate_overlay_files(self.bit)

    def test_real_vivado_split_pointer_requires_both_exact_halves(self):
        hwh=self.bit.with_suffix('.hwh');tree=ET.parse(hwh).getroot();module=next(tree.iter('MODULE'))
        reg=next(r for r in module.iter('REGISTER') if r.get('NAME')=='config_words')
        reg.set('NAME','config_words_1')
        next(p for p in reg.findall('PROPERTY') if p.get('NAME')=='SIZE').set('VALUE','32')
        high=ET.fromstring(ET.tostring(reg));high.set('NAME','config_words_2')
        next(p for p in high.findall('PROPERTY') if p.get('NAME')=='ADDRESS_OFFSET').set('VALUE','20')
        module.append(high);ET.ElementTree(tree).write(hwh)
        contract.validate_overlay_files(self.bit)
        complete=ET.tostring(tree)
        for failure in ('missing_high','wrong_high_offset','wrong_high_width','ambiguous_whole'):
            with self.subTest(failure=failure):
                bad=ET.fromstring(complete);m=next(bad.iter('MODULE'))
                upper=next(r for r in m.iter('REGISTER') if r.get('NAME')=='config_words_2')
                if failure=='missing_high':m.remove(upper)
                elif failure=='ambiguous_whole':
                    whole=ET.fromstring(ET.tostring(reg));whole.set('NAME','config_words');m.append(whole)
                else:
                    prop='ADDRESS_OFFSET' if failure=='wrong_high_offset' else 'SIZE'
                    next(p for p in upper.findall('PROPERTY') if p.get('NAME')==prop).set('VALUE','64')
                ET.ElementTree(bad).write(hwh)
                with self.assertRaises(ValueError):contract.validate_overlay_files(self.bit)

    def test_runtime_profile_and_factory_require_explicit_planner(self):
        from runtime_config import board_arguments
        from engine import make_backend
        profile=self.folder/'runtime.json'
        cfg=dict(schema='so101-runtime-v1',ik_engine='wls',pl_mode='planner',overlay=self.bit.name)
        profile.write_text(json.dumps(cfg))
        args=board_arguments(profile,self.folder)
        self.assertEqual(args[args.index('--pl-mode')+1],'planner')
        self.assertEqual(args[args.index('--ip-name')+1],contract.TOP+'_0')
        backend=Mock(return_value=object())
        with patch.dict(sys.modules,{'planner_accel_backend':SimpleNamespace(PynqPlannerAccel=backend)}):
            make_backend('wls',self.bit,pl_mode='planner',pl_load_policy='attach',platform_manifest=self.manifest)
        backend.assert_called_once_with(self.bit,contract.TOP+'_0',load_policy='attach',
            platform_manifest=self.manifest,platform_ready=None)
        with self.assertRaisesRegex(ValueError,'requires'):make_backend('wls',pl_mode='planner')
        cfg['pl_mode']='target';profile.write_text(json.dumps(cfg))
        with self.assertRaises(ValueError):board_arguments(profile,self.folder)

    def test_packager_requires_v2_export_and_preserves_pending_board_status(self):
        export=self.folder/'export';export.mkdir()
        for suffix in ('.bit','.hwh'):
            (export/('drawing_planner'+suffix)).write_bytes(self.bit.with_suffix(suffix).read_bytes())
        (export/'timing_summary.rpt').write_text('HOST UNIT FIXTURE - NOT ACTUAL TIMING')
        output=self.folder/'package'
        args=[sys.executable,str(ROOT/'hw/md0700r/package_platform.py'),'--export',str(export),
            '--registers',str(self.bit.with_suffix('.registers.json')),'--dtbo',str(self.folder/'display.dtbo'),
            '--kernel-release','test-kernel','--build-id','fixture-package','--output',str(output),
            '--accelerator-mode','planner','--display-backend','kernel-drm']
        failed=subprocess.run(args,capture_output=True,text=True)
        self.assertNotEqual(failed.returncode,0);self.assertFalse(output.exists())
        (export/'accelerator_mode.txt').write_text('planner\n')
        result=subprocess.run(args,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        cfg,*_=validate_manifest(output/'platform.json','test-kernel')
        self.assertEqual(cfg['accelerator_abi'],contract.ABI)
        self.assertEqual(cfg['board_acceptance'],'NOT_RUN')
        self.assertFalse((output/'drawing_target.bit').exists())


class PlannerBootSelfTestTests(unittest.TestCase):
    def run_selftest(self,difference=0.,checked=2,faulted=False):
        import planning
        from scripts.load_platform import planner_fk_self_test
        model,config,q=planning.nominal();q=np.asarray(q);qs=np.asarray([q,q+.001])
        poses=model.pose_many(qs)
        # The backend deliberately returns PS reference even if the PL is wrong.
        core=SimpleNamespace(faulted=faulted,fk_rows=Mock(return_value=(poses[:,:3,3],poses[:,:3,:3]@model.tool_axis)),
            metrics=Mock(side_effect=[{'fk_rows_checked':7},dict(fk_rows_checked=7+checked,fk_mode='shadow_only',
                fk_max_position_difference_m=difference,fk_max_axis_difference=0.)]))
        planner_fk_self_test(core,model,qs,config)

    def test_valid_both_modes_can_be_marked_ready(self):self.run_selftest(difference=1e-7)

    def test_wrong_pl_or_missing_completion_cannot_pass_via_ps_reference(self):
        for kwargs in ({'difference':1e-3},{'difference':float('nan')},{'checked':0},{'faulted':True}):
            with self.subTest(kwargs=kwargs),self.assertRaisesRegex(RuntimeError,'self-test failed'):
                self.run_selftest(**kwargs)


class UserspacePlatformTests(unittest.TestCase):
    def setUp(self):
        from md0700r_contract import expected_contract
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.bit,self.manifest,self.cfg=fixture(self.folder)
        self.cfg.update(display_backend='pynq-mmio',touch_backend='gt911-pl-gpio',
                        dtbo=None,kernel_release=None,display_contract=expected_contract())
        self.manifest.write_text(json.dumps(self.cfg))

    def test_userspace_validates_contract_without_kernel_pin_or_dtbo(self):
        with patch('md0700r_contract.validate_hwh') as hwh:
            cfg,bit,dtbo,*_=validate_manifest(self.manifest,'actual-board-kernel')
        hwh.assert_called_once_with(bit.with_suffix('.hwh'))
        self.assertIsNone(dtbo);self.assertEqual(cfg['display_backend'],'pynq-mmio')

    def test_userspace_rejects_bad_contract_or_old_touch_configuration(self):
        for change in ({'display_backend':'guess'}, {'touch_backend':'goodix-i2c'},
                       {'dtbo':'display.dtbo'}, {'kernel_release':'test-kernel'},
                       {'display_contract':{}}):
            with self.subTest(change=change):
                self.manifest.write_text(json.dumps(dict(self.cfg,**change)))
                with self.assertRaises(ValueError):validate_manifest(self.manifest)

    def test_hwh_is_not_trusted_from_manifest_claim_alone(self):
        with patch('md0700r_contract.validate_hwh',side_effect=ValueError('wrong touch net')):
            with self.assertRaisesRegex(ValueError,'wrong touch'):validate_manifest(self.manifest)

    def test_userspace_does_not_wait_for_drm_or_write_xorg(self):
        from scripts.load_platform import prepare_display_receipt
        with patch('scripts.load_platform.Path.glob',side_effect=AssertionError('must not probe DRM')):
            prepare_display_receipt(self.cfg,self.folder,0)
        self.assertFalse((self.folder/'xorg.conf').exists())

    def test_legacy_drm_still_requires_connector(self):
        from scripts.load_platform import prepare_display_receipt
        with patch('scripts.load_platform.Path.glob',return_value=[]):
            with self.assertRaisesRegex(RuntimeError,'No DRM'):
                prepare_display_receipt({},self.folder,-1)

    def test_display_health_must_match_all_artifacts_and_attach_mode(self):
        from md0700r_runtime import validate_health,display_ready
        identity=dict(abi=contract.ABI,hashes={'drawing_planner.bit':'abc'},
                      bit_sha256='abc',manifest_sha256='manifest')
        metrics=dict(abi=contract.ABI,artifact_hashes=identity['hashes'],faulted=False,
                     pl_load_policy='attach')
        validate_health({'ik_metrics':metrics},identity)
        for delta in ({'abi':'old'}, {'faulted':True}, {'pl_load_policy':'download'},
                      {'artifact_hashes':{'drawing_target.bit':'abc'}}):
            with self.subTest(delta=delta),self.assertRaises(ValueError):
                validate_health({'ik_metrics':dict(metrics,**delta)},identity)
        status=dict(status='RUNNING',hardware_frames_verified=True,bit_sha256='abc',
                    manifest_sha256='manifest')
        self.assertTrue(display_ready(status,identity))
        for delta in ({'manifest_sha256':'stale'},{'bit_sha256':'old'},
                      {'hardware_frames_verified':False}):
            self.assertFalse(display_ready(dict(status,**delta),identity))

    def test_display_does_not_attach_without_valid_boot_receipt(self):
        from md0700r_runtime import resolve_display
        with patch('md0700r_contract.validate_hwh'),patch('md0700r_runtime.validate_attached',
                side_effect=ValueError('boot receipt absent')) as attach:
            with self.assertRaisesRegex(ValueError,'boot receipt absent'):
                resolve_display(self.folder,self.manifest)
        attach.assert_called_once()


class PlannerSourceDeliveryTests(unittest.TestCase):
    def test_runtime_contains_native_sources_and_planner_contract_without_host_binary(self):
        from scripts.build_delivery import selected_files
        selected={p.as_posix() for p in selected_files(ROOT)}
        self.assertTrue({'native/geometry.py','native/geometry.cpp','native/build.py',
            'planner_accel_backend.py','planner_accel_contract.py','plan_storage.py',
            'scripts/export_planner_register_map.py','hw/md0700r/create_fused.tcl',
            'hw/md0700r/build_fused.tcl','hw/md0700r/package_platform.py'}.issubset(selected))
        self.assertFalse(any(p.endswith(('.dll','.so','.dylib')) or p.startswith('native/build/') for p in selected))


class PlatformDownloadLeaseTests(unittest.TestCase):
    def test_userspace_download_does_not_pass_a_fake_none_dtbo(self):
        from scripts.load_platform import downloaded_backend
        lease=Mock();lease.__enter__=Mock(return_value=lease);lease.__exit__=Mock(return_value=False)
        overlay=SimpleNamespace(download=Mock())
        pynq=SimpleNamespace(Overlay=Mock(return_value=overlay),MMIO=Mock())
        core=SimpleNamespace(transport=SimpleNamespace(inflight=False,close=Mock()))
        with patch.dict(sys.modules,{'pynq':pynq,'planner_accel_backend':SimpleNamespace(
                PynqPlannerAccel=Mock(return_value=core))}),patch(
                'planner_accel_lease.acquire_planner_lease',return_value=lease):
            with downloaded_backend(contract.ABI,'fixture.bit',None,0x40000000,65536,{}):pass
        pynq.Overlay.assert_called_once_with('fixture.bit',download=False)

    def test_download_both_abis_requires_lease_and_planner_releases_buffers_first(self):
        from scripts.load_platform import downloaded_backend
        for abi in (contract.ABI,'so101-ik-target-v1'):
            with self.subTest(abi=abi):
                events=[]
                class Lease:
                    def __enter__(self):events.append('lease_enter');return self
                    def __exit__(self,*args):events.append('lease_exit')
                lease=Lease()
                transport=SimpleNamespace(inflight=False,close=lambda:events.append('buffers_close'))
                core=SimpleNamespace(transport=transport)
                backend=Mock(side_effect=lambda **kw:(events.append('backend'),core)[1])
                overlay=SimpleNamespace(download=lambda:events.append('download'))
                pynq=SimpleNamespace(Overlay=Mock(side_effect=lambda *a,**kw:(events.append('overlay'),overlay)[1]),
                    MMIO=Mock(side_effect=lambda *a:(events.append('mmio'),object())[1]))
                with patch.dict(sys.modules,{'pynq':pynq,
                        'planner_accel_backend':SimpleNamespace(PynqPlannerAccel=backend),
                        'ik_target_backend':SimpleNamespace(PynqIKTarget=backend)}),patch(
                        'planner_accel_lease.acquire_planner_lease',return_value=lease) as acquire:
                    with downloaded_backend(abi,'fixture.bit','fixture.dtbo',0x40000000,65536,{}) as opened:
                        self.assertIs(opened,core);events.append('selftest_and_receipt')
                acquire.assert_called_once_with(0x40000000)
                expected=['lease_enter','overlay','download','mmio','backend','selftest_and_receipt']
                if abi==contract.ABI:
                    expected.append('buffers_close');self.assertIs(backend.call_args.kwargs['lease'],lease)
                else:self.assertNotIn('lease',backend.call_args.kwargs)
                self.assertEqual(events,expected+['lease_exit'])

    def test_occupied_or_stale_lease_prevents_even_overlay_creation(self):
        from scripts.load_platform import downloaded_backend
        pynq=SimpleNamespace(Overlay=Mock(),MMIO=Mock())
        with patch.dict(sys.modules,{'pynq':pynq}),patch('planner_accel_lease.acquire_planner_lease',
                side_effect=RuntimeError('busy or stale')):
            with self.assertRaisesRegex(RuntimeError,'busy or stale'):
                with downloaded_backend(contract.ABI,'fixture.bit','fixture.dtbo',0x40000000,65536,{}):
                    self.fail('must not enter')
        pynq.Overlay.assert_not_called();pynq.MMIO.assert_not_called()

    def test_pending_close_preserves_original_failure_and_lease_exit(self):
        from scripts.load_platform import downloaded_backend
        events=[]
        class Lease:
            def __enter__(self):return self
            def __exit__(self,kind,*args):events.append(kind)
        core=SimpleNamespace(transport=SimpleNamespace(inflight=True,
            close=Mock(side_effect=RuntimeError('still owns DDR'))))
        pynq=SimpleNamespace(Overlay=Mock(return_value=SimpleNamespace(download=Mock())),MMIO=Mock())
        backend=Mock(return_value=core)
        with patch.dict(sys.modules,{'pynq':pynq,'planner_accel_backend':SimpleNamespace(PynqPlannerAccel=backend)}),patch(
                'planner_accel_lease.acquire_planner_lease',return_value=Lease()):
            with self.assertRaisesRegex(ValueError,'original timeout'):
                with downloaded_backend(contract.ABI,'fixture.bit','fixture.dtbo',0x40000000,65536,{}):
                    raise ValueError('original timeout')
        core.transport.close.assert_called_once();self.assertEqual(events,[ValueError])


class PlannerAttachMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.bit,self.manifest,_=fixture(Path(self.tmp.name))

    def run_attach(self,memories,receipt_error=None):
        from planner_accel_backend import PynqPlannerAccel
        memory=object();events=[]
        overlay=SimpleNamespace(mem_dict=memories,device=SimpleNamespace(
            get_memory=Mock(return_value=memory)),download=Mock())
        pynq=SimpleNamespace(Overlay=Mock(side_effect=lambda *a,**k:(events.append('metadata'),overlay)[1]),
            MMIO=Mock(return_value=SimpleNamespace(base_addr=0x40000000)),allocate=Mock())
        lease=SimpleNamespace(pending=False,assert_owned=Mock(),close=Mock())
        with patch.dict(sys.modules,{'pynq':pynq}),patch('platform_runtime.validate_attached',
                side_effect=receipt_error if receipt_error else lambda *a,**k:(events.append('receipt'),(0x40000000,65536))[1]),patch(
                'planner_accel_backend.acquire_planner_lease',return_value=lease),patch(
                'planner_accel_backend.DDRTransport') as transport:
            try:
                core=PynqPlannerAccel(self.bit,platform_manifest=self.manifest)
            except ValueError:
                pynq.allocate.assert_not_called();overlay.download.assert_not_called()
                if receipt_error:pynq.Overlay.assert_not_called();pynq.MMIO.assert_not_called()
                else:lease.close.assert_called_once()
                raise
            allocator=transport.call_args.args[2]
            allocator(shape=(8,),dtype=np.uint64)
        self.assertEqual(events,['receipt','metadata'])
        pynq.Overlay.assert_called_once_with(str(self.bit),download=False)
        overlay.download.assert_not_called()
        pynq.allocate.assert_called_once_with(target=memory,shape=(8,),dtype=np.uint64)
        return core

    def test_fresh_process_attaches_explicit_ps_ddr_without_download(self):
        self.run_attach({'PSDDR':{'base_address':0,'size':536870912}})

    def test_missing_or_ambiguous_ps_ddr_fails_without_allocation(self):
        for memories in ({},{'a':{'base_address':0},'b':{'base_address':0}}):
            with self.subTest(memories=memories),self.assertRaisesRegex(ValueError,'explicit PS DDR'):
                self.run_attach(memories)

    def test_receipt_gate_runs_before_metadata_or_mmio(self):
        with self.assertRaisesRegex(ValueError,'no boot receipt'):
            self.run_attach({},ValueError('no boot receipt'))


if __name__=='__main__':unittest.main()
