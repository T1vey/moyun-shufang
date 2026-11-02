#!/bin/sh
set -eu
root=/home/xilinx/tcb705_releases/20261020_lineart_r1/ZYNQArm
export XILINX_XRT=/usr TCB705_PL_MANIFEST="$root/overlay/tcb705/platform.json"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
cd "$root"
.venv/bin/python - <<'PY'
import copy,hashlib,json,pathlib,subprocess,urllib.request
root=pathlib.Path.cwd()
ready=json.loads(pathlib.Path('/run/so101-platform/ready.json').read_text())
assert ready['build_id']=='tcb705_lineart_20261020_r1'
units=('so101-platform','tcb705-ui','so101-md0700r','so101-gt911','tcb705-ge-pl')
result={'build_id':ready['build_id'],'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
result['services']={u:subprocess.check_output(['systemctl','is-active',u],text=True).strip() for u in units}
assert all(v=='active' for v in result['services'].values())
pid=subprocess.check_output(['systemctl','show','tcb705-ui','--property=MainPID','--value'],text=True).strip()
env=dict(x.split(b'=',1) for x in pathlib.Path('/proc/'+pid+'/environ').read_bytes().split(b'\0') if b'=' in x)
result['ui_acceleration_environment']={k:env[k.encode()].decode() for k in ('XILINX_XRT','TCB705_PL_MANIFEST','TCB705_LINEART','TCB705_NATIVE_LINEART')}
assert result['ui_acceleration_environment']['TCB705_PL_MANIFEST']==str(root/'overlay/tcb705/platform.json')
for name in ('status.json','touch.json'):
 data=json.loads((pathlib.Path('/run/so101-lcd')/name).read_text())
 assert data['status']=='RUNNING'
 result[name]=data
for port,route in ((8785,'/api/jobs'),(8095,'/')):
 with urllib.request.urlopen('http://127.0.0.1:%d%s'%(port,route),timeout=5) as r:
  result['http_'+str(port)]=r.status
  if port==8785:result['active_job']=bool(json.load(r).get('active'))
backup=pathlib.Path('/home/xilinx/tcb705_deploy_backups/20261020_lineart_r1')
profile_raw=pathlib.Path('/home/xilinx/tcb705_data/tcb705.machine.json').read_bytes()
actual=hashlib.sha256(profile_raw).hexdigest()
expected=(backup/'calibration.sha256').read_text().strip()
if actual!=expected:
 # The running configuration acquired execution.sdk after the immediate
 # post-boot hash check. Reconstruct the old bytes and require the saved hash:
 # this proves all calibration/settings outside that one added section match.
 baseline=copy.deepcopy(json.loads(profile_raw))
 assert 'sdk' in baseline['execution']
 baseline['execution'].pop('sdk')
 reconstructed=(json.dumps(baseline,ensure_ascii=False,indent=2)+'\n').encode()
 assert hashlib.sha256(reconstructed).hexdigest()==expected,'unexpected machine configuration change'
 result['configuration_change_after_boot']='execution.sdk section added; JSON final newline removed; all other fields exactly match saved pre-deploy SHA256'
else:result['configuration_change_after_boot']='none'
result['calibration_unchanged']=True
result['calibration_sha256']=actual
from tcb705.accel_runtime import platform_health
result['platform']=platform_health()
assert not result['platform']['faulted']
for iface in ('eth0','eth1','wlan0'):
 path=pathlib.Path('/sys/class/net')/iface
 result[iface]={'present':path.exists(),'operstate':(path/'operstate').read_text().strip() if path.exists() else None}
json_path=pathlib.Path('/home/xilinx/lineart_board_acceptance_20261020/final_health.json')
json_path.write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
PY
journalctl -b -k -p err --no-pager -n 20
