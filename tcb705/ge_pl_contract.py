"""Check that a sealed network overlay belongs to the intended Z20 hardware."""
import xml.etree.ElementTree as ET


CONTRACT = dict(dtbo='ge_pl.dtbo', phy_address=4, bridge_address=8,
                reset_gpio_offset=54, reference_clock_hz=200000000,
                kernel_release='5.4.0-xilinx-v2020.2')


def validate_hwh(path):
    modules = {m.get('INSTANCE'): m for m in ET.parse(path).iter('MODULE')}
    expected = {
        'ge_pl_bridge': ('xilinx.com:ip:gmii_to_rgmii:4.1', {
            'C_PHYADDR': '8', 'RGMII_TXC_SKEW': '0', 'C_EXTERNAL_CLOCK': 'false',
            'SupportLevel': 'Include_Shared_Logic_in_Core'}),
        'ge_pl_reset_slice': ('xilinx.com:ip:xlslice:1.0', {
            'DIN_WIDTH': '2', 'DIN_FROM': '0', 'DIN_TO': '0'}),
        'rst_ge_pl': ('xilinx.com:ip:proc_sys_reset:5.0', {
            'C_AUX_RESET_HIGH': '1', 'C_EXT_RESET_HIGH': '0'}),
        'processing_system7_0': ('xilinx.com:ip:processing_system7:5.5', {
            'PCW_ENET1_ENET1_IO': 'EMIO', 'PCW_ENET1_PERIPHERAL_ENABLE': '1',
            'PCW_ENET1_GRP_MDIO_IO': 'EMIO', 'PCW_FCLK2_PERIPHERAL_CLKSRC': 'IO PLL',
            'PCW_FPGA_FCLK2_ENABLE': '1'})}
    for name, (vlnv, values) in expected.items():
        module = modules.get(name)
        if module is None or module.get('VLNV') != vlnv:
            raise ValueError('GE_PL IP missing or incompatible: '+name)
        params = {p.get('NAME'): p.get('VALUE') for p in module.findall('./PARAMETERS/PARAMETER')}
        for key, value in values.items():
            if params.get(key) != value:
                raise ValueError('GE_PL parameter mismatch: '+name+'/'+key)

    def port(name, pin):
        found = modules[name].find("./PORTS/PORT[@NAME='%s']" % pin)
        if found is None:
            raise ValueError('GE_PL pin missing: '+name+'/'+pin)
        return found

    def same(a, b):
        x, y = port(*a).get('SIGNAME'), port(*b).get('SIGNAME')
        if not x or x != y:
            raise ValueError('GE_PL connection mismatch: '+str((a, b)))

    same(('ge_pl_bridge', 'clkin'), ('processing_system7_0', 'FCLK_CLK2'))
    if port('ge_pl_bridge', 'clkin').get('CLKFREQUENCY') != '200000000':
        raise ValueError('GE_PL reference clock must be 200 MHz')
    same(('rst_ge_pl', 'dcm_locked'), ('tcb_const_one', 'dout'))
    same(('rst_ge_pl', 'aux_reset_in'), ('tcb_const_zero', 'dout'))
    same(('rst_ge_pl', 'ext_reset_in'), ('processing_system7_0', 'FCLK_RESET2_N'))
    for pin in ('rx_reset', 'tx_reset'):
        same(('ge_pl_bridge', pin), ('rst_ge_pl', 'peripheral_reset'))
    same(('ge_pl_reset_slice', 'Din'), ('processing_system7_0', 'GPIO_O'))
    return dict(CONTRACT)
