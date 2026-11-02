#!/bin/sh
# Run after staging, as root. No controller requests or robot motion.
set -eu
test "$(id -u)" = 0
release=/home/xilinx/tcb705_releases/20261018_v2c_ge_pl_r1/ZYNQArm
backup=/home/xilinx/tcb705_deploy_backups/20261018_v2c_ge_pl_r1
test ! -e "$backup"
test -L /home/xilinx/ZYNQArm
cd "$release"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1 XILINX_XRT=/usr
export TCB705_PL_MANIFEST="$release/overlay/tcb705/platform.json"
.venv/bin/python - <<'PY'
import json,urllib.request,urllib.error
from pathlib import Path
for port in (8785,8765):
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/jobs'%port,timeout=5) as r:doc=json.load(r)
    except urllib.error.URLError as exc:
        if port==8765 and isinstance(exc.reason,ConnectionRefusedError):continue
        raise
    if doc.get('active'):raise RuntimeError('Active job; maintenance refused')
report=json.loads(Path('build/tcb705/verification_v2c_board/report.json').read_text())
assert report['passed'] and report['tests']>=152
assert {'test_tcb705_web.py','test_tcb705_kinfit.py'} <= {s['suite'] for s in report['suites']}
assert not list(Path('/sys/bus/platform/devices/e000c000.ethernet/net').glob('*')), 'GE_PL attached: use reboot maintenance, never hot-reload'
print('MAINTENANCE_PREFLIGHT_PASS',flush=True)
PY
.venv/bin/python scripts/load_platform.py --check --manifest "$TCB705_PL_MANIFEST"
mkdir -p "$backup/units"
readlink -f /home/xilinx/ZYNQArm > "$backup/previous_release.txt"
for unit in so101-platform so101-workbench tcb705-ui so101-md0700r so101-gt911 tcb705-ge-pl; do
    systemctl is-enabled "$unit" > "$backup/$unit.enabled" || true
    systemctl is-active "$unit" > "$backup/$unit.active" || true
    systemctl cat "$unit" > "$backup/$unit.effective.txt" || true
    for source in "/etc/systemd/system/$unit.service" "/etc/systemd/system/$unit.service.d"; do
        if test -e "$source"; then cp -a "$source" "$backup/units/"; fi
    done
done
if test -f /home/xilinx/tcb705_data/tcb705.machine.json; then
    cp -p /home/xilinx/tcb705_data/tcb705.machine.json "$backup/tcb705.machine.json"
fi
cp /run/so101-platform/ready.json "$backup/previous_ready.json"
systemctl stop so101-gt911.service
systemctl stop so101-md0700r.service
systemctl stop tcb705-ui.service so101-workbench.service
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
.venv/bin/python scripts/load_platform.py --manifest "$TCB705_PL_MANIFEST" --backend-port 8785
.venv/bin/python scripts/start_ge_pl.py --manifest "$TCB705_PL_MANIFEST"
.venv/bin/python - <<'PY'
from pathlib import Path
import json
root=Path.cwd();python=root/'.venv/bin/python';manifest=root/'overlay/tcb705/platform.json'
commands={
 'so101-platform':f'{python} -B {root}/scripts/load_platform.py --manifest {manifest} --backend-port 8785',
 'tcb705-ui':f'{python} -B {root}/scripts/run_tcb705.py --no-browser --data-dir /home/xilinx/tcb705_data --secrets-file /home/xilinx/.config/so101/secrets.local.json',
 'so101-md0700r':f'{python} -B {root}/deploy/pynq-md0700r/md0700r_display.py --runtime {root} --platform-manifest {manifest} --gui-user xilinx --data-dir /home/xilinx/tcb705_data --port 8785 --user-ui-port 8095',
 'so101-gt911':f'{python} -B {root}/deploy/pynq-md0700r/gt911_input.py --runtime {root} --platform-manifest {manifest}',
}
for unit,cmd in commands.items():
    directory=Path('/etc/systemd/system')/(unit+'.service.d');directory.mkdir(exist_ok=True)
    target=directory/'zzzzzzzz-tcb705-v2c.conf'
    if target.exists():raise RuntimeError('V2c drop-in exists')
    dependency='[Unit]\nRequires=tcb705-ge-pl.service\nAfter=tcb705-ge-pl.service\n' if unit=='tcb705-ui' else ''
    target.write_text(dependency+f'''[Service]
WorkingDirectory={root}
Environment=XILINX_XRT=/usr OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 TCB705_PL_MANIFEST={manifest}
ExecStart=
ExecStart={cmd}
TimeoutStopSec=infinity
''')
Path('/etc/systemd/system/tcb705-ge-pl.service').write_text(f'''[Unit]
Description=TCB705 GE_PL after verified FPGA initialization
Requires=so101-platform.service
After=so101-platform.service
Before=tcb705-ui.service
PartOf=so101-platform.service
[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory={root}
Environment=XILINX_XRT=/usr
ExecStart={python} -B {root}/scripts/start_ge_pl.py --manifest {manifest}
TimeoutStartSec=45
[Install]
WantedBy=multi-user.target
''')
profile=json.loads((root/'robots/tcb705/profile.armvision_web.json').read_text())
assert profile['sdk_mapping_verified'] is False
Path('/home/xilinx/tcb705_data/tcb705.machine.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2)+'\n')
PY
ln -sfn "$release" /home/xilinx/ZYNQArm
systemctl daemon-reload
systemctl disable so101-workbench.service
systemctl enable so101-platform.service tcb705-ge-pl.service tcb705-ui.service so101-md0700r.service so101-gt911.service
systemctl start so101-platform.service tcb705-ge-pl.service
systemctl start tcb705-ui.service so101-md0700r.service so101-gt911.service
printf 'V2C_ACTIVATED_MOTION_DISABLED\n'
