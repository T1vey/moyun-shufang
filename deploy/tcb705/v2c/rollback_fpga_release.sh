#!/bin/sh
# Restores the exact previous boot selection. Reboot is mandatory after GE_PL.
set -eu
test "$(id -u)" = 0
backup=/home/xilinx/tcb705_deploy_backups/20261018_v2c_ge_pl_r1
test -f "$backup/previous_release.txt"
previous=$(cat "$backup/previous_release.txt")
test -d "$previous"
systemctl stop so101-gt911.service so101-md0700r.service
systemctl stop tcb705-ui.service so101-workbench.service
if systemctl cat tcb705-ge-pl.service >/dev/null 2>&1; then systemctl stop tcb705-ge-pl.service; fi
systemctl stop so101-platform.service
python3 - <<'PY'
from pathlib import Path
import shutil
backup=Path('/home/xilinx/tcb705_deploy_backups/20261018_v2c_ge_pl_r1')
base=Path('/etc/systemd/system')
for unit in ('so101-platform','so101-workbench','tcb705-ui','so101-md0700r','so101-gt911','tcb705-ge-pl'):
    for suffix in ('.service','.service.d'):
        dst=base/(unit+suffix);saved=backup/'units'/dst.name
        if dst.is_symlink() or dst.is_file():dst.unlink()
        elif dst.is_dir():shutil.rmtree(dst)
        if saved.is_dir():shutil.copytree(saved,dst,symlinks=True)
        elif saved.exists():shutil.copy2(saved,dst)
config=Path('/home/xilinx/tcb705_data/tcb705.machine.json')
saved=backup/config.name
if saved.exists():shutil.copy2(saved,config)
elif config.exists():config.unlink()
PY
ln -sfn "$previous" /home/xilinx/ZYNQArm
systemctl daemon-reload
for unit in so101-platform so101-workbench tcb705-ui so101-md0700r so101-gt911 tcb705-ge-pl; do
    if test "$(cat "$backup/$unit.enabled")" = enabled; then
        systemctl enable "$unit"
    else
        systemctl disable "$unit" 2>/dev/null || true
    fi
done
printf 'PREVIOUS_BOOT_SELECTION_RESTORED_REBOOT_REQUIRED\n'
# Do not download a bitstream while GEM1 is attached.
if test "${1:-}" = --reboot; then systemctl reboot; fi
