"""Seven-axis platform ownership, explicit DDR and identity isolation."""
from pathlib import Path
from types import SimpleNamespace
import sys,unittest
from unittest.mock import Mock,patch
from tcb705 import accel_contract as c
from tcb705 import accel_runtime as runtime

class PlatformTests(unittest.TestCase):
    def test_missing_receipt_prevents_pynq_and_lease(self):
        pynq=SimpleNamespace(Overlay=Mock(),MMIO=Mock())
        with patch.object(runtime,'attached_identity',side_effect=ValueError('missing receipt')),patch.dict(sys.modules,{'pynq':pynq}),patch('planner_accel_lease.acquire_planner_lease') as acquire:
            core,reason=runtime.open_accelerator()
        self.assertIsNone(core);self.assertIn('missing receipt',reason)
        pynq.Overlay.assert_not_called();pynq.MMIO.assert_not_called();acquire.assert_not_called()

    def attach(self,memories,lease_error=None):
        events=[];memory=object();lease=SimpleNamespace(pending=False,close=Mock())
        overlay=SimpleNamespace(mem_dict=memories,device=SimpleNamespace(get_memory=Mock(return_value=memory)),download=Mock())
        pynq=SimpleNamespace(Overlay=Mock(side_effect=lambda *a,**k:(events.append('metadata'),overlay)[1]),MMIO=Mock(),allocate=Mock(),Clocks=SimpleNamespace(fclk1_mhz=1000/13))
        def acquire(*args):
            events.append('lease')
            if lease_error:raise lease_error
            return lease
        identity=({'bitfile':'tcb.bit','accelerator_clock_hz':76923076,'accelerator_abi':c.ABI}, {}, {},0x40000000,65536)
        with patch.object(runtime,'attached_identity',return_value=identity),patch.object(runtime,'verify_planner_clock'),patch.object(runtime,'platform_manifest',return_value=Path('/sealed/platform.json')),patch.dict(sys.modules,{'pynq':pynq}),patch('planner_accel_lease.acquire_planner_lease',side_effect=acquire),patch('planner_accel_backend.DDRTransport') as transport:
            core,reason=runtime.open_accelerator()
            if core:
                self.assertEqual(events,['lease','metadata'])
                self.assertIs(transport.call_args.kwargs['protocol'],c)
                transport.call_args.kwargs['allocator'](shape=(8,),dtype='u8')
                pynq.allocate.assert_called_once_with(target=memory,shape=(8,),dtype='u8')
                pynq.Overlay.assert_called_once_with(str(Path('/sealed/tcb.bit')),download=False)
            else:
                pynq.allocate.assert_not_called()
                if lease_error:pynq.Overlay.assert_not_called();pynq.MMIO.assert_not_called()
                else:lease.close.assert_called_once()
        overlay.download.assert_not_called()
        return core,reason

    def test_fresh_process_attaches_explicit_ddr_without_download(self):
        core,reason=self.attach({'PSDDR':{'base_address':0}})
        self.assertIsNotNone(core);self.assertIsNone(reason)

    def test_missing_or_ambiguous_ddr_releases_idle_lease(self):
        for memories in ({},{'a':{'base_address':0},'b':{'base_address':0}}):
            with self.subTest(memories=memories):
                core,reason=self.attach(memories)
                self.assertIsNone(core);self.assertIn('explicit PS DDR',reason)

    def test_busy_lease_prevents_even_metadata_attachment(self):
        core,reason=self.attach({},RuntimeError('busy'))
        self.assertIsNone(core);self.assertEqual(reason,'busy')

    def test_physical_clock_must_match_sealed_hardware(self):
        reader=SimpleNamespace(get_pl_clk=Mock(side_effect=[1000/13,100]),PL_CLK_CTRLS=[None,SimpleNamespace(SRCSEL=0)])
        ps=SimpleNamespace(_ClocksZynq=Mock(return_value=reader))
        mmio=SimpleNamespace(read=Mock(return_value=0))
        with patch.dict(sys.modules,{'pynq.ps':ps,'pynq':SimpleNamespace(MMIO=Mock(return_value=mmio))}):
            self.assertAlmostEqual(runtime.verify_planner_clock(76923076),1000000000/13)
            ps._ClocksZynq.assert_called_with(ref_clk_mhz=33.333333)
            reader.get_pl_clk.side_effect=[100,100]
            with self.assertRaisesRegex(ValueError,'physical FCLK1'):runtime.verify_planner_clock(76923076)
            mmio.read.return_value=2
            with self.assertRaisesRegex(ValueError,'reset is asserted'):runtime.verify_planner_clock(76923076)

    def test_reset_polarity_and_wiring_are_checked_before_mmio(self):
        import xml.etree.ElementTree as ET
        tree=ET.Element('SYSTEM')
        def module(name,params,pins):
            m=ET.SubElement(tree,'MODULE',INSTANCE=name)
            pp=ET.SubElement(m,'PARAMETERS');ports=ET.SubElement(m,'PORTS')
            for k,v in params.items():ET.SubElement(pp,'PARAMETER',NAME=k,VALUE=str(v))
            for k,v in pins.items():ET.SubElement(ports,'PORT',NAME=k,SIGNAME=v)
            return m
        reset=module('rst_tcb_planner',dict(C_EXT_RESET_HIGH=0,C_AUX_RESET_HIGH=1),dict(aux_reset_in='zero',mb_debug_sys_rst='zero',dcm_locked='one',ext_reset_in='psreset1',slowest_sync_clk='clock1',peripheral_aresetn='reset1'))
        module('tcb_const_zero',dict(CONST_VAL='0x0'),dict(dout='zero'))
        module('tcb_const_one',dict(CONST_VAL='0x1'),dict(dout='one'))
        module('processing_system7_0',{},dict(FCLK_RESET1_N='psreset1',FCLK_CLK1='clock1'))
        core=module(c.TOP+'_0',{},dict(ap_rst_n='reset1'))
        module('ps7_0_axi_periph',{},dict(M06_ARESETN='reset1'))
        module('planner_ddr',{},dict(ARESETN='reset1'))
        c.validate_reset_domain(tree)
        aux=reset.find("./PARAMETERS/PARAMETER[@NAME='C_AUX_RESET_HIGH']")
        aux.set('VALUE','0')
        with self.assertRaisesRegex(ValueError,'polarity'):c.validate_reset_domain(tree)
        aux.set('VALUE','1');core.find('./PORTS/PORT').set('SIGNAME','wrong_reset')
        with self.assertRaisesRegex(ValueError,'wiring'):c.validate_reset_domain(tree)

    def test_five_axis_receipt_cannot_attach_seven_axis(self):
        old=({'accelerator_abi':'so101-planner-accel-v2'},Path('old.bit'),None,{}, {},0x40000000,65536)
        with patch.object(runtime,'platform_manifest',return_value=Path('/sealed/platform.json')),patch('platform_runtime.validate_manifest',return_value=old),patch('platform_runtime.validate_attached') as check:
            with self.assertRaisesRegex(ValueError,'seven-axis ABI'):runtime.attached_identity()
        check.assert_not_called()

    def test_downloader_leases_before_download_and_closes_buffers(self):
        from scripts.load_platform import downloaded_backend
        events=[]
        class Lease:
            def __enter__(self):events.append('lease');return self
            def __exit__(self,*args):events.append('release')
        overlay=SimpleNamespace(mem_dict={'PSDDR':{'base_address':0}},device=SimpleNamespace(get_memory=Mock()),download=lambda:events.append('download'))
        pynq=SimpleNamespace(Overlay=Mock(return_value=overlay),MMIO=Mock(),allocate=Mock())
        transport=SimpleNamespace(close=lambda:events.append('close'))
        with patch.dict(sys.modules,{'pynq':pynq}),patch('planner_accel_lease.acquire_planner_lease',return_value=Lease()),patch('planner_accel_backend.DDRTransport',return_value=transport) as ctor:
            with downloaded_backend(c.ABI,'sealed.bit',None,0x40000000,65536,{}) as core:
                self.assertIs(core.transport,transport);self.assertIs(ctor.call_args.kwargs['protocol'],c)
                events.append('selftest')
        self.assertEqual(events,['lease','download','selftest','close','release'])

if __name__=='__main__':unittest.main()
