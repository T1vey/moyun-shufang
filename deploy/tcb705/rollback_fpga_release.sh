# Explicit rollback after inspecting a failed activation; never deletes DMA markers.
set -eu
test "$(id -u)" = 0
backup=/home/xilinx/tcb705_deploy_backups/20261017_fpga_batch_r2
test -f "$backup/previous_release.txt"
previous=$(cat "$backup/previous_release.txt")
oldplatform=/home/xilinx/so101_releases/release_planner_20261011_a8f65f66/so101_planner_runtime
systemctl stop so101-gt911.service so101-md0700r.service
systemctl stop tcb705-ui.service so101-workbench.service so101-platform.service
cd "$oldplatform"
export XILINX_XRT=/usr OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
.venv/bin/python - <<'PY'
from pathlib import Path
from planner_accel_lease import acquire_planner_lease
for name in ('status.json','touch.json'):
    if (Path('/run/so101-lcd')/name).exists():raise RuntimeError('Display/touch still active')
with acquire_planner_lease(0x40000000):pass
PY
if test -f /run/so101-platform/ready.json; then
    mv /run/so101-platform/ready.json "$backup/rolled_back_seven_axis_ready.json"
fi
.venv/bin/python scripts/load_platform.py --manifest overlay/planner_platform/platform.json
for unit in so101-platform tcb705-ui so101-md0700r so101-gt911; do
    rm -f "/etc/systemd/system/$unit.service.d/zzzzzz-tcb705-sevenaxis.conf"
done
cp -a "$backup/units/so101-md0700r.service" /etc/systemd/system/so101-md0700r.service
ln -sfn "$previous" /home/xilinx/ZYNQArm
systemctl daemon-reload
for unit in so101-platform so101-workbench tcb705-ui so101-md0700r so101-gt911; do
    if test "$(cat "$backup/$unit.enabled")" = enabled; then systemctl enable "$unit"; fi
done
systemctl start so101-platform.service so101-workbench.service tcb705-ui.service so101-md0700r.service so101-gt911.service
printf 'PREVIOUS_PLATFORM_RESTORED\n'
