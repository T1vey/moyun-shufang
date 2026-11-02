"""Attach Navigator GE_PL after verified PL load. No robot/motion commands.

Full FPGA reconfiguration after GEM1 attachment requires a reboot. Linux 5.4's
converter driver has no remove callback; do not hot-remove a live MDIO overlay.
"""
import argparse
import ipaddress
import json
import mmap
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_runtime import validate_manifest, validate_attached
from tcb705.ge_pl_contract import CONTRACT

GEM1 = Path('/sys/bus/platform/devices/e000c000.ethernet')
OVERLAY = Path('/sys/kernel/config/device-tree/overlays/tcb705-ge-pl')


def gem1_interfaces():
    return sorted(p.name for p in (GEM1/'net').glob('*'))


def check_platform(manifest):
    cfg, bit, _, _, hashes, _, _ = validate_manifest(manifest, platform.release())
    validate_attached(bit, cfg['ip_name'], hashes, manifest, kernel_release=platform.release())
    network = cfg.get('ge_pl')
    if network != CONTRACT:
        raise ValueError('Missing or unsupported sealed GE_PL contract')
    if platform.release() != network['kernel_release']:
        raise ValueError('GE_PL kernel version differs from verified driver')
    if network['dtbo'] not in cfg['files']:
        raise ValueError('GE_PL DTBO is not sealed')
    return cfg, Path(manifest).resolve().parent/network['dtbo']


def configure_gem1_clocks():
    # UG585 / generated ps7_init: only select GEM1 RX/TX from EMIO.
    # Never run ps7_init wholesale against running Linux (DDR/PLL/GE_PS).
    fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
    try:
        with mmap.mmap(fd, 4096, flags=mmap.MAP_SHARED,
                       prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=0xf8000000) as mem:
            read = lambda off: struct.unpack_from('<I', mem, off)[0]
            # PYNQ has programmed FCLK2. Check the actual board 33.333333 MHz reference.
            pll = (read(0x108) >> 12) & 0x7f
            fclk = read(0x190)
            d0, d1 = (fclk >> 8) & 63, (fclk >> 20) & 63
            if (fclk >> 4) & 3 or not d0 or not d1:
                raise RuntimeError('FCLK2 must use the IO PLL and valid divisors')
            hz = (100000000.0 / 3) * pll / d0 / d1
            if abs(hz - 200000000) > 1000:
                raise RuntimeError('GE_PL FCLK2 is not 200 MHz: '+str(hz))
            before = {hex(off): read(off) for off in (0x13c, 0x144)}
            # Linux arch/arm/mach-zynq/slcr.c leaves SLCR unlocked at boot.
            # Its clock driver writes gates without unlocking for each write.
            # Relocking here silently prevents GEM1 APER enable (PHY probe EIO)
            # and can also prevent a later PS software reset.
            struct.pack_into('<I', mem, 0x008, 0xdf0d)  # SLCR unlock
            for off, mask, value in ((0x13c, 0x11, 0x11), (0x144, 0x41, 0x41)):
                struct.pack_into('<I', mem, off, (read(off) & ~mask) | value)
                if read(off) & mask != value:
                    raise RuntimeError('GEM1 clock register write failed')
            return {'fclk2_hz': hz, 'before': before,
                    'after': {hex(off): read(off) for off in (0x13c, 0x144)}}
    finally:
        os.close(fd)


def release_phy():
    chips = [p for p in Path('/sys/class/gpio').glob('gpiochip*')
             if (p/'label').read_text().strip() == 'zynq_gpio']
    if len(chips) != 1:
        raise RuntimeError('Expected one Zynq PS GPIO controller')
    number = int((chips[0]/'base').read_text()) + 54
    pin = Path('/sys/class/gpio')/('gpio'+str(number))
    if pin.exists():
        raise RuntimeError('PHY reset GPIO already owned; reboot before retrying')
    Path('/sys/class/gpio/export').write_text(str(number))
    (pin/'direction').write_text('low')
    time.sleep(.02)
    (pin/'value').write_text('1')
    time.sleep(.2)
    return number


def configure_address(iface, path):
    if not path.exists():
        return None
    cfg = json.loads(path.read_text())
    address = ipaddress.IPv4Interface(cfg['address'])
    peer_value = cfg.get('peer_ip', cfg.get('controller_ip'))
    if 'peer_ip' in cfg and 'controller_ip' in cfg and cfg['peer_ip'] != cfg['controller_ip']:
        raise ValueError('Conflicting wired peer addresses')
    peer = ipaddress.IPv4Address(peer_value)
    if (address.network.prefixlen < 24 or peer not in address.network
            or address.ip == peer or address.ip in
            (address.network.network_address, address.network.broadcast_address)):
        raise ValueError('Invalid dedicated wired subnet/address')
    # Prevent ambiguous routing through GE_PS/Wi-Fi. No gateway is added.
    existing = json.loads(subprocess.check_output(['ip', '-j', '-4', 'address', 'show']))
    for row in existing:
        if row['ifname'] == iface:
            continue
        for info in row.get('addr_info', []):
            other = ipaddress.IPv4Interface(info['local']+'/'+str(info['prefixlen']))
            if address.network.overlaps(other.network):
                raise ValueError('Wired subnet overlaps '+row['ifname'])
    subprocess.run(['ip', 'address', 'replace', str(address), 'dev', iface], check=True)
    return dict(address=str(address), **{('peer_ip' if 'peer_ip' in cfg else 'controller_ip'):str(peer)})


def start(manifest, network_config=Path('/home/xilinx/tcb705_data/ge_pl_network.json')):
    import fcntl
    if os.geteuid() != 0:
        raise PermissionError('Root is required for GE_PL bring-up')
    cfg, dtbo = check_platform(manifest)
    with open('/run/lock/tcb705-ge-pl.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if OVERLAY.exists() or gem1_interfaces():
            receipt = Path('/run/tcb705-ge-pl.json')
            if receipt.exists() and json.loads(receipt.read_text())['build_id'] == cfg['build_id']:
                interfaces=gem1_interfaces()
                if len(interfaces)!=1:
                    raise RuntimeError('GE_PL receipt exists without its network interface')
                info=json.loads(receipt.read_text())
                info['network']=configure_address(interfaces[0],network_config)
                receipt.write_text(json.dumps(info,indent=2)+'\n')
                print('GE_PL_ALREADY_READY', interfaces); return
            raise RuntimeError('GEM1 already attached; reboot before changing its platform')
        clocks = configure_gem1_clocks()
        gpio = release_phy()
        # Keep this dedicated wired port from acquiring a default route via NM.
        # Match only this platform's dedicated locally administered MAC.
        rules = Path('/run/udev/rules.d')
        rules.mkdir(parents=True, exist_ok=True)
        (rules/'79-tcb705-ge-pl.rules').write_text(
            'SUBSYSTEM=="net", ATTR{address}=="02:0a:35:00:22:02", ENV{NM_UNMANAGED}="1"\n')
        subprocess.run(['udevadm', 'control', '--reload-rules'], check=True)
        OVERLAY.mkdir()
        (OVERLAY/'dtbo').write_bytes(dtbo.read_bytes())
        deadline = time.monotonic()+15
        while not gem1_interfaces() and time.monotonic() < deadline:
            time.sleep(.2)
        interfaces = gem1_interfaces()
        if len(interfaces) != 1:
            raise RuntimeError('GEM1 driver did not create a network interface; inspect dmesg, then reboot')
        iface = interfaces[0]
        subprocess.run(['ip', 'link', 'set', 'dev', iface, 'up'], check=True)
        address = configure_address(iface, network_config)
        receipt = dict(build_id=cfg['build_id'], interface=iface, reset_gpio=gpio, clocks=clocks, network=address)
        Path('/run/tcb705-ge-pl.json').write_text(json.dumps(receipt, indent=2)+'\n')
        print('GE_PL_READY', json.dumps(receipt), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--network-config', type=Path, default=Path('/home/xilinx/tcb705_data/ge_pl_network.json'))
    args = parser.parse_args()
    start(args.manifest, args.network_config)
