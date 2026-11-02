"""Package the XSA, runtime platform, timing evidence and per-file hashes."""
import hashlib,json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
output=Path(sys.argv[1])
report=json.loads((ROOT/'hw/reports/lineart/acceptance.json').read_text())
if report['timing']['drc_errors'] or report['timing']['setup_slack_ns']<0:raise RuntimeError('unverified build')
files=[]
for source,target in [('hw/vivado_lineart/export','export'),('overlay/tcb705_lineart','platform'),('hw/reports/lineart','reports')]:
 for path in sorted((ROOT/source).iterdir()):
  if path.is_file() and path.suffix!='.log':files.append((path,target+'/'+path.name))
for name in ('线稿PL加速实施说明.md','线稿PL加速_构建验收报告.md'):files.append((ROOT/'docs'/name,'docs/'+name))
hashes={}
with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as z:
 for path,name in files:
  data=path.read_bytes();hashes[name]=hashlib.sha256(data).hexdigest();z.writestr(name,data)
 z.writestr('FILES_SHA256.json',json.dumps(hashes,indent=2))
print('HARDWARE_PACKAGE',output,len(files))
