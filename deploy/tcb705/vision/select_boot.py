"""Select the staged vision platform for the next reboot; never reconfigures the live PL.

Run as root from the staged release:  sudo .venv/bin/python deploy/tcb705/vision/select_boot.py
"""
import hashlib,json,os,re,shutil,subprocess,urllib.request
from pathlib import Path

ROOT=Path('/home/xilinx/tcb705_releases/20261024_vision_r1/ZYNQArm')
BACKUP=Path('/home/xilinx/tcb705_deploy_backups/20261024_vision_r1')
DROPIN='zzzzzzzzzzzzzzzzzz-vision.conf'
UNITS=('so101-platform','tcb705-ui','so101-md0700r','so101-gt911','tcb705-ge-pl')
MANIFEST=ROOT/'overlay/tcb705/platform.json'

def main():
 if os.geteuid()!=0:raise PermissionError('root required')
 if Path(__file__).resolve().parents[3]!=ROOT:raise RuntimeError('run the staged script')
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 with opener.open('http://127.0.0.1:8785/api/jobs',timeout=5) as response:jobs=json.load(response)
 if jobs.get('active'):raise RuntimeError('Active job; maintenance refused')
 if not (ROOT/'build/tcb705/vision_stage/STAGE_PASS').is_file():raise RuntimeError('staging checks have not passed')
 subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/load_platform.py'),'--check','--manifest',str(MANIFEST)],check=True)
 commands={}
 for unit in UNITS:
  directory=Path('/etc/systemd/system')/(unit+'.service.d')
  if directory.exists() and any(p.name>=DROPIN for p in directory.glob('*.conf')):raise RuntimeError('later/existing drop-in: '+unit)
  text=subprocess.check_output(['systemctl','show',unit,'--property=ExecStart','--value'],text=True)
  match=re.search(r'argv\[\]=(.*?)\s*; ignore_errors=',text)
  if not match:raise RuntimeError('unexpected ExecStart: '+unit)
  command,count=re.subn(r'/home/xilinx/tcb705_releases/[^/\s]+/ZYNQArm',str(ROOT),match[1])
  if not count or '\n' in command:raise RuntimeError('unexpected release command: '+unit)
  commands[unit]=command
 BACKUP.mkdir(parents=True,exist_ok=False)
 (BACKUP/'previous_release.txt').write_text(str(Path('/home/xilinx/ZYNQArm').resolve())+'\n')
 calibration=Path('/home/xilinx/tcb705_data/tcb705.machine.json')
 if calibration.exists():(BACKUP/'calibration.sha256').write_text(hashlib.sha256(calibration.read_bytes()).hexdigest())
 if Path('/run/so101-platform/ready.json').exists():shutil.copy2('/run/so101-platform/ready.json',BACKUP/'previous_ready.json')
 for unit in UNITS:
  (BACKUP/(unit+'.effective.txt')).write_bytes(subprocess.check_output(['systemctl','cat',unit]))
  directory=Path('/etc/systemd/system')/(unit+'.service.d');directory.mkdir(exist_ok=True)
  (directory/DROPIN).write_text('[Service]\nWorkingDirectory='+str(ROOT)+'\n'
    +'Environment="TCB705_PL_MANIFEST='+str(MANIFEST)+'" "TCB705_LINEART=auto" "TCB705_NATIVE_LINEART=auto"\n'
    +'ExecStart=\nExecStart='+commands[unit]+'\n'
    +('TimeoutStartSec=180\n' if unit=='so101-platform' else ''))
 link=Path('/home/xilinx/ZYNQArm');temporary=link.with_name('ZYNQArm.vision.tmp')
 if temporary.is_symlink():temporary.unlink()
 temporary.symlink_to(ROOT);temporary.replace(link)
 subprocess.run(['systemctl','daemon-reload'],check=True)
 print('VISION_SELECTED_FOR_NEXT_BOOT; reboot to load the new FPGA (running hardware unchanged)',flush=True)

if __name__=='__main__':main()
