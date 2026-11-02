set -eu
release=/home/xilinx/tcb705_releases/20261017_batch_acceleration
archive=/home/xilinx/TCB705_20261017_batch_r1.zip
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
runtimepython=/home/xilinx/ZYNQArm/.venv/bin/python
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
"$runtimepython" scripts/build_tcb705.py --sdk
"$runtimepython" scripts/verify_tcb705.py --output build/tcb705/verification_batch_board
"$runtimepython" scripts/benchmark_tcb705_acceleration.py --repeat 3 --output build/tcb705/benchmark_arm.json
systemctl is-active tcb705-ui so101-md0700r so101-gt911
