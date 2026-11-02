"""Remove only this release's overrides, restore the previous selection, then reboot.

sudo /home/xilinx/tcb705_releases/20261024_vision_r1/ZYNQArm/.venv/bin/python deploy/tcb705/vision/rollback.py
"""
import os,subprocess
from pathlib import Path
BACKUP=Path('/home/xilinx/tcb705_deploy_backups/20261024_vision_r1')
if os.geteuid()!=0:raise PermissionError('root required')
previous=Path((BACKUP/'previous_release.txt').read_text().strip())
if not (previous/'scripts/load_platform.py').is_file():raise RuntimeError('previous release missing')
for unit in ('so101-platform','tcb705-ui','so101-md0700r','so101-gt911','tcb705-ge-pl'):
 p=Path('/etc/systemd/system')/(unit+'.service.d')/'zzzzzzzzzzzzzzzzzz-vision.conf'
 if p.exists():p.unlink()
link=Path('/home/xilinx/ZYNQArm');temporary=link.with_name('ZYNQArm.rollback.tmp')
if temporary.is_symlink():temporary.unlink()
temporary.symlink_to(previous);temporary.replace(link)
subprocess.run(['systemctl','daemon-reload'],check=True)
print('PREVIOUS_BOOT_SELECTION_RESTORED; reboot required; no live FPGA reload')
