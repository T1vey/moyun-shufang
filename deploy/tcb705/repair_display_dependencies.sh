set -eu
test "$(id -u)" = 0
cd /home/xilinx/ZYNQArm
test "$(readlink -f .)" = /home/xilinx/tcb705_releases/20261017_fpga_batch_r2/ZYNQArm
test -f /home/xilinx/tcb705_deploy_backups/20261017_fpga_batch_r2/units/so101-md0700r.service
systemctl stop so101-gt911 so101-md0700r
systemctl stop so101-workbench
.venv/bin/python deploy/tcb705/write_display_service.py
systemctl daemon-reload
systemctl start so101-md0700r so101-gt911
systemctl show so101-md0700r -p BindsTo -p PartOf -p Requires
