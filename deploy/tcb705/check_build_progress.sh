set -eu
ps -eo pid,ppid,etimes,%cpu,rss,args | grep -E 'verify_tcb705|unittest|tcb_runner|build_tcb705' | grep -v grep || true
free -m
find /home/xilinx/tcb705_releases/20261017_armvision/ZYNQArm/build/tcb705/board_verification -maxdepth 1 -type f -printf '%f %s bytes\n' 2>/dev/null || true
ip -brief -4 address
ip -4 route
