# Only after trial_ge_pl.sh and physical Ethernet validation have succeeded.
set -eu
test "$(id -u)" = 0
release=/home/xilinx/tcb705_releases/20261017_ge_pl_r2/ZYNQArm
backup=/home/xilinx/tcb705_deploy_backups/20261017_ge_pl_r2
test -e "$backup/previous_ready.json"
cd "$release"
export XILINX_XRT=/usr OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from scripts.start_ge_pl import check_platform
root=Path.cwd();python=root/'.venv/bin/python';manifest=root/'overlay/tcb705_ge_pl/platform.json'
cfg,_=check_platform(manifest)
assert json.loads(Path('/run/tcb705-ge-pl.json').read_text())['build_id']==cfg['build_id']
assert Path('/sys/class/net/eth1/carrier').read_text().strip()=='1', 'GE_PL physical link is down'
units={
'so101-platform':f'''[Service]
WorkingDirectory={root}
ExecStart=
ExecStart={python} -B {root}/scripts/load_platform.py --manifest {manifest} --backend-port 8785
''',
'tcb705-ui':f'''[Service]
WorkingDirectory={root}
Environment=TCB705_PL_MANIFEST={manifest}
ExecStart=
ExecStart={python} -B {root}/scripts/run_tcb705.py --allow-real --no-browser --data-dir /home/xilinx/tcb705_data --secrets-file /home/xilinx/.config/so101/secrets.local.json
''',
'so101-md0700r':f'''[Service]
WorkingDirectory={root}
ExecStart=
ExecStart={python} -B {root}/deploy/pynq-md0700r/md0700r_display.py --runtime {root} --platform-manifest {manifest} --gui-user xilinx --data-dir /home/xilinx/tcb705_data --port 8785 --user-ui-port 8095
''',
'so101-gt911':f'''[Service]
WorkingDirectory={root}
ExecStart=
ExecStart={python} -B {root}/deploy/pynq-md0700r/gt911_input.py --runtime {root} --platform-manifest {manifest}
'''}
for unit,content in units.items():
    directory=Path('/etc/systemd/system')/(unit+'.service.d');directory.mkdir(exist_ok=True)
    (directory/'zzzzzzz-tcb705-ge-pl.conf').write_text(content)
Path('/etc/systemd/system/tcb705-ge-pl.service').write_text(f'''[Unit]
Description=TCB705 GE_PL Ethernet after verified FPGA initialization
Requires=so101-platform.service
After=so101-platform.service
Before=tcb705-ui.service
PartOf=so101-platform.service
[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory={root}
ExecStart={python} -B {root}/scripts/start_ge_pl.py --manifest {manifest}
TimeoutStartSec=45
[Install]
WantedBy=multi-user.target
''')
PY
ln -sfn "$release" /home/xilinx/ZYNQArm
systemctl daemon-reload
systemctl enable tcb705-ge-pl.service
systemctl start so101-platform.service tcb705-ge-pl.service
systemctl start tcb705-ui.service so101-md0700r.service so101-gt911.service
