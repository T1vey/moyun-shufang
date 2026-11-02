# Run as root only after stage_fpga_release.sh succeeds. No robot commands.
set -eu
test "$(id -u)" = 0
release=/home/xilinx/tcb705_releases/20261017_fpga_batch_r2/ZYNQArm
backup=/home/xilinx/tcb705_deploy_backups/20261017_fpga_batch_r2
test -d "$release"
test -L /home/xilinx/ZYNQArm
test ! -e "$backup"
cd "$release"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1 XILINX_XRT=/usr
export TCB705_PL_MANIFEST="$release/overlay/tcb705/platform.json"
.venv/bin/python - <<'PY'
import json,urllib.request
from pathlib import Path
for port in (8785,8765):
    with urllib.request.urlopen('http://127.0.0.1:%d/api/jobs'%port,timeout=5) as r:doc=json.load(r)
    if doc.get('active'):raise RuntimeError('Wait for current job before maintenance on port '+str(port))
report=json.loads(Path('build/tcb705/verification_final_board/report.json').read_text())
assert report['passed'] and report['tests']>=151,'Final ARM software tests have not passed'
print('MAINTENANCE_PREFLIGHT_PASS',flush=True)
PY
.venv/bin/python scripts/load_platform.py --check --manifest "$TCB705_PL_MANIFEST"
mkdir -p "$backup/units"
readlink -f /home/xilinx/ZYNQArm > "$backup/previous_release.txt"
for unit in so101-platform so101-workbench tcb705-ui so101-md0700r so101-gt911; do
    systemctl is-enabled "$unit" > "$backup/$unit.enabled" || true
    systemctl cat "$unit" > "$backup/$unit.effective.txt"
    for source in "/etc/systemd/system/$unit.service" "/etc/systemd/system/$unit.service.d"; do
        if test -e "$source"; then cp -a "$source" "$backup/units/"; fi
    done
done
cp /run/so101-platform/ready.json "$backup/previous_ready.json"
# Drain consumers in order. All DMA-owning units have unlimited stop time.
systemctl stop so101-gt911.service
systemctl stop so101-md0700r.service
systemctl stop so101-workbench.service
systemctl stop tcb705-ui.service
systemctl stop so101-platform.service
.venv/bin/python - <<'PY'
from pathlib import Path
from planner_accel_lease import acquire_planner_lease
for name in ('status.json','touch.json'):
    if (Path('/run/so101-lcd')/name).exists():raise RuntimeError('Display/touch did not drain')
with acquire_planner_lease(0x40000000):pass
print('DMA_CONSUMERS_DRAINED',flush=True)
PY
mv /run/so101-platform/ready.json "$backup/retired_ready.json"
# Actual PL programming and independent CPU-vs-PL IK/FK self-test.
.venv/bin/python scripts/load_platform.py --manifest "$TCB705_PL_MANIFEST" --backend-port 8785
.venv/bin/python - <<'PY'
from pathlib import Path
root=Path.cwd();python=root/'.venv/bin/python';manifest=root/'overlay/tcb705/platform.json'
units={
'so101-platform':f'''[Unit]
Before=tcb705-ui.service
[Service]
WorkingDirectory={root}
Environment=XILINX_XRT=/usr OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
ExecStart=
ExecStart={python} -B {root}/scripts/load_platform.py --manifest {manifest} --backend-port 8785
TimeoutStartSec=infinity
TimeoutStopSec=infinity
''',
'tcb705-ui':f'''[Unit]
Requires=so101-platform.service
After=so101-platform.service
PartOf=so101-platform.service
[Service]
User=root
WorkingDirectory={root}
Environment=XILINX_XRT=/usr TCB705_PL_MANIFEST={manifest}
ExecStart=
ExecStart={python} -B {root}/scripts/run_tcb705.py --allow-real --no-browser --data-dir /home/xilinx/tcb705_data --secrets-file /home/xilinx/.config/so101/secrets.local.json
KillMode=mixed
TimeoutStopSec=infinity
''',
'so101-md0700r':f'''[Unit]
BindsTo=
BindsTo=tcb705-ui.service so101-platform.service
After=
After=tcb705-ui.service so101-platform.service
PartOf=
PartOf=tcb705-ui.service so101-platform.service
[Service]
WorkingDirectory={root}
Environment=XILINX_XRT=/usr
ExecStart=
ExecStart={python} -B {root}/deploy/pynq-md0700r/md0700r_display.py --runtime {root} --platform-manifest {manifest} --gui-user xilinx --data-dir /home/xilinx/tcb705_data --port 8785 --user-ui-port 8095
TimeoutStopSec=infinity
''',
'so101-gt911':f'''[Service]
WorkingDirectory={root}
ExecStart=
ExecStart={python} -B {root}/deploy/pynq-md0700r/gt911_input.py --runtime {root} --platform-manifest {manifest}
'''}
for unit,content in units.items():
    folder=Path('/etc/systemd/system')/(unit+'.service.d');folder.mkdir(exist_ok=True)
    destination=folder/'zzzzzz-tcb705-sevenaxis.conf'
    if destination.exists():raise RuntimeError('New platform drop-in already exists: '+str(destination))
    destination.write_text(content)
print('SEVEN_AXIS_BOOT_SERVICES_INSTALLED',flush=True)
PY
# Empty dependency directives in a drop-in do not remove the base unit's
# BindsTo/PartOf. Replace that base unit, whose original is already backed up.
.venv/bin/python deploy/tcb705/write_display_service.py
ln -sfn "$release" /home/xilinx/ZYNQArm
systemctl disable so101-workbench.service
systemctl daemon-reload
systemctl enable so101-platform.service tcb705-ui.service so101-md0700r.service so101-gt911.service
systemctl start so101-platform.service
systemctl start tcb705-ui.service
systemctl start so101-md0700r.service
systemctl start so101-gt911.service
printf 'SEVEN_AXIS_PLATFORM_PROGRAMMED_AND_SERVICES_STARTED\n'
