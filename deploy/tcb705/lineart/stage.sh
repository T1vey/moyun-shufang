#!/bin/sh
# Isolated installation only. No service changes, FPGA writes or robot commands.
set -eu
release=/home/xilinx/tcb705_releases/20261020_lineart_r1
archive=/home/xilinx/TCB705_20261020_lineart_r1.zip
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
 if root.resolve() not in (root/name).resolve().parents:raise ValueError('unsafe manifest path')
 if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:raise ValueError('source hash mismatch: '+name)
assert json.loads((root/'overlay/tcb705/platform.json').read_text())['lineart']['stages']==8
print('SOURCE_VERIFIED',flush=True)
PY
cd "$release/ZYNQArm"
previous=$(readlink -f /home/xilinx/ZYNQArm)
test -x "$previous/.venv/bin/python"
ln -s "$(readlink -f "$previous/.venv")" .venv
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
export TCB705_PL_MANIFEST="$release/not_loaded_platform.json"
.venv/bin/python scripts/build_tcb705.py --sdk
.venv/bin/python scripts/verify_tcb705.py --output build/tcb705/verification_lineart_board
.venv/bin/python scripts/load_platform.py --check --manifest overlay/tcb705/platform.json
printf 'LINEART_STAGE_PASS\n'
