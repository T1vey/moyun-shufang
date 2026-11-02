#!/bin/sh
# Deploy the web-program executor to the ZYNQ (run from the PC in Git Bash):
#   sh deploy/tcb705/deploy_web_executor.sh [board_ip]
# Needs key-based SSH (fix_board_key.ps1). Backs up every replaced file on the board,
# runs the TCB705 tests with the board's python3, installs the web profile as the
# machine config and restarts tcb705-ui. Does not move the arm.
set -eu
HOST=${1:-192.168.2.99}
U=xilinx
SSH="ssh -o BatchMode=yes -o ConnectTimeout=8 $U@$HOST"
cd "$(dirname "$0")/../.."
FILES="tcb705/web_control.py tcb705/web_executor.py tcb705/kinematic_fit.py tcb705/bridge.py tcb705/workbench.py
tcb705/config.py tcb705/calibration.py tcb705/planner.py tcb705/artifact.py
scripts/tcb705_web_draw.py scripts/tcb705_calibrate_capture.py
robots/tcb705/profile.armvision_web.json tests/test_tcb705_web.py tests/test_tcb705_kinfit.py"
STAMP=$(date +%Y%m%d_%H%M%S)
BK=/home/xilinx/tcb705_deploy_backups/web_executor_$STAMP
echo "== backup on board: $BK"
$SSH "set -e; mkdir -p $BK; cd /home/xilinx/ZYNQArm; for f in $(echo $FILES); do [ -f \$f ] && mkdir -p $BK/\$(dirname \$f) && cp -p \$f $BK/\$f || true; done; [ -f /home/xilinx/tcb705_data/tcb705.machine.json ] && cp -p /home/xilinx/tcb705_data/tcb705.machine.json $BK/ || true; echo backed up"
echo "== copy files"
tar -cf - $FILES | $SSH "cd /home/xilinx/ZYNQArm && tar -xf - && echo copied"
echo "== tests on board"
$SSH "cd /home/xilinx/ZYNQArm && python3 -m unittest tests.test_tcb705_web tests.test_tcb705_kinfit tests.test_tcb705 2>&1 | tail -5"
echo "== install web profile as machine config + restart UI"
$SSH "cp /home/xilinx/ZYNQArm/robots/tcb705/profile.armvision_web.json /home/xilinx/tcb705_data/tcb705.machine.json && sudo -n systemctl restart tcb705-ui && sleep 8 && systemctl is-active tcb705-ui"
echo "== backend status"
$SSH "curl -s http://127.0.0.1:8785/api/status | head -c 600; echo"
echo "rollback: copy files back from $BK on the board"
