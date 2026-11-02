#!/bin/sh
# Board-only acceptance. A disconnected controller is expected in this phase.
set -eu
cd /home/xilinx/tcb705_releases/20261018_v2c_ge_pl_r1/ZYNQArm
export XILINX_XRT=/usr OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
export TCB705_PL_MANIFEST="$PWD/overlay/tcb705/platform.json"
.venv/bin/python - <<'PY'
import json,time,urllib.request,subprocess
from pathlib import Path
from platform_runtime import validate_manifest
from tcb705.accel_runtime import attached_identity,platform_health
from md0700r_runtime import resolve_display,display_ready,validate_health
root=Path.cwd();manifest=root/'overlay/tcb705/platform.json'
identity=resolve_display(root,manifest)
cfg,*_=validate_manifest(manifest)
attached_identity()
for attempt in range(60):
    try:
        display=json.loads(Path('/run/so101-lcd/status.json').read_text())
        touch=json.loads(Path('/run/so101-lcd/touch.json').read_text())
        if display_ready(display,identity) and touch['status']=='RUNNING':break
    except (OSError,ValueError,KeyError):pass
    time.sleep(1)
else:raise RuntimeError('Display/touch did not become ready')
with urllib.request.urlopen('http://127.0.0.1:8785/api/status',timeout=5) as r:state=json.load(r)
validate_health(state,identity)
assert state['robot_type']=='TCB705' and state['physical_authorized'] is False
with urllib.request.urlopen('http://127.0.0.1:8785/api/config',timeout=5) as r:machine=json.load(r)
reference=json.loads((root/'robots/tcb705/profile.armvision_web.json').read_text())
assert machine['armvision']==reference['armvision']
assert machine['sdk_mapping_verified'] is False
with urllib.request.urlopen('http://127.0.0.1:8095/',timeout=5) as r:
    assert r.status==200 and '糖画坊' in r.read().decode('utf-8')
network=json.loads(Path('/run/tcb705-ge-pl.json').read_text())
assert network['build_id']==cfg['build_id']
iface=network['interface']
report=dict(build_id=cfg['build_id'],platform=platform_health(),display=display,touch=touch,
    physical_motion=False,physical_authorized=state['physical_authorized'],ge_pl=network,
    controller_connected=False,controller_test='DEFERRED: user has not connected the arm',
    ge_pl_carrier=(Path('/sys/class/net')/iface/'carrier').read_text().strip(),
    network_addresses=json.loads(subprocess.check_output(['ip','-j','-4','address','show'])),
    fpga_state=Path('/sys/class/fpga_manager/fpga0/state').read_text().strip(),
    services={u:subprocess.check_output(['systemctl','is-active',u],text=True).strip()
              for u in ['so101-platform','tcb705-ge-pl','tcb705-ui','so101-md0700r','so101-gt911']})
assert all(s=='active' for s in report['services'].values())
out=root/'build/tcb705/deployment/v2c_board_acceptance.json';out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
PY
# This must reuse the boot receipt, without downloading the FPGA again.
.venv/bin/python scripts/load_platform.py --manifest "$TCB705_PL_MANIFEST" --backend-port 8785
printf 'V2C_BOARD_ACCEPTANCE_PASS\n'
