"""Application-only r1 -> r2 repair; no enable, home, move or FPGA download.

The old r1 stop loop cannot exit after its SDK child has failed. A second
SIGTERM is permitted only for that old process, after external STOP, servo-off,
stable feedback, zero accepted strokes/jobs, and proof it owns no DMA mappings.
This maintenance recovery does not relax the application's motion locks.
"""
from pathlib import Path
import sys
import deploy_handwriting as d
d.BASE='/home/xilinx/tcb705_releases/20261023_handwriting_r1/ZYNQArm'
d.DEST='/home/xilinx/tcb705_releases/20261023_handwriting_r2/ZYNQArm'
d.OUT=Path(__file__).resolve().parents[1]/'build/handwriting_fix_20261023'
d.FILES+=['scripts/check_handwriting_webkit.py','scripts/check_handwriting_ui.cjs','scripts/deploy_handwriting_fix.py','tests/test_handwriting_auth.py']

def activate():
    code=r'''
import os,sys,pathlib,json,hashlib,time,signal,subprocess,urllib.request
base=BASE;dest=DEST
assert os.path.realpath('/home/xilinx/ZYNQArm')==base
sys.path.insert(0,dest)
from tcb705.config import load
from tcb705.web_control import Controller,settle_pose
cal='/home/xilinx/tcb705_data/tcb705.machine.json'
calhash=hashlib.sha256(open(cal,'rb').read()).hexdigest()
c=load(cal);ctrl=Controller(c['controller'],c['robot_id'],timeout=3)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def api(path):
    with opener.open('http://127.0.0.1:8785'+path,timeout=5) as r:return json.load(r)
assert api('/api/jobs')['active'] is None
s=api('/api/handwriting/status')
assert s['phase'] in ('FAULT','CLOSED'),s
if s['phase']=='FAULT':assert not s['strokes'],s
def stopped():
    ctrl.login();replies=ctrl.stop()
    assert replies and all(r[1] is True for r in replies),replies
    state=ctrl.state()
    assert state['g_servo_statero_']=='0' and state['_phc_alarm_']=='0',state
    pose=settle_pose(ctrl,n=3,interval=.15,timeout=4)
    return {'state':state,'pose':pose,'stop':replies}
before=stopped() if s['phase']=='FAULT' else {'session':'CLOSED'}
procs=[]
for p in pathlib.Path('/proc').iterdir():
    if not p.name.isdigit():continue
    try:cmd=(p/'cmdline').read_bytes().decode().split('\0')
    except (FileNotFoundError,PermissionError):continue
    if base+'/app.py' in cmd:procs.append(int(p.name))
assert len(procs)==1,procs
pid=procs[0]
def no_dma():
    assert not list(pathlib.Path('/run/lock/so101-planner').glob('*.inflight.json'))
    maps=pathlib.Path('/proc/%s/maps'%pid).read_text()
    assert not any('/dev/' in line or '/sys/' in line for line in maps.splitlines()),'Device mappings still owned'
    locks=pathlib.Path('/proc/locks').read_text().splitlines()
    assert not any((' %s '%pid) in line and 'FLOCK' in line for line in locks),'PL lease still owned'
no_dma()
drop='zzzzzzzzzzzzzzzzz-handwriting.conf'
app='[Service]\nWorkingDirectory='+dest+'\nExecStart=\nExecStart='+dest+'/.venv/bin/python -B '+dest+'/scripts/run_tcb705.py --allow-real --no-browser --data-dir /home/xilinx/tcb705_data --secrets-file /home/xilinx/.config/so101/secrets.local.json\n'
display='[Service]\nWorkingDirectory='+dest+'\nExecStart=\nExecStart='+dest+'/.venv/bin/python -B '+dest+'/deploy/pynq-md0700r/md0700r_display.py --runtime '+dest+' --platform-manifest /home/xilinx/tcb705_releases/20261020_lineart_r1/ZYNQArm/overlay/tcb705/platform.json --gui-user xilinx --data-dir /home/xilinx/tcb705_data --port 8785 --user-ui-port 8095\n'
backup={}
for unit,body in [('tcb705-ui',app),('so101-md0700r',display)]:
    p=pathlib.Path('/etc/systemd/system/'+unit+'.service.d')/drop
    backup[unit]=p.read_text();p.write_text(body)
pathlib.Path('/home/xilinx/handwriting-r1-service-backup.json').write_text(json.dumps(backup,indent=2))
temporary='/home/xilinx/ZYNQArm.handwriting-next'
assert not os.path.lexists(temporary)
os.symlink(dest,temporary);os.replace(temporary,'/home/xilinx/ZYNQArm')
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','stop','--no-block','tcb705-ui'],check=True)
time.sleep(7)
interrupted=False
if pathlib.Path('/proc/%s'%pid).exists():
    assert s['phase']=='FAULT','Normal shutdown is still draining; do not interrupt it'
    no_dma();stopped()
    # Interrupt only the obsolete handwriting worker join. No CMA memory is
    # mapped and both the controller's queue and physical motion are stopped.
    os.kill(pid,signal.SIGTERM);interrupted=True
deadline=time.monotonic()+20
while time.monotonic()<deadline:
    active=subprocess.run(['systemctl','is-active','tcb705-ui'],stdout=subprocess.PIPE,text=True).stdout.strip()
    if active in ('inactive','failed'):break
    time.sleep(.5)
else:raise RuntimeError('Old service did not stop')
subprocess.run(['systemctl','start','tcb705-ui'],check=True)
subprocess.run(['systemctl','start','so101-md0700r','so101-gt911'],check=True)
assert hashlib.sha256(open(cal,'rb').read()).hexdigest()==calhash
report=dict(release=dest,previous_release=base,calibration_sha256=calhash,
    old_stop_join_interrupted=interrupted,verified_controller=before,
    programmed_fpga=False,enabled_robot=False,sent_motion=False)
pathlib.Path('/home/xilinx/handwriting-r2-deployment.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
'''.replace('base=BASE;dest=DEST','base=%r;dest=%r'%(d.BASE,d.DEST))
    print(d.py(code,True,120))

if __name__=='__main__':
    {'stage':d.stage,'test':d.test,'activate':activate}[sys.argv[1]]()
