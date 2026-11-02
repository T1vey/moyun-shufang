"""Remove only this release's overrides, restore prior selection, then reboot."""
import os,subprocess
from pathlib import Path
BACKUP=Path('/home/xilinx/tcb705_deploy_backups/20261020_lineart_r1')
if os.geteuid()!=0:raise PermissionError('root required')
previous=Path((BACKUP/'previous_release.txt').read_text().strip())
if not (previous/'scripts/load_platform.py').is_file():raise RuntimeError('previous release missing')
for unit in ('so101-platform','tcb705-ui','so101-md0700r','so101-gt911','tcb705-ge-pl'):
 p=Path('/etc/systemd/system')/(unit+'.service.d')/'zzzzzzzzzzzz-lineart.conf'
 if p.exists():p.unlink()
link=Path('/home/xilinx/ZYNQArm');temporary=link.with_name('ZYNQArm.rollback.tmp')
temporary.symlink_to(previous);temporary.replace(link)
subprocess.run(['systemctl','daemon-reload'],check=True)
print('PREVIOUS_BOOT_SELECTION_RESTORED; reboot required; no live FPGA reload')
