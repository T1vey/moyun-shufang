set -eu
root=/home/xilinx/lineart_cpu_validation_20261020
test ! -e "$root"
mkdir "$root"
python3 -m zipfile -e /home/xilinx/lineart_cpu_validation.zip "$root"
cd "$root"
previous=$(readlink -f /home/xilinx/ZYNQArm)
ln -s "$(readlink -f "$previous/.venv")" .venv
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
.venv/bin/python native/build_lineart.py
.venv/bin/python tools/verify_lineart_gallery.py --images gallery --output cpu_gallery.json
