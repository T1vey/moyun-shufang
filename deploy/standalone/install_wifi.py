"""Install a built 8733bu module only for the currently running kernel."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('build_directory', type=Path)
    a = p.parse_args()
    if os.geteuid() != 0:
        raise PermissionError('Run as root')
    module = a.build_directory / '8733bu.ko'
    meta = json.loads((a.build_directory / 'wifi-build.json').read_text())
    actual = subprocess.check_output(['modinfo', '-F', 'vermagic', str(module)], text=True).strip()
    if (meta['kernel_release'] != platform.release() or meta['vermagic'] != actual or
            actual.split()[0] != platform.release() or
            hashlib.sha256(module.read_bytes()).hexdigest() != meta['sha256']):
        raise ValueError('WiFi module/kernel identity mismatch; no files installed')
    dest = Path('/lib/modules') / platform.release() / 'extra/8733bu.ko'
    dest.parent.mkdir(exist_ok=True)
    if dest.exists():
        raise ValueError('An installed 8733bu module already exists; compare it before replacing')
    shutil.copy2(module, dest)
    try:
        subprocess.run(['depmod', '-a'], check=True)
        subprocess.run(['modprobe', '8733bu'], check=True)
    except subprocess.CalledProcessError:
        dest.unlink()
        subprocess.run(['depmod', '-a'], check=True)
        raise
    print('Driver loaded. Use nmcli --ask device wifi connect SSID; Ethernet configuration is unchanged.')


if __name__ == '__main__':
    main()
