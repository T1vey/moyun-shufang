"""FP32 release: select for next boot (same logic as scripts/deploy_fp32_20261024.py select). No FPGA reload, no motion."""
import os,pathlib,shutil,subprocess
if os.geteuid()!=0:raise PermissionError('run with sudo')
_root=pathlib.Path('/home/xilinx/tcb705_releases/20261024_fp32_r1/ZYNQArm')
shutil.copy2('/home/xilinx/fp32_check/FP32_CHECK_PASS.json',_root/'FP32_CHECK_PASS.json')
subprocess.run(['chmod','-R','go-w',str(_root)],check=True)
import pathlib,json,os,re,subprocess,urllib.request,hashlib,shutil
base='/home/xilinx/tcb705_releases/20261024_vision_r1/ZYNQArm';root=pathlib.Path('/home/xilinx/tcb705_releases/20261024_fp32_r1/ZYNQArm');backup=pathlib.Path('/home/xilinx/tcb705_deploy_backups/20261024_fp32_r1');drop='zzzzzzzzzzzzzzzzzzz-fp32.conf';units=('so101-platform', 'tcb705-ui', 'so101-md0700r', 'so101-gt911', 'tcb705-ge-pl')
op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def api(path):
 with op.open('http://127.0.0.1:8785'+path,timeout=5) as response:return json.load(response)
assert api('/api/jobs')['active'] is None,'Active task'
assert api('/api/handwriting/status')['phase']=='CLOSED','Handwriting session active'
assert os.path.realpath('/home/xilinx/ZYNQArm')==base,'Unexpected release'
assert (root/'FP32_CHECK_PASS.json').exists(),'Staged checks not completed'
manifest=root/'overlay/tcb705/platform.json'
subprocess.run([str(root/'.venv/bin/python'),str(root/'scripts/load_platform.py'),'--check','--manifest',str(manifest)],check=True)
commands={}
for unit in units:
 directory=pathlib.Path('/etc/systemd/system')/(unit+'.service.d')
 assert not any(p.name>=drop for p in directory.glob('*.conf')),'Later drop-in exists'
 text=subprocess.check_output(['systemctl','show',unit,'-p','ExecStart','--value'],text=True)
 match=re.search(r'argv\[\]=(.*?)\s*; ignore_errors=',text)
 assert match,unit
 command,count=re.subn(r'/home/xilinx/tcb705_releases/[^/\s]+/ZYNQArm',str(root),match[1])
 assert count and '\n' not in command
 commands[unit]=command
backup.mkdir(parents=True,exist_ok=False)
(backup/'previous_release.txt').write_text(base+'\n')
cal=pathlib.Path('/home/xilinx/tcb705_data/tcb705.machine.json')
(backup/'calibration.sha256').write_text(hashlib.sha256(cal.read_bytes()).hexdigest())
shutil.copy2('/run/so101-platform/ready.json',backup/'previous_ready.json')
for unit in units:
 (backup/(unit+'.effective.txt')).write_bytes(subprocess.check_output(['systemctl','cat',unit]))
 directory=pathlib.Path('/etc/systemd/system')/(unit+'.service.d');directory.mkdir(exist_ok=True)
 (directory/drop).write_text('[Service]\nWorkingDirectory='+str(root)+'\nEnvironment="TCB705_PL_MANIFEST='+str(manifest)+'" "TCB705_LINEART=auto" "TCB705_NATIVE_LINEART=auto"\nExecStart=\nExecStart='+commands[unit]+'\n'+('TimeoutStartSec=180\n' if unit=='so101-platform' else ''))
link=pathlib.Path('/home/xilinx/ZYNQArm');temp=link.with_name('ZYNQArm.fp32-next');assert not temp.exists() and not temp.is_symlink()
temp.symlink_to(root);temp.replace(link)
subprocess.run(['systemctl','daemon-reload'],check=True)
assert hashlib.sha256(cal.read_bytes()).hexdigest()==(backup/'calibration.sha256').read_text()
print('FP32_SELECTED_FOR_NEXT_BOOT; no FPGA hot reload and no robot command')
