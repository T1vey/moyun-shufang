#!/bin/sh
set -eu
root=/home/xilinx/tcb705_releases/20261020_lineart_r1/ZYNQArm
scratch=/home/xilinx/lineart_board_acceptance_20261020
for unit in so101-platform tcb705-ui so101-md0700r so101-gt911 tcb705-ge-pl; do
    systemctl is-active --quiet "$unit"
done
python3 - <<'PY'
import json,pathlib,urllib.request
for name in ('status.json','touch.json'):
 data=json.loads((pathlib.Path('/run/so101-lcd')/name).read_text())
 assert data['status']=='RUNNING'
with urllib.request.urlopen('http://127.0.0.1:8785/api/jobs',timeout=5) as r:
 assert not json.load(r).get('active'),'active UI job'
print('GUI_ACTIVE_BENCHMARK_BEGIN',flush=True)
PY
export XILINX_XRT=/usr TCB705_PL_MANIFEST="$root/overlay/tcb705/platform.json"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
cd "$root"
.venv/bin/python tools/verify_lineart_gallery.py --images "$scratch/gallery" --output "$scratch/gallery_active_gui.json" --pl --limit 3
for unit in so101-platform tcb705-ui so101-md0700r so101-gt911 tcb705-ge-pl; do
    systemctl is-active --quiet "$unit"
done
printf 'GUI_ACTIVE_BENCHMARK_PASS\n'
