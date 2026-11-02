set -eu
cd /home/xilinx/ZYNQArm
export TCB_SKIP_BENCHMARK=1
bash deploy/tcb705/verify_fpga_release.sh
.venv/bin/python - <<'PY'
import json
from pathlib import Path
root=Path('build/tcb705/deployment')
before=json.loads((root/'ready_before_reboot.json').read_text())
after=json.loads(Path('/run/so101-platform/ready.json').read_text())
assert after['boot_id']!=before['boot_id'],'Linux did not reboot'
assert after['build_id']==before['build_id']=='tcb705_r4_fclk1_20261017_r2'
assert after['artifact_hashes']==before['artifact_hashes']
assert after['self_test']=='PASS'
report=dict(reboot_verified=True,kind='software_reboot',boot_id_before=before['boot_id'],boot_id_after=after['boot_id'],build_id=after['build_id'],self_test=after['self_test'])
(root/'reboot_acceptance.json').write_text(json.dumps(report,indent=2))
(root/'ready_after_reboot.json').write_text(json.dumps(after,indent=2))
print(json.dumps(report,indent=2))
PY
