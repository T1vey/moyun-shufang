#!/bin/sh
set -eu
python3 - <<'PY'
import hashlib,json,pathlib,shutil,subprocess,urllib.request,zipfile
root=pathlib.Path('/home/xilinx/tcb705_releases/20261020_lineart_r1/ZYNQArm')
backup=pathlib.Path('/home/xilinx/tcb705_deploy_backups/20261020_lineart_r1/metadata_cache_patch1')
with urllib.request.urlopen('http://127.0.0.1:8785/api/jobs',timeout=5) as r:
 if json.load(r).get('active'):raise RuntimeError('active job; patch refused')
old=json.loads((root/'DELIVERY_SHA256.json').read_text())
with zipfile.ZipFile('/home/xilinx/lineart_metadata_patch1.zip') as z:
 manifest=json.loads(z.read('PATCH_SHA256.json'))
 blobs={}
 for name,sha in manifest.items():
  if root not in (root/name).resolve().parents:raise ValueError('unsafe patch path')
  data=z.read(name)
  assert hashlib.sha256(data).hexdigest()==sha
  p=root/name
  if p.exists():
   current=hashlib.sha256(p.read_bytes()).hexdigest()
   assert current in (old.get(name),sha), 'existing file differs: '+name
  blobs[name]=data
backup.mkdir(parents=True,exist_ok=False)
existed={}
for name in blobs:
 p=root/name;existed[name]=p.exists()
 if p.exists():
  target=backup/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
(backup/'existed.json').write_text(json.dumps(existed))
subprocess.run(['systemctl','stop','tcb705-ui'],check=True)
try:
 for name,data in blobs.items():
  p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
  tmp=p.with_name(p.name+'.patch1.tmp');tmp.write_bytes(data);tmp.replace(p)
 # Focused tests: the base release's 244 tests have already passed on this board.
 env=dict(__import__('os').environ,TCB705_PL_MANIFEST=str(root/'not_loaded_platform.json'),
          OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
 for pattern in ('test_lineart_attachment.py','test_tcb705_web.py'):
  proc=subprocess.run([str(root/'.venv/bin/python'),'-m','unittest','discover','-s','tests','-p',pattern,'-v'],
      cwd=str(root),env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  (backup/(pattern+'.log')).write_text(proc.stdout)
  print(proc.stdout,flush=True)
  if proc.returncode:raise RuntimeError('patch regression failed: '+pattern)
 (root/'DELIVERY_PATCH_SHA256.json').write_text(json.dumps({'patch':'lineart_metadata_cache_patch1','files':manifest},indent=2))
except BaseException:
 for name,was_present in existed.items():
  if was_present:shutil.copy2(backup/name,root/name)
  elif (root/name).exists():(root/name).unlink()
 subprocess.run(['systemctl','start','tcb705-ui'],check=True)
 subprocess.run(['systemctl','start','so101-md0700r','so101-gt911'],check=True)
 raise
subprocess.run(['systemctl','start','tcb705-ui'],check=True)
subprocess.run(['systemctl','start','so101-md0700r','so101-gt911'],check=True)
print('LINEART_METADATA_PATCH_PASS',flush=True)
PY
