# Trial new PL without changing boot selection. On failure reboot to old build.
set -eu
test "$(id -u)" = 0
release=/home/xilinx/tcb705_releases/20261017_ge_pl_r2/ZYNQArm
backup=/home/xilinx/tcb705_deploy_backups/20261017_ge_pl_r2
test ! -e "$backup"
cd "$release"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1 XILINX_XRT=/usr
export TCB705_PL_MANIFEST="$release/overlay/tcb705_ge_pl/platform.json"
.venv/bin/python - <<'PY'
import json,urllib.request,urllib.error
from pathlib import Path
for port in (8785,8765):
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/jobs'%port,timeout=5) as r:doc=json.load(r)
    except urllib.error.URLError as exc:
        if port==8765 and isinstance(exc.reason,ConnectionRefusedError):continue
        raise
    if doc.get('active'):raise RuntimeError('Wait for current job before platform maintenance')
report=json.loads(Path('build/tcb705/verification_ge_pl_board/report.json').read_text())
assert report['passed'] and report['tests']>=152
assert not list(Path('/sys/bus/platform/devices/e000c000.ethernet/net').glob('*'))
PY
.venv/bin/python scripts/load_platform.py --check --manifest "$TCB705_PL_MANIFEST"
mkdir -p "$backup/units"
readlink -f /home/xilinx/ZYNQArm > "$backup/previous_release.txt"
for unit in so101-platform so101-workbench tcb705-ui so101-md0700r so101-gt911; do
    systemctl cat "$unit" > "$backup/$unit.effective.txt"
    for source in "/etc/systemd/system/$unit.service" "/etc/systemd/system/$unit.service.d"; do
        if test -e "$source"; then cp -a "$source" "$backup/units/"; fi
    done
done
cp /run/so101-platform/ready.json "$backup/previous_ready.json"
systemctl stop so101-gt911.service so101-md0700r.service
systemctl stop so101-workbench.service tcb705-ui.service
systemctl stop so101-platform.service
.venv/bin/python - <<'PY'
from pathlib import Path
from planner_accel_lease import acquire_planner_lease
for name in ('status.json','touch.json'):
    if (Path('/run/so101-lcd')/name).exists():raise RuntimeError('Display/touch did not drain')
with acquire_planner_lease(0x40000000):pass
PY
mv /run/so101-platform/ready.json "$backup/retired_ready.json"
.venv/bin/python scripts/load_platform.py --manifest "$TCB705_PL_MANIFEST" --backend-port 8785
.venv/bin/python scripts/start_ge_pl.py --manifest "$TCB705_PL_MANIFEST"
ip -br link
dmesg | tail -35
