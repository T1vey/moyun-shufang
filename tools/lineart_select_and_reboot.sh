#!/bin/sh
set -eu
root=/home/xilinx/tcb705_releases/20261020_lineart_r1/ZYNQArm
cat /proc/sys/kernel/random/boot_id
"$root/.venv/bin/python" "$root/deploy/tcb705/lineart/select_boot.py"
sync
shutdown -r +1 'Load verified TCB705 lineart platform'
