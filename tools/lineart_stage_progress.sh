#!/bin/sh
set -eu
ps -eo pid,comm,etime,pcpu,pmem | grep -E '(cc1plus|g\+\+|python|PID)' || true
find /home/xilinx/tcb705_releases/20261020_lineart_r1/ZYNQArm/build/tcb705 -maxdepth 1 -type f -printf '%f %s bytes\n' | sort
free -m
