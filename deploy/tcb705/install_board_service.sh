# Install the validated ARM release. Retain the sealed display/GT911 FPGA platform.
set -eu
runtime=/home/xilinx/tcb705_releases/20261017_armvision/ZYNQArm
old=/home/xilinx/so101_releases/release_planner_20261011_a8f65f66/so101_planner_runtime
backup=/home/xilinx/tcb705_deploy_backups/20261017_armvision
data=/home/xilinx/tcb705_data
"$runtime/.venv/bin/python" - "$runtime" <<'PY'
import json,pathlib,sys
root=pathlib.Path(sys.argv[1]);r=json.loads((root/'build/tcb705/board_verification/report.json').read_text())
assert r['passed'] and r['tests']>=90,r
PY
test ! -e /etc/systemd/system/so101-md0700r.service.d/zzzz-tcb705.conf
test ! -e /etc/systemd/system/tcb705-ui.service
mkdir -p "$backup" "$data"
chown xilinx:xilinx "$data"
systemctl cat so101-workbench so101-md0700r so101-gt911 so101-platform > "$backup/previous-services.txt"
cp -a /etc/systemd/system/so101-md0700r.service.d "$backup/md0700r-service.d"
if test -e /home/xilinx/ZYNQArm || test -L /home/xilinx/ZYNQArm; then
    test "$(readlink -f /home/xilinx/ZYNQArm)" = "$runtime"
else
    ln -s "$runtime" /home/xilinx/ZYNQArm
fi
cat > /etc/systemd/system/tcb705-ui.service <<EOF
[Unit]
Description=TCB705 ZYNQ drawing application and calibration UI
After=network.target

[Service]
Type=simple
User=xilinx
WorkingDirectory=$runtime
Environment=OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
ExecStart=$runtime/.venv/bin/python -B $runtime/scripts/run_tcb705.py --allow-real --no-browser --data-dir $data --secrets-file /home/xilinx/.config/so101/secrets.local.json
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now tcb705-ui.service
python3 - <<'PY'
import json,time,urllib.request
for i in range(90):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8785/api/status',timeout=2) as r:s=json.load(r)
        assert s['robot_type']=='TCB705' and s['simulation'] is False
        with urllib.request.urlopen('http://127.0.0.1:8095/',timeout=2) as r:assert r.status==200
        print('TCB705_BACKEND_AND_WEB_READY',flush=True);break
    except Exception:
        if i==89:raise
        time.sleep(1)
PY
cat > /etc/systemd/system/so101-md0700r.service.d/zzzz-tcb705.conf <<EOF
[Unit]
Requires=tcb705-ui.service
After=tcb705-ui.service

[Service]
ExecStart=
ExecStart=$runtime/.venv/bin/python -B $runtime/deploy/pynq-md0700r/md0700r_display.py --runtime $runtime --platform-manifest $old/overlay/planner_platform/platform.json --gui-user xilinx --data-dir $data --port 8765 --user-ui-port 8095
EOF
systemctl daemon-reload
systemctl stop so101-gt911.service
systemctl restart so101-md0700r.service
systemctl start so101-gt911.service
printf 'TCB705_SERVICES_INSTALLED\n'
