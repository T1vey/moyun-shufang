"""Verified userspace MD0700R/GT911 hardware interface, independent of a DTBO.

Only the dedicated platform loader programs the PL. Linux DRM/Goodix drivers
must not own these registers when this profile is active. Python 3.8 compatible.
"""
import xml.etree.ElementTree as ET


_IPS = {
    'clock': ('clk_wiz_0', 0x43C30000, 'xilinx.com:ip:clk_wiz:6.0'),
    'lcd_id': ('lcd_out_lcd_id', 0x41200000, 'xilinx.com:ip:axi_gpio:2.0'),
    'pwm': ('lcd_out_lcd_pl_pwm', 0x43C00000, 'digilentinc.com:IP:PWM:2.0'),
    'vtc': ('lcd_out_lcd_vtc', 0x43C10000, 'xilinx.com:ip:v_tc:6.2'),
    'framebuffer': ('lcd_out_v_frmbuf_rd_0', 0x43C20000, 'xilinx.com:ip:v_frmbuf_rd:3.0'),
    'reset_touch': ('rest_gpio', 0x41220000, 'xilinx.com:ip:axi_gpio:2.0'),
}


def expected_contract():
    """Return a fresh JSON-safe interface contract; no board acceptance is implied."""
    return dict(schema='so101-md0700r-mmio-v1', width=1024, height=600,
                pixel_clock_hz=51200000, framebuffer_format=29, stride_bytes=3072,
                x11_display=':9', touch_packet_offset=8, register_window_bytes=65536,
                ips={key: dict(instance=value[0], base=value[1]) for key, value in _IPS.items()},
                touch_module='touch_pl',
                touch_packet_format='gt911-seq10-pressed1-valid1-x10-y10')


def validate_hwh(path):
    """Reject a userspace profile bound to incompatible or ambiguous HWH data."""
    root = ET.parse(path).getroot()

    def module(name, vlnv):
        found = [m for m in root.iter('MODULE') if m.get('INSTANCE') == name]
        if len(found) != 1 or found[0].get('VLNV') != vlnv:
            raise ValueError('MD0700R HWH module mismatch: ' + name)
        return found[0]

    def parameter(m, name, value):
        found = [p.get('VALUE') for p in m.findall('./PARAMETERS/PARAMETER')
                 if p.get('NAME') == name]
        if found != [str(value)]:
            raise ValueError('MD0700R HWH parameter mismatch: ' + m.get('INSTANCE') + '/' + name)

    def port(m, name, expected):
        found = [p for p in m.findall('./PORTS/PORT') if p.get('NAME') == name]
        if len(found) != 1 or any(found[0].get(k) != v for k, v in expected.items()):
            raise ValueError('MD0700R HWH port mismatch: ' + m.get('INSTANCE') + '/' + name)
        return found[0]

    modules = {}
    for key, (name, base, vlnv) in _IPS.items():
        modules[key] = module(name, vlnv)
        ranges = {(int(r.get('BASEVALUE'), 0), int(r.get('HIGHVALUE'), 0))
                  for r in root.iter('MEMRANGE') if r.get('INSTANCE') == name}
        if ranges != {(base, base + 65535)}:
            raise ValueError('MD0700R HWH address mismatch: ' + name)
    for key, checks in {
        'clock': {'C_CLKOUT0_ACTUAL_FREQ': '51.20000', 'C_NUM_OUT_CLKS': '1'},
        'lcd_id': {'C_GPIO_WIDTH': '3', 'C_IS_DUAL': '0'},
        'pwm': {'NUM_PWM': '1', 'C_PWM_AXI_DATA_WIDTH': '32'},
        'vtc': {'C_GENERATE_EN': '1', 'C_HAS_AXI4_LITE': '1'},
        'framebuffer': {'C_M_AXI_MM_VIDEO_ADDR_WIDTH': '32', 'SAMPLES_PER_CLOCK': '1',
                        'HAS_BGR8': '1', 'MAX_DATA_WIDTH': '8'},
        'reset_touch': {'C_IS_DUAL': '1', 'C_GPIO_WIDTH': '3', 'C_ALL_OUTPUTS': '1',
                        'C_GPIO2_WIDTH': '32', 'C_ALL_INPUTS_2': '1'},
    }.items():
        for name, value in checks.items():
            parameter(modules[key], name, value)
    touch = module('touch_pl', 'xilinx.com:module_ref:gt911_pl_bridge:1.0')
    source = port(touch, 'packet', {'DIR': 'O', 'LEFT': '31', 'RIGHT': '0'})
    sink = port(modules['reset_touch'], 'gpio2_io_i', {'DIR': 'I', 'LEFT': '31', 'RIGHT': '0'})
    if not source.get('SIGNAME') or source.get('SIGNAME') != sink.get('SIGNAME'):
        raise ValueError('MD0700R touch packet is disconnected from GPIO channel 2')
    port(touch, 'clk', {'CLKFREQUENCY': '100000000'})
    port(modules['vtc'], 'clk', {'CLKFREQUENCY': '51200000'})
    return expected_contract()
