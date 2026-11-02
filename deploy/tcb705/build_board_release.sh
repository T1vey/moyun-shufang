set -eu
runtime=/home/xilinx/tcb705_releases/20261017_armvision/ZYNQArm
old=/home/xilinx/so101_releases/release_planner_20261011_a8f65f66/so101_planner_runtime
cp "$old/.venv/lib/python3.8/site-packages/so101-pynq-runtime.pth" "$runtime/.venv/lib/python3.8/site-packages/pynq_runtime_dependencies.pth"
cd "$runtime"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
.venv/bin/python - <<'PY'
import numpy,PIL,cv2,serial,scipy,skimage
print('DEPS_OK',numpy.__version__,PIL.__version__,cv2.__version__,serial.__version__)
PY
.venv/bin/python scripts/build_tcb705.py --sdk
ldd -r build/tcb705/libtcb_core.so
ldd -r build/tcb705/tcb_sdk_probe
.venv/bin/python scripts/verify_tcb705.py --output build/tcb705/board_verification
printf 'BOARD_BUILD_AND_TESTS_PASSED\n'
