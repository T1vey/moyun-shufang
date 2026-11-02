#!/bin/sh
set -eu
root=/home/xilinx/tcb705_releases/20261020_lineart_r1/ZYNQArm
cat /proc/sys/kernel/random/boot_id
readlink -f /home/xilinx/ZYNQArm
systemctl show so101-platform tcb705-ui so101-md0700r so101-gt911 tcb705-ge-pl -p Id -p ActiveState -p SubState -p Result
journalctl -b -u so101-platform --no-pager -n 50
export TCB705_PL_MANIFEST="$root/overlay/tcb705/platform.json"
"$root/.venv/bin/python" "$root/scripts/load_platform.py" --check --manifest "$TCB705_PL_MANIFEST"
python3 - <<'PY'
import hashlib,json,pathlib,urllib.request
ready=json.loads(pathlib.Path('/run/so101-platform/ready.json').read_text())
print('READY_BUILD',ready.get('build_id'))
assert ready.get('build_id')=='tcb705_lineart_20261020_r1'
backup=pathlib.Path('/home/xilinx/tcb705_deploy_backups/20261020_lineart_r1')
expected=(backup/'calibration.sha256').read_text().strip()
actual=hashlib.sha256(pathlib.Path('/home/xilinx/tcb705_data/tcb705.machine.json').read_bytes()).hexdigest()
assert actual==expected,'calibration changed'
print('CALIBRATION_UNCHANGED',actual)
for port,path in ((8785,'/api/jobs'),(8095,'/')):
 with urllib.request.urlopen('http://127.0.0.1:%d%s'%(port,path),timeout=5) as r:
  print('HTTP',port,r.status)
  if port==8785:
   jobs=json.load(r)
   print('ACTIVE_JOB',bool(jobs.get('active')))
print('ETH1_PRESENT',pathlib.Path('/sys/bus/platform/devices/e000c000.ethernet/net/eth1').exists())
for name in ('status.json','touch.json'):
 p=pathlib.Path('/run/so101-lcd')/name
 print('DISPLAY_STATE',name,json.loads(p.read_text()) if p.exists() else 'not yet published')
PY
ip -brief address
journalctl -b -u so101-md0700r -u so101-gt911 -u tcb705-ge-pl --no-pager -n 35
