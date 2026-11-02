#!/bin/sh
# Run from the project root, inside the PYNQ-compatible Python environment.
# Builds/tests only. Does not install a service, load an FPGA image or move a robot.
set -eu
test -f scripts/build_tcb705.py
test "$(getconf LONG_BIT)" = 32
case "$(uname -m)" in armv7*) ;; *) echo 'Expected Linux ARMv7 armhf' >&2; exit 2;; esac
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
python3 scripts/build_tcb705.py --sdk
python3 -m unittest discover -s tests -p test_tcb705.py -v
python3 -m unittest discover -s tests -p test_armvision_calibration.py -v
python3 scripts/tcb705_demo.py --shape two-strokes --output build/tcb705/board-demo
