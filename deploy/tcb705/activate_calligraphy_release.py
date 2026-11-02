"""Activate the staged 2026-10-21 brush UI; retain calibration and running FPGA.

Run on the board after staging and offline tests. Requires root for systemd.
No controller API, robot command, FPGA download, or calibration write is used.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request

OLD = Path('/home/xilinx/tcb705_releases/20261020_lineart_r1/ZYNQArm')
NEW = Path('/home/xilinx/tcb705_releases/20261021_calligraphy_v4_r1/ZYNQArm')
MACHINE = Path('/home/xilinx/tcb705_data/tcb705.machine.json')
SUFFIX = 'zzzzzzzzzzzzzz-calligraphy-v4.conf'
UNITS = ('tcb705-ui', 'so101-md0700r')
DROPINS = [Path('/etc/systemd/system') / (u+'.service.d') / SUFFIX for u in UNITS]
LINK = Path('/home/xilinx/ZYNQArm')

def run(*args):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT).stdout

def get(port, route):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open('http://127.0.0.1:%d%s'%(port,route),timeout=15) as r:
        return json.load(r)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def wait_for(check, seconds=90):
    deadline=time.monotonic()+seconds
    error=None
    while time.monotonic()<deadline:
        try:
            value=check()
            if value:return value
        except Exception as exc:error=exc
        time.sleep(1)
    raise RuntimeError('service readiness timeout: '+str(error))

def main():
    if os.geteuid()!=0:raise SystemExit('Run this staged script with sudo python3.')
    assert Path(__file__).resolve()==NEW/'deploy/tcb705/activate_calligraphy_release.py'
    for p in DROPINS:assert not p.exists(), 'drop-in already exists: '+str(p)
    assert run('systemctl','is-active','so101-platform').strip()=='active'
    assert OLD.as_posix() in run('systemctl','show','tcb705-ui','-p','WorkingDirectory')
    assert LINK.is_symlink(), 'inspect the existing runtime path before replacing it'
    manifest=json.loads((NEW/'build/calligraphy/source_manifest.json').read_text())
    for name,want in manifest.items():assert sha(NEW/name)==want,name
    machine_hash=sha(MACHINE)
    assert machine_hash==sha(NEW.parent/'machine.before.json'),'machine changed since staging'
    jobs=get(8785,'/api/jobs')
    assert not jobs.get('active'), 'a backend task is active; finish it before activation'
    state=get(8095,'/api/state')
    assert (state.get('workflow') or {}).get('phase')=='idle','GUI is not idle'
    before=get(8785,'/api/status')
    assert before['ik_metrics'].get('faulted') is False
    backup=NEW.parent/('service_backup_'+time.strftime('%Y%m%d_%H%M%S'))
    backup.mkdir()
    for unit in UNITS:
        (backup/(unit+'.txt')).write_text(run('systemctl','cat',unit))
        folder=Path('/etc/systemd/system')/(unit+'.service.d')
        shutil.copytree(folder,backup/(unit+'.service.d'))
    shutil.copy2(MACHINE,backup/'tcb705.machine.json')
    previous_link=os.readlink(LINK)
    (backup/'runtime_link.before.txt').write_text(previous_link)
    platform=str(OLD/'overlay/tcb705/platform.json')
    common='[Service]\nWorkingDirectory=%s\nEnvironment="TCB705_PL_MANIFEST=%s"\nExecStart=\n'%(NEW,platform)
    ui=common+'ExecStart=%s/.venv/bin/python -B %s/scripts/run_tcb705.py --allow-real --no-browser --data-dir /home/xilinx/tcb705_data --secrets-file /home/xilinx/.config/so101/secrets.local.json\n'%(NEW,NEW)
    display=common+'ExecStart=%s/.venv/bin/python -B %s/deploy/pynq-md0700r/md0700r_display.py --runtime %s --platform-manifest %s --gui-user xilinx --data-dir /home/xilinx/tcb705_data --port 8785 --user-ui-port 8095\n'%(NEW,NEW,NEW,platform)
    created=[]
    changed_link=False
    print('Backup: '+str(backup),flush=True)
    try:
        # Normal service shutdown releases existing DMA through its owner.
        run('systemctl','stop','so101-md0700r','tcb705-ui')
        for p,body in zip(DROPINS,(ui,display)):
            p.write_text(body);created.append(p)
        run('systemctl','daemon-reload')
        for unit in UNITS:
            assert str(NEW) in run('systemctl','show',unit,'-p','WorkingDirectory')
        run('systemctl','start','tcb705-ui')
        current=wait_for(lambda:get(8785,'/api/status'))
        assert current['ik_metrics']['build_id']==before['ik_metrics']['build_id']
        assert current['ik_metrics']['artifact_hashes']==before['ik_metrics']['artifact_hashes']
        assert current['ik_metrics'].get('faulted') is False
        catalog=wait_for(lambda:get(8785,'/api/calligraphy'))
        assert catalog['version']=='brush-modules-20261021-v4'
        assert len(catalog['items'])==88
        assert catalog['simulation'] is False
        assert catalog['profile']['verified'] is False
        assert catalog['profile']['max_press_mm']==0
        wait_for(lambda:get(8095,'/api/state'))
        run('systemctl','start','so101-md0700r')
        def lcd_ready():
            p=Path('/run/so101-lcd/status.json')
            return json.loads(p.read_text()) if p.is_file() else None
        lcd=wait_for(lcd_ready)
        assert lcd.get('hardware_frames_verified') is True
        assert lcd.get('build_id')==before['ik_metrics']['build_id']
        assert sha(MACHINE)==machine_hash, 'calibration changed during activation'
        temp=LINK.with_name('ZYNQArm.calligraphy.new')
        assert not temp.exists() and not temp.is_symlink()
        temp.symlink_to(NEW,target_is_directory=True);temp.replace(LINK);changed_link=True
        receipt=dict(release=str(NEW),previous_release=str(OLD),backup=str(backup),
            source_manifest_sha256=sha(NEW/'build/calligraphy/source_manifest.json'),
            module_version=catalog['version'],basic=sum(i['group']=='basic' for i in catalog['items']),
            radicals=sum(i['group']=='radical' for i in catalog['items']),
            brush=catalog['profile'],machine_sha256_before=machine_hash,machine_sha256_after=sha(MACHINE),
            contact_z_mm=json.loads(MACHINE.read_text())['armvision']['z_table_mm'],
            fpga=current['ik_metrics'],display=lcd,robot_motion_issued=False)
        (NEW.parent/'activation_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
        print(json.dumps(receipt,ensure_ascii=False,indent=2),flush=True)
    except BaseException:
        print('Activation failed; restoring previous services.',flush=True)
        run('systemctl','stop','so101-md0700r','tcb705-ui')
        for p in created:p.unlink()
        if changed_link:
            temp=LINK.with_name('ZYNQArm.calligraphy.rollback')
            temp.symlink_to(previous_link,target_is_directory=True);temp.replace(LINK)
        run('systemctl','daemon-reload')
        run('systemctl','start','tcb705-ui')
        wait_for(lambda:get(8785,'/api/status'))
        run('systemctl','start','so101-md0700r')
        raise

if __name__=='__main__':main()
