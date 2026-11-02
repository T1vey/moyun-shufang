set -eu
uname -m
readlink -f /home/xilinx/ZYNQArm
systemctl show so101-platform tcb705-ui so101-md0700r so101-gt911 tcb705-ge-pl -p Id -p ActiveState -p ExecStart
python3 - <<'PY'
import json,pathlib,urllib.request
p=pathlib.Path('/run/so101-platform/ready.json')
if p.exists():
 d=json.loads(p.read_text());print('LOADED_BUILD',d.get('build_id'))
for port in (8785,8095):
 try:
  with urllib.request.urlopen('http://127.0.0.1:%d/api/jobs'%port,timeout=3) as r:d=json.load(r)
  print('JOB_STATE',port,'active',bool(d.get('active')),'jobs',len(d.get('jobs',[])))
 except Exception as e:print('JOB_STATE_UNAVAILABLE',port,type(e).__name__)
PY
ip -brief address
command -v g++
df -h /home/xilinx
