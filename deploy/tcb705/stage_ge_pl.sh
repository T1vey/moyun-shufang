# Stage without changing the active platform or robot settings.
set -eu
release=/home/xilinx/tcb705_releases/20261017_ge_pl_r2
archive=/home/xilinx/TCB705_20261017_ge_pl_r2.zip
test ! -e "$release"
mkdir -p "$release"
python3 - "$archive" "$release" <<'PY'
import hashlib,json,pathlib,sys,zipfile
archive,destination=map(pathlib.Path,sys.argv[1:])
with zipfile.ZipFile(archive) as z:
    for item in z.infolist():
        if destination.resolve() not in (destination/item.filename).resolve().parents:raise ValueError('unsafe archive path')
    z.extractall(destination)
root=destination/'ZYNQArm'
for name,expected in json.loads((root/'DELIVERY_SHA256.json').read_text()).items():
    if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:raise ValueError('source hash mismatch: '+name)
print('GE_PL_SOURCE_VERIFIED',flush=True)
PY
cd "$release/ZYNQArm"
ln -s /home/xilinx/tcb705_releases/20261017_armvision/ZYNQArm/.venv .venv
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
export TCB705_PL_MANIFEST="$release/not_loaded_platform.json"
.venv/bin/python scripts/build_tcb705.py --sdk
.venv/bin/python scripts/verify_tcb705.py --output build/tcb705/verification_ge_pl_board
.venv/bin/python scripts/load_platform.py --check --manifest overlay/tcb705_ge_pl/platform.json
