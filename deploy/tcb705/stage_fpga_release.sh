set -eu
release=/home/xilinx/tcb705_releases/20261017_fpga_batch_r2
archive=/home/xilinx/TCB705_20261017_fpga_batch_r2.zip
test ! -e "$release"
mkdir -p "$release"
python3 - "$archive" "$release" <<'PY'
import hashlib,json,pathlib,sys,zipfile
archive,destination=map(pathlib.Path,sys.argv[1:])
with zipfile.ZipFile(archive) as z:
    for item in z.infolist():
        if destination.resolve() not in (destination/item.filename).resolve().parents:raise ValueError('unsafe archive path')
    z.extractall(destination)
root=destination/'ZYNQArm';manifest=json.loads((root/'DELIVERY_SHA256.json').read_text())
for name,expected in manifest.items():
    if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:raise ValueError('source hash mismatch: '+name)
print('SOURCE_VERIFIED',len(manifest),flush=True)
PY
cd "$release/ZYNQArm"
ln -s /home/xilinx/tcb705_releases/20261017_armvision/ZYNQArm/.venv .venv
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
# Prevent any hardware attachment in the isolated software regression phase.
export TCB705_PL_MANIFEST="$release/not_loaded_platform.json"
.venv/bin/python scripts/build_tcb705.py --sdk
.venv/bin/python scripts/verify_tcb705.py --output build/tcb705/verification_final_board
.venv/bin/python scripts/load_platform.py --check --manifest overlay/tcb705/platform.json
printf 'TCB705_SOURCE_AND_PLATFORM_READY_FOR_MAINTENANCE\n'
