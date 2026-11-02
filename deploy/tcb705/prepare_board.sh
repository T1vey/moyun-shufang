set -eu
release=/home/xilinx/tcb705_releases/20261017_armvision
archive=/home/xilinx/TCB705_20261017_board.zip
test ! -e "$release"
mkdir -p "$release"
python3 - "$archive" "$release" <<'PY'
import hashlib,json,pathlib,sys,zipfile
archive,destination=map(pathlib.Path,sys.argv[1:])
with zipfile.ZipFile(archive) as z:
    for item in z.infolist():
        p=(destination/item.filename).resolve()
        if destination.resolve() not in p.parents:raise ValueError('Archive path outside release')
    z.extractall(destination)
root=destination/'ZYNQArm'
manifest=json.loads((root/'DELIVERY_SHA256.json').read_text())
for name,expected in manifest.items():
    if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:raise ValueError('Hash mismatch '+name)
print('SOURCE_SHA256_VERIFIED',len(manifest))
PY
runtime=$release/ZYNQArm
python3 -m venv --system-site-packages "$runtime/.venv"
# Reuse the already-installed ARM packages without replacing PYNQ libraries.
old=/home/xilinx/so101_releases/release_planner_20261011_a8f65f66/so101_planner_runtime
test -d "$old/.venv/lib/python3.8/site-packages"
printf '%s\n' "$old/.venv/lib/python3.8/site-packages" > "$runtime/.venv/lib/python3.8/site-packages/pynq_existing_packages.pth"
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
