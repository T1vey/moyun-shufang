"""Stage, test and install the SDK queue fix; no enable, movement or PL loading."""
from pathlib import Path
import hashlib,json,paramiko,posixpath
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/tcb705/handwriting_queue_fix_20261027'
BASE='/home/xilinx/tcb705_releases/20261025_styles_r1/ZYNQArm'
DEST='/home/xilinx/styles_check/handwriting_queue_fix_20261027'
FILES=['tcb705/sdk_motion.py','tests/test_sdk_queue_barrier.py']
EXPECTED='9bb886aa52f7e0ffbd5b14d5f3d624ab978c17e001d7db7ef8b2845212515014'

def remote(c,code):
 i,o,e=c.exec_command('python3 -',timeout=90);i.write(code);i.channel.shutdown_write()
 out=o.read().decode();err=e.read().decode();status=o.channel.recv_exit_status()
 if status:raise RuntimeError(out+'\n'+err)
 return json.loads(out)

def main():
 c=paramiko.SSHClient();c.load_system_host_keys();c.connect('192.168.2.99',username='xilinx',timeout=8)
 try:
  manifest={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in FILES}
  print(remote(c,"from pathlib import Path\nimport json\np=Path(%r)\np.mkdir(parents=True,exist_ok=True)\nprint(json.dumps({'stage':str(p)}))"%DEST))
  s=c.open_sftp()
  for f in FILES:
   parent=DEST+'/stage/'+posixpath.dirname(f)
   remote(c,"from pathlib import Path\nimport json\nPath(%r).mkdir(parents=True,exist_ok=True)\nprint('{}')"%parent)
   s.put(str(ROOT/f),DEST+'/stage/'+f)
  s.close()
  code=r'''
import json,sys,os,hashlib,subprocess
from pathlib import Path
base=Path(BASE);dest=Path(DEST);manifest=MANIFEST
for f,h in manifest.items():assert hashlib.sha256((dest/'stage'/f).read_bytes()).hexdigest()==h,f
runner=r"""
import sys,importlib.util,unittest,json,time,os
from pathlib import Path
base=Path(sys.argv[1]);stage=Path(sys.argv[2])
os.chdir(str(base));sys.path.insert(0,str(base));sys.path.insert(0,str(base/'tests'));sys.path.insert(0,str(stage/'tests'))
import tcb705
spec=importlib.util.spec_from_file_location('tcb705.sdk_motion',str(stage/'tcb705/sdk_motion.py'))
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;setattr(tcb705,'sdk_motion',m);spec.loader.exec_module(m)
names=['test_sdk_queue_barrier','test_tcb705_sdk','test_handwriting_blend','test_handwriting_executor','test_handwriting_auth','test_calligraphy_speed','test_calligraphy_home']
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in names)
t=time.monotonic();r=unittest.TextTestRunner(verbosity=1).run(suite)
print(json.dumps({'tests':r.testsRun,'errors':len(r.errors),'failures':len(r.failures),'seconds':round(time.monotonic()-t,2),'success':r.wasSuccessful(),'source':m.__file__}))
sys.exit(not r.wasSuccessful())
"""
env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
r=subprocess.run([str(base/'.venv/bin/python'),'-B','-',str(base),str(dest/'stage')],input=runner,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,env=env,timeout=90)
(dest/'board_tests.stdout').write_text(r.stdout);(dest/'board_tests.stderr').write_text(r.stderr)
assert r.returncode==0,r.stdout+'\n'+r.stderr
print(r.stdout.strip().splitlines()[-1])
'''.replace('Path(BASE)','Path(%r)'%BASE).replace('Path(DEST)','Path(%r)'%DEST).replace('manifest=MANIFEST','manifest=%r'%manifest)
  result=remote(c,code);print(json.dumps(result,ensure_ascii=False));OUT.mkdir(parents=True,exist_ok=True)
  (OUT/'board_tests.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
  code=r'''
import json,hashlib,tarfile,os,urllib.request,shutil
from pathlib import Path
base=Path(BASE);dest=Path(DEST);manifest=MANIFEST
assert os.path.realpath('/home/xilinx/ZYNQArm')==str(base)
def api(path):return json.load(urllib.request.urlopen('http://127.0.0.1:8785'+path,timeout=5))
h=api('/api/handwriting/status');jobs=api('/api/jobs')
assert jobs.get('active') is None,'Active robot job'
assert h['phase']=='CLOSED' and h['stop_confirmed'],'Handwriting not closed/stopped'
p=base/'tcb705/sdk_motion.py'
assert hashlib.sha256(p.read_bytes()).hexdigest()==EXPECTED,'Board source changed'
cal=Path('/home/xilinx/tcb705_data/tcb705.machine.json');calhash=hashlib.sha256(cal.read_bytes()).hexdigest()
backup=dest/'before.tar.gz';assert not backup.exists(),'Backup already exists; inspect before rerunning'
with tarfile.open(str(backup),'w:gz') as tar:
 for f in manifest:
  if (base/f).exists():tar.add(str(base/f),arcname=f)
for f,hsh in manifest.items():
 src=dest/'stage'/f;target=base/f
 assert hashlib.sha256(src.read_bytes()).hexdigest()==hsh,f
 tmp=target.with_name(target.name+'.queue-fix-next');assert not tmp.exists()
 shutil.copy2(str(src),str(tmp));os.replace(str(tmp),str(target))
 assert hashlib.sha256(target.read_bytes()).hexdigest()==hsh,f
assert hashlib.sha256(cal.read_bytes()).hexdigest()==calhash,'Calibration changed during installation'
report={'installed':manifest,'previous_sdk_sha256':EXPECTED,'backup':str(backup),'calibration_sha256':calhash,'configuration_unchanged':True,'service_restart_pending':True,'robot_commands_sent':False,'fpga_loaded':False}
(dest/'installed.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
'''.replace('Path(BASE)','Path(%r)'%BASE).replace('Path(DEST)','Path(%r)'%DEST).replace('manifest=MANIFEST','manifest=%r'%manifest).replace('EXPECTED',repr(EXPECTED))
  report=remote(c,code);(OUT/'installed.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
 finally:c.close()
if __name__=='__main__':main()
