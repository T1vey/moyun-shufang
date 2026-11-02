"""Versioned FP32 deployment: stage/check, select next boot, verify. No motion."""
import hashlib,json,shlex,subprocess,sys,tarfile
from pathlib import Path
import deploy_handwriting as remote

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'build/tcb705/fp32_deployment_20261024'
BASE='/home/xilinx/tcb705_releases/20261024_vision_r1/ZYNQArm'
DEST='/home/xilinx/tcb705_releases/20261024_fp32_r1/ZYNQArm'
BACKUP='/home/xilinx/tcb705_deploy_backups/20261024_fp32_r1'
DROP='zzzzzzzzzzzzzzzzzzz-fp32.conf'
UNITS=('so101-platform','tcb705-ui','so101-md0700r','so101-gt911','tcb705-ge-pl')

def upload(path,name):
    subprocess.run(['scp','-q',str(path),remote.HOST+':/home/xilinx/'+name],check=True)

def stage():
    from platform_runtime import validate_manifest
    platform=ROOT/'overlay/tcb705_parallel_fp32_20261024'
    validate_manifest(platform/'platform.json')
    OUT.mkdir(parents=True,exist_ok=True)
    files={p.relative_to(ROOT).as_posix():p for p in ROOT.glob('*.py')}
    for directory in ('tcb705','calligraphy','handwriting','brush_vision','user_gui','web','ik_solver','scripts','deploy/pynq-md0700r','native','tests'):
        for p in (ROOT/directory).rglob('*'):
            if p.is_file() and p.suffix in ('.py','.cpp','.hpp','.h','.js','.css','.html') and not {'__pycache__','build'}.intersection(p.relative_to(ROOT).parts):
                files[p.relative_to(ROOT).as_posix()]=p
    for name in ('robots/tcb705/profile.armvision_joint.json',):files[name]=ROOT/name
    cfg=json.loads((platform/'platform.json').read_text())
    for name in ['platform.json']+list(cfg['files']):files['overlay/tcb705/'+name]=platform/name
    expected={name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in files.items()}
    manifest=OUT/'expected.json';manifest.write_text(json.dumps(expected,indent=2))
    upload(manifest,'fp32-expected.json')
    changed=json.loads(remote.py('''import json,hashlib,pathlib,os
base=pathlib.Path(%r)
assert os.path.realpath('/home/xilinx/ZYNQArm')==str(base)
expected=json.loads(pathlib.Path('/home/xilinx/fp32-expected.json').read_text())
print(json.dumps([n for n,h in expected.items() if not (base/n).is_file() or hashlib.sha256((base/n).read_bytes()).hexdigest()!=h]))
'''%BASE,True))
    package=OUT/'update.tar.gz'
    with tarfile.open(package,'w:gz') as archive:
        for name in changed:archive.add(files[name],arcname=name)
    upload(package,'fp32-update.tar.gz')
    result=remote.py('''import pathlib,os,shutil,tarfile,json,hashlib
base=pathlib.Path(%r);dest=pathlib.Path(%r)
assert os.path.realpath('/home/xilinx/ZYNQArm')==str(base)
assert not dest.exists(),'Choose a fresh release'
shutil.copytree(base,dest,symlinks=True)
with tarfile.open('/home/xilinx/fp32-update.tar.gz') as archive:
 for m in archive.getmembers():
  p=(dest/m.name).resolve()
  assert m.isfile() and str(p).startswith(str(dest)+'/'),m.name
 archive.extractall(dest)
expected=json.loads(pathlib.Path('/home/xilinx/fp32-expected.json').read_text())
for name,digest in expected.items():assert hashlib.sha256((dest/name).read_bytes()).hexdigest()==digest,name
cal=pathlib.Path('/home/xilinx/tcb705_data/tcb705.machine.json')
report={'base':str(base),'release':str(dest),'verified_files':len(expected),'calibration_sha256':hashlib.sha256(cal.read_bytes()).hexdigest(),'changed':%r,'fpga_loaded':False,'robot_motion':False}
(dest/'FP32_STAGE.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
'''%(BASE,DEST,changed),True,180)
    (OUT/'stage.json').write_text(result,encoding='utf-8')
    print(result)

def select():
    code='''import pathlib,json,os,re,subprocess,urllib.request,hashlib,shutil
base=%r;root=pathlib.Path(%r);backup=pathlib.Path(%r);drop=%r;units=%r
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
'''%(BASE,DEST,BACKUP,DROP,UNITS)
    result=remote.py(code,True,60);(OUT/'select.txt').write_text(result);print(result)

if __name__=='__main__':{'stage':stage,'select':select}[sys.argv[1]]()
