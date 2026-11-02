"""Versioned application-only deployment. Never programs PL or moves the arm.

Uses the existing local board credential only on sudo stdin; it is not logged.
Stage and offline verification are separate from activating the UI service.
"""
import argparse, ast, hashlib, json, shlex, subprocess, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/handwriting_20261023'
HOST='xilinx@192.168.2.99'
BASE='/home/xilinx/tcb705_releases/20261022_text3500_r1/ZYNQArm'
DEST='/home/xilinx/tcb705_releases/20261023_handwriting_r1/ZYNQArm'
FILES=['app.py','tcb705/workbench.py','tcb705/planner.py','tcb705/short_stroke.py',
 'calligraphy/presets.py','user_gui/display_server.py','user_gui/static/desktop.html',
 'user_gui/static/desktop.js','native/handwriting_match.cpp','scripts/build_handwriting.py',
 'tests/test_handwriting.py','tests/test_handwriting_executor.py','tests/test_short_stroke.py','user_gui/tests/test_display_server.py']
FILES += ['handwriting/'+p.name for p in (ROOT/'handwriting').glob('*.py')]
FILES += ['user_gui/static/handwriting.'+ext for ext in ('html','css','js')]
FILES += ['tcb705/model.py','tcb705/planning_batches.py','tcb705/planning_session.py',
          'tcb705/web_executor.py','tcb705/artifact.py','calligraphy/curves.py','calligraphy/execution.py',
          'scripts/bench_handwriting.py','handwriting/README.md']

def password():
    tree=ast.parse((ROOT/'tools/pynq_ssh.py').read_text(encoding='utf-8-sig'))
    for n in tree.body:
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PWD' for t in n.targets):
            return ast.literal_eval(n.value)
    raise RuntimeError('Existing deployment credential not found')

def remote(command,root=False,timeout=120):
    if root:command="sudo -S -p '' "+command
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5',HOST,command],
        input=password()+'\n' if root else None,text=True,encoding='utf-8',
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    return result.stdout+result.stderr

def py(code,root=False,timeout=120):
    return remote('python3 -c '+shlex.quote(code),root,timeout)

def stage():
    OUT.mkdir(parents=True,exist_ok=True)
    manifest={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in FILES}
    (OUT/'files.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    package=OUT/'handwriting-update.tar.gz'
    with tarfile.open(package,'w:gz') as t:
        for f in FILES:t.add(ROOT/f,arcname=f)
    subprocess.run(['scp','-q',str(package),HOST+':/home/xilinx/handwriting-update.tar.gz'],check=True)
    print(py("""import os,shutil,tarfile,hashlib,json
base=%r;dest=%r
assert base.startswith('/home/xilinx/tcb705_releases/') and dest.startswith('/home/xilinx/tcb705_releases/')
if not os.path.exists(dest):shutil.copytree(base,dest,symlinks=True)
with tarfile.open('/home/xilinx/handwriting-update.tar.gz') as t:
    for m in t.getmembers():
        assert m.isfile() and os.path.abspath(os.path.join(dest,m.name)).startswith(dest+'/')
    t.extractall(dest)
expected=%r
for f,h in expected.items():assert hashlib.sha256(open(dest+'/'+f,'rb').read()).hexdigest()==h,f
print(json.dumps({'release':dest,'files':len(expected),'verified':True}))
"""%(BASE,DEST,manifest),True))

def test():
    command='env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 '+DEST+'/.venv/bin/python -B '
    print(remote(command+DEST+'/scripts/build_handwriting.py',True))
    # unittest imports ROOT from cwd; shell command is literal and quoted.
    for args in ('-m unittest discover -s tests -p "test_handwriting*.py" -v',
                 '-m unittest discover -s tests -p test_short_stroke.py -v',
                 '-m unittest discover -s user_gui/tests -p test_display_server.py -v'):
        text=remote('sh -c '+shlex.quote('cd '+shlex.quote(DEST)+' && '+command+args),True,180)
        print(text)
    print('BOARD_OFFLINE_TESTS_PASS')

DROP='zzzzzzzzzzzzzzzzz-handwriting.conf'
def activate():
    # Preparation/real movement is never called by deployment.
    print(py("""import json,urllib.request,hashlib,os,pathlib,subprocess
base=%r;dest=%r;drop=%r
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open('http://127.0.0.1:8785/api/jobs',timeout=5) as r:jobs=json.load(r)
assert jobs['active'] is None,'An active robot job prevents deployment'
assert os.path.realpath('/home/xilinx/ZYNQArm')==base,'Unexpected active release'
cal='/home/xilinx/tcb705_data/tcb705.machine.json'
before=hashlib.sha256(open(cal,'rb').read()).hexdigest()
app='[Service]\\nWorkingDirectory='+dest+'\\nExecStart=\\nExecStart='+dest+'/.venv/bin/python -B '+dest+'/scripts/run_tcb705.py --allow-real --no-browser --data-dir /home/xilinx/tcb705_data --secrets-file /home/xilinx/.config/so101/secrets.local.json\\n'
display='[Service]\\nWorkingDirectory='+dest+'\\nExecStart=\\nExecStart='+dest+'/.venv/bin/python -B '+dest+'/deploy/pynq-md0700r/md0700r_display.py --runtime '+dest+' --platform-manifest /home/xilinx/tcb705_releases/20261020_lineart_r1/ZYNQArm/overlay/tcb705/platform.json --gui-user xilinx --data-dir /home/xilinx/tcb705_data --port 8785 --user-ui-port 8095\\n'
for unit,body in [('tcb705-ui',app),('so101-md0700r',display)]:
    p=pathlib.Path('/etc/systemd/system/'+unit+'.service.d')/drop
    assert not p.exists(),'New drop-in already exists'
    p.write_text(body)
temporary='/home/xilinx/ZYNQArm.handwriting-next'
assert not os.path.lexists(temporary)
os.symlink(dest,temporary);os.replace(temporary,'/home/xilinx/ZYNQArm')
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','restart','tcb705-ui'],check=True)
assert hashlib.sha256(open(cal,'rb').read()).hexdigest()==before
report=dict(release=dest,previous_release=base,calibration_sha256=before,
            programmed_fpga=False,sent_robot_commands=False)
pathlib.Path('/home/xilinx/handwriting-deployment.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
"""%(BASE,DEST,DROP),True,180))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['stage','test','activate']);a=p.parse_args()
    globals()[a.action]()
