set -eu
uname -a
ip -brief address
systemctl is-active tcb705-ui so101-platform so101-md0700r so101-gt911
readlink -f /home/xilinx/ZYNQArm
cat /run/so101-platform.json 2>/dev/null || true
