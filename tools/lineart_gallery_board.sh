#!/bin/sh
# Image processing only: no robot or cloud commands.
set -eu
root=/home/xilinx/tcb705_releases/20261020_lineart_r1/ZYNQArm
scratch=/home/xilinx/lineart_board_acceptance_20261020
mkdir -p "$scratch"
python3 - "$scratch" <<'PY'
import hashlib,json,pathlib,sys,zipfile
dst=pathlib.Path(sys.argv[1])
with zipfile.ZipFile('/home/xilinx/lineart_gallery.zip') as z:
 for item in z.infolist():
  if dst.resolve() not in (dst/item.filename).resolve().parents:raise ValueError('unsafe archive path')
 z.extractall(dst)
for name,expected in json.loads((dst/'sha256.json').read_text()).items():
 assert hashlib.sha256((dst/'gallery'/name).read_bytes()).hexdigest()==expected
print('GALLERY_SOURCE_VERIFIED',flush=True)
PY
export TCB705_PL_MANIFEST="$root/overlay/tcb705/platform.json"
export XILINX_XRT=/usr
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
cd "$root"
.venv/bin/python tools/verify_lineart_gallery.py --images "$scratch/gallery" --output "$scratch/gallery_pl_patch1.json" --pl
printf 'LINEART_BOARD_GALLERY_PASS\n'
