"""Optional audio contract. Validate the boot receipt before mapping AXI."""
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from . import contract as c


def validate_hwh(path):
    root = ET.parse(path).getroot()
    ranges = {(int(m.get('BASEVALUE'), 0), int(m.get('HIGHVALUE'), 0))
              for m in root.iter('MEMRANGE') if m.get('INSTANCE') == c.IP_NAME}
    if ranges != {(c.BASE, c.BASE + c.SIZE - 1)}:
        raise ValueError('Audio address differs from the 0x40060000 / 64K contract')
    modules = [m for m in root.iter('MODULE') if m.get('INSTANCE') == c.IP_NAME]
    if len(modules) != 1:
        raise ValueError('Expected one audio_out_0 module')
    clocks = [p for p in modules[0].iter('PORT') if p.get('NAME') == 's_axi_aclk']
    if len(clocks) != 1 or int(clocks[0].get('CLKFREQUENCY', '0')) != 100000000:
        raise ValueError('Audio requires the 100 MHz peripheral clock')
    return dict(abi=c.ABI, ip_name=c.IP_NAME, base=c.BASE, size=c.SIZE,
                identity=c.IDENTITY, version=c.VERSION, clock_hz=100000000,
                sample_rate=c.SAMPLE_RATE, fifo_samples=16384)


def validate_manifest_section(cfg, directory, bit):
    expected = validate_hwh(Path(bit).with_suffix('.hwh'))
    if cfg.get('audio') != expected:
        raise ValueError('Audio manifest differs from hardware contract')
    return expected


def attached_audio():
    from tcb705.accel_runtime import platform_manifest, attached_identity
    path = platform_manifest()
    if path is None:
        raise RuntimeError('当前平台尚未配置朗读模块')
    # Read the declaration first; a legacy platform must never probe this AXI address.
    cfg = json.loads(path.read_text(encoding='utf-8'))
    if not cfg.get('audio'):
        raise RuntimeError('当前 FPGA 未包含朗读模块，更新并重启后可用')
    cfg, _, _, _, _ = attached_identity()
    return validate_manifest_section(cfg, path.parent, path.parent / cfg['bitfile'])
