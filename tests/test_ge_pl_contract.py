"""Reject dangerous network hardware mismatches before PS register writes."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import json
import struct
from unittest.mock import patch, MagicMock
from tcb705.ge_pl_contract import validate_hwh
from scripts.start_ge_pl import configure_address, configure_gem1_clocks


class GePlContractTests(unittest.TestCase):
    def test_pc_peer_config_and_conflicting_legacy_address(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg=Path(directory)/'network.json'
            data=dict(address='192.168.2.99/24',peer_ip='192.168.2.1')
            cfg.write_text(json.dumps(data))
            existing=[dict(ifname='eth0',addr_info=[dict(local='192.168.4.23',prefixlen=24)])]
            with patch('scripts.start_ge_pl.subprocess.check_output',return_value=json.dumps(existing).encode()),patch('scripts.start_ge_pl.subprocess.run') as run:
                self.assertEqual(configure_address('eth1',cfg)['peer_ip'],'192.168.2.1')
                run.assert_called_once()
            data['controller_ip']='192.168.2.4';cfg.write_text(json.dumps(data))
            with patch('scripts.start_ge_pl.subprocess.run') as run:
                with self.assertRaisesRegex(ValueError,'Conflicting'):configure_address('eth1',cfg)
                run.assert_not_called()

    def test_clock_setup_keeps_linux_slcr_writable_and_preserves_other_clocks(self):
        registers=bytearray(4096)
        for offset,value in ((0x108,30<<12),(0x190,0x100500),
                             (0x13c,1),(0x144,0x3c01),(0x140,0x100801)):
            struct.pack_into('<I',registers,offset,value)
        before=bytes(registers)
        mapping=MagicMock();mapping.__enter__.return_value=registers
        # Windows has no MAP_SHARED/PROT_* constants; mocked mapping is portable.
        with patch('scripts.start_ge_pl.os.open',return_value=99),patch('scripts.start_ge_pl.os.close'), \
             patch('scripts.start_ge_pl.os.O_SYNC',0,create=True), \
             patch('scripts.start_ge_pl.mmap.mmap',return_value=mapping), \
             patch('scripts.start_ge_pl.mmap.MAP_SHARED',1,create=True), \
             patch('scripts.start_ge_pl.mmap.PROT_READ',1,create=True), \
             patch('scripts.start_ge_pl.mmap.PROT_WRITE',2,create=True):
            result=configure_gem1_clocks()
        self.assertEqual(result['fclk2_hz'],200000000)
        self.assertEqual(struct.unpack_from('<I',registers,0x13c)[0],0x11)
        self.assertEqual(struct.unpack_from('<I',registers,0x144)[0],0x3c41)
        allowed=set(range(8,12))|set(range(0x13c,0x140))|set(range(0x144,0x148))
        self.assertTrue(all(a==b or i in allowed for i,(a,b) in enumerate(zip(before,registers))))

    def test_robot_subnet_never_overlaps_existing_control_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg=Path(directory)/'network.json'
            cfg.write_text(json.dumps(dict(address='192.168.2.23/24',controller_ip='192.168.2.4')))
            existing=[dict(ifname='eth0',addr_info=[dict(local='192.168.2.99',prefixlen=24)])]
            with patch('scripts.start_ge_pl.subprocess.check_output',return_value=json.dumps(existing).encode()),patch('scripts.start_ge_pl.subprocess.run') as run:
                with self.assertRaisesRegex(ValueError,'overlaps eth0'):configure_address('eth1',cfg)
                run.assert_not_called()

    def test_static_robot_address_does_not_add_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg=Path(directory)/'network.json'
            cfg.write_text(json.dumps(dict(address='192.168.4.23/24',controller_ip='192.168.4.4')))
            with patch('scripts.start_ge_pl.subprocess.check_output',return_value=b'[]'),patch('scripts.start_ge_pl.subprocess.run') as run:
                self.assertEqual(configure_address('eth1',cfg)['controller_ip'],'192.168.4.4')
                run.assert_called_once_with(['ip','address','replace','192.168.4.23/24','dev','eth1'],check=True)

    def test_missing_address_configuration_leaves_interface_unassigned(self):
        with tempfile.TemporaryDirectory() as directory,patch('scripts.start_ge_pl.subprocess.run') as run:
            self.assertIsNone(configure_address('eth1',Path(directory)/'missing.json'))
            run.assert_not_called()

    def test_real_export_and_corrupted_reset_clock_phy(self):
        root = Path(__file__).resolve().parents[1]
        candidates = [root/'overlay/tcb705_ge_pl/tcb705_planner.hwh',
                      root/'hw/vivado_ge_pl/tcb705_md0700r.gen/sources_1/bd/system/hw_handoff/system.hwh']
        source = next((p for p in candidates if p.exists()), None)
        if source is None:
            self.skipTest('GE_PL hardware export not present')
        self.assertEqual(validate_hwh(source)['phy_address'], 4)
        mutations = [('ge_pl_bridge', 'C_PHYADDR', '4'),
                     ('ge_pl_bridge', 'RGMII_TXC_SKEW', '2'),
                     ('rst_ge_pl', 'C_AUX_RESET_HIGH', '0'),
                     ('ge_pl_reset_slice', 'DIN_FROM', '1')]
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)/'invalid.hwh'
            for module, param, value in mutations:
                with self.subTest(module=module, param=param):
                    tree = ET.parse(source)
                    m = next(m for m in tree.iter('MODULE') if m.get('INSTANCE') == module)
                    m.find("./PARAMETERS/PARAMETER[@NAME='%s']" % param).set('VALUE', value)
                    tree.write(dest)
                    with self.assertRaises(ValueError):
                        validate_hwh(dest)
            tree = ET.parse(source)
            bridge = next(m for m in tree.iter('MODULE') if m.get('INSTANCE') == 'ge_pl_bridge')
            bridge.find("./PORTS/PORT[@NAME='clkin']").set('SIGNAME', 'wrong_clock')
            tree.write(dest)
            with self.assertRaises(ValueError):
                validate_hwh(dest)


if __name__ == '__main__':
    unittest.main()
