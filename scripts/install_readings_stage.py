"""Board-side installer; no sudo, restart, hardware access, calibration or secret changes."""
import argparse,hashlib,json,os,subprocess,tarfile,urllib.request
from pathlib import Path
BASE=Path('/home/xilinx/tcb705_releases/20261025_styles_r1/ZYNQArm')
def md5(raw):return hashlib.md5(raw).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);p.add_argument('--install',action='store_true');a=p.parse_args()
    old=json.loads((a.stage/'expected_old_md5.json').read_text());new=json.loads((a.stage/'new_md5.json').read_text())
    package=a.stage/'readings_fp32_20261027.tar'
    for name,digest in old.items():
        dest=BASE/name
        if name.startswith('/') or '..' in Path(name).parts:raise RuntimeError('Unsafe package path')
        actual=md5(dest.read_bytes()) if dest.exists() else None
        if actual!=digest:raise RuntimeError('Old file changed: '+name)
    with tarfile.open(str(package)) as t:
        if len(t.getmembers())!=len(new):raise RuntimeError('Archive file count differs')
        for m in t.getmembers():
            if not m.isfile() or m.name not in new or md5(t.extractfile(m).read())!=new[m.name]:raise RuntimeError('Staged archive mismatch: '+m.name)
    print('STAGE_HASHES_PASS',len(new),flush=True)
    if not a.install:return
    state=json.load(urllib.request.urlopen('http://127.0.0.1:8095/api/state',timeout=5))
    workflow=state.get('workflow') or {}
    if workflow.get('phase') not in ('idle','completed','cancelled','failed'):raise RuntimeError('Screen workflow is not idle')
    for name in old:
        dest=BASE/name
        parent=dest.parent
        while not parent.exists():parent=parent.parent
        if not os.access(str(parent),os.W_OK) or (dest.exists() and not os.access(str(dest),os.W_OK)):
            raise RuntimeError('Installation requires owner permission: '+name)
    backup=a.stage/'before_readings_fp32.tar'
    if backup.exists():raise RuntimeError('Backup already exists; refusing to overwrite')
    names=[name for name,d in old.items() if d is not None and not name.startswith('overlay/tcb705/')]+['overlay/tcb705']
    subprocess.run(['tar','-cf',str(backup),'-C',str(BASE),'--']+names,check=True)
    print('BACKUP_READY',str(backup),flush=True)
    subprocess.run(['tar','-xmf',str(package),'-C',str(BASE)],check=True)
    for name,digest in new.items():
        if md5((BASE/name).read_bytes())!=digest:raise RuntimeError('Installed file mismatch: '+name)
    print('INSTALLED_HASHES_PASS',len(new),flush=True)
    platform=json.loads((BASE/'overlay/tcb705/platform.json').read_text())['build_id']
    result=dict(files=len(new),backup=str(backup),platform=platform,reboot_required=True)
    (a.stage/'installed.json').write_text(json.dumps(result,indent=2))
    print('FILES_INSTALLED_NO_RESTART_NO_PL_DOWNLOAD_NO_ROBOT_MOTION',flush=True)
if __name__=='__main__':main()
