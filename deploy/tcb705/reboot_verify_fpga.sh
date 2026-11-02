# Reboot only the accepted idle board; no robot commands.
set -eu
cd /home/xilinx/ZYNQArm
test -f build/tcb705/benchmark_arm_pl.json
.venv/bin/python - <<'PY'
import json,urllib.request
from pathlib import Path
with urllib.request.urlopen('http://127.0.0.1:8785/api/jobs',timeout=5) as response:jobs=json.load(response)
if jobs.get('active'):raise RuntimeError('An application job is active; do not reboot')
root=Path('build/tcb705/deployment')
for source,name in [(Path('/run/so101-platform/ready.json'),'ready_before_reboot.json'),(root/'board_acceptance.json','acceptance_before_reboot.json')]:
    (root/name).write_bytes(source.read_bytes())
print('ACCEPTED_IDLE_BOARD_REBOOT_SCHEDULED',flush=True)
PY
systemd-run --unit=tcb705-verify-reboot --on-active=3 /bin/systemctl reboot
