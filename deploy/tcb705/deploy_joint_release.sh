#!/bin/sh
# Stage the joint-mode release on the ZYNQ (run from the PC, Git Bash):
#   sh deploy/tcb705/deploy_joint_release.sh [board_ip]
# 1. copy the active v2c release (same FPGA platform, .venv, built natives) to a new release dir
# 2. overlay the current sources (controller-DH calibration, joint mode, planner speedups)
# 3. rebuild the native core on the board, run the TCB705 tests there
# 4. install the joint profile as the machine config (old one backed up)
# No sudo, no service change, no robot motion. Services are switched by
# deploy/tcb705/activate_joint_release.sh (needs sudo, run on the board).
set -eu
HOST=${1:-192.168.2.99}
SSH="ssh -o BatchMode=yes -o ConnectTimeout=8 xilinx@$HOST"
SRC_RELEASE=/home/xilinx/tcb705_releases/20261018_v2c_ge_pl_r1/ZYNQArm
NEW=/home/xilinx/tcb705_releases/20261018_joint_r1
cd "$(dirname "$0")/../.."
echo "== 1. new release $NEW (copy of the v2c release)"
$SSH "set -e; test -d $SRC_RELEASE; if [ -e $NEW ]; then echo 'exists, reusing'; else mkdir -p $NEW && cp -a $SRC_RELEASE $NEW/; fi"
echo "== 2. overlay sources"
tar --exclude=__pycache__ --exclude='*.pyc' -cf - tcb705 native scripts robots tests deploy docs hls_source user_gui app.py workbench.py \
    stroke_paths.py path_quality.py vision.py README.md requirements-tcb705.txt | $SSH "cd $NEW/ZYNQArm && tar -xf - && echo overlaid"
echo "== 3. build native core (+SDK probe) and test on the board"
$SSH "cd $NEW/ZYNQArm && export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 && .venv/bin/python scripts/build_tcb705.py --sdk 2>&1 | tail -2 && \
  .venv/bin/python -m unittest discover -s tests -p 'test_tcb705*.py' 2>&1 | tail -3"
echo "== 4. machine config is installed by activate_joint_release.sh (the file is root-owned)"
echo "staged: $NEW  -> next (on the board, needs sudo): sh $NEW/ZYNQArm/deploy/tcb705/activate_joint_release.sh"
