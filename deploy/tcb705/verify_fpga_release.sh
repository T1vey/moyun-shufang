set -eu
release=/home/xilinx/tcb705_releases/20261017_fpga_batch_r2/ZYNQArm
cd "$release"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1 XILINX_XRT=/usr
export TCB705_PL_MANIFEST="$release/overlay/tcb705/platform.json"
.venv/bin/python - <<'PY'
import json,time,urllib.request,subprocess
from pathlib import Path
from tcb705.accel_runtime import attached_identity,platform_health
from md0700r_runtime import resolve_display,display_ready,validate_health
root=Path.cwd();manifest=root/'overlay/tcb705/platform.json'
identity=resolve_display(root,manifest)
for attempt in range(90):
    try:
        display=json.loads(Path('/run/so101-lcd/status.json').read_text())
        touch=json.loads(Path('/run/so101-lcd/touch.json').read_text())
        if display_ready(display,identity) and touch['status']=='RUNNING':break
    except (OSError,ValueError,KeyError):pass
    time.sleep(1)
else:raise RuntimeError('New display/touch did not become ready')
with urllib.request.urlopen('http://127.0.0.1:8785/api/status',timeout=5) as r:state=json.load(r)
validate_health(state,identity)
assert state['robot_type']=='TCB705' and state['physical_authorized'] is False
with urllib.request.urlopen('http://127.0.0.1:8785/api/config',timeout=5) as r:machine=json.load(r)
saved=Path('/home/xilinx/tcb705_data/tcb705.machine.json')
reference=json.loads((saved if saved.exists() else root/'robots/tcb705/profile.armvision.json').read_text())
assert machine['robot_type']=='TCB705' and machine['armvision']['method']=='armvision-ab-z-uvw-v1'
assert machine['armvision']==reference['armvision'],'Deployment changed the Tianlian calibration'
with urllib.request.urlopen('http://127.0.0.1:8095/',timeout=5) as r:
    assert r.status==200
    html=r.read().decode('utf-8')
assert '糖画坊' in html
report=dict(platform=platform_health(),display=display,touch=touch,version=state['version'],calibration=machine['armvision'],
    motion_supported=state['motion_supported'],physical_motion=False,
    fpga_state=Path('/sys/class/fpga_manager/fpga0/state').read_text().strip(),
    services={u:subprocess.check_output(['systemctl','is-active',u],text=True).strip() for u in ['so101-platform','tcb705-ui','so101-md0700r','so101-gt911']})
out=root/'build/tcb705/deployment/board_acceptance.json';out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
PY
# Second loader invocation must attach via receipt without another download.
.venv/bin/python scripts/load_platform.py --manifest "$TCB705_PL_MANIFEST" --backend-port 8785
if test "${TCB_SKIP_BENCHMARK:-0}" != 1; then
    .venv/bin/python scripts/benchmark_tcb705_hardware.py --repeat 3 --output build/tcb705/benchmark_arm_pl.json
fi
systemctl is-enabled so101-platform tcb705-ui so101-md0700r so101-gt911
printf 'SEVEN_AXIS_BOARD_ACCEPTANCE_PASS\n'
