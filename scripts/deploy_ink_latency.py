"""Versioned display/input-only update. No robot commands or FPGA download."""
import json,sys,shlex
from pathlib import Path
import deploy_handwriting as d
d.BASE='/home/xilinx/tcb705_releases/20261023_handwriting_r2/ZYNQArm'
d.DEST='/home/xilinx/tcb705_releases/20261024_ink_latency_r1/ZYNQArm'
d.OUT=Path(__file__).resolve().parents[1]/'build/handwriting_latency_20261024'
d.FILES=['user_gui/static/handwriting.js','user_gui/static/handwriting.html',
 'scripts/user_gui_kiosk.py','deploy/pynq-md0700r/md0700r_display.py',
 'tests/test_md0700r_runtime.py','tests/test_kiosk_view_poll.py',
 'scripts/check_handwriting_webkit.py','scripts/deploy_ink_latency.py']

def activate():
    code='''import json,urllib.request,pathlib,subprocess,os,hashlib
base=%r;dest=%r
op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def api(path):
 with op.open('http://127.0.0.1:8785'+path,timeout=5) as r:return json.load(r)
assert api('/api/jobs')['active'] is None,'Active task'
assert api('/api/handwriting/status')['phase']=='CLOSED','Close handwriting before display restart'
assert os.path.realpath('/home/xilinx/ZYNQArm')==base,'Unexpected release'
cal=pathlib.Path('/home/xilinx/tcb705_data/tcb705.machine.json');before=hashlib.sha256(cal.read_bytes()).hexdigest()
backup={}
for unit in ['tcb705-ui','so101-md0700r']:
 p=pathlib.Path('/etc/systemd/system/'+unit+'.service.d/zzzzzzzzzzzzzzzzz-handwriting.conf')
 body=p.read_text();assert base in body
 backup[unit]=body;p.write_text(body.replace(base,dest))
pathlib.Path('/home/xilinx/ink-latency-service-backup.json').write_text(json.dumps(backup,indent=2))
temp='/home/xilinx/ZYNQArm.ink-next';assert not os.path.lexists(temp)
os.symlink(dest,temp);os.replace(temp,'/home/xilinx/ZYNQArm')
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','restart','tcb705-ui'],check=True)
subprocess.run(['systemctl','start','so101-md0700r','so101-gt911'],check=True)
assert hashlib.sha256(cal.read_bytes()).hexdigest()==before
report=dict(release=dest,previous_release=base,calibration_sha256=before,fpga_downloaded=False,robot_commands=False)
pathlib.Path('/home/xilinx/ink-latency-deployment.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
'''%(d.BASE,d.DEST)
    print(d.py(code,True,120))

def test():
    for name in ('test_md0700r_runtime.py','test_kiosk_view_poll.py'):
        command='cd '+shlex.quote(d.DEST)+' && env OPENBLAS_NUM_THREADS=1 .venv/bin/python -B -m unittest discover -s tests -p '+shlex.quote(name)+' -v'
        print(d.remote('sh -c '+shlex.quote(command),True,60))
    command='env WEBKIT_DISABLE_COMPOSITING_MODE=1 GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3 '+d.DEST+'/scripts/check_handwriting_webkit.py'
    result=d.remote(command,False,60);print(result)
    (d.OUT/'webkit-result.txt').write_text(result,encoding='utf-8')

if __name__=='__main__':{'stage':d.stage,'test':test,'activate':activate}[sys.argv[1]]()
