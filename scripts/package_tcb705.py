"""Package sources, sealed FPGA artifacts and reports without local machine state."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('output',type=Path)
    ap.add_argument('--platform',type=Path,help='Sealed platform folder to publish as overlay/tcb705')
    a=ap.parse_args()
    if a.output.exists():ap.error('output exists, choose a new filename')
    if a.platform:
        from platform_runtime import validate_manifest
        validate_manifest(a.platform/'platform.json')
    excluded={'.git','.venv','__pycache__','build','dist','tcb705_data','logs','tmp','.pytest_cache','_archive','.Xil','NA'}
    files=[]
    for p in ROOT.rglob('*'):
        rel=p.relative_to(ROOT)
        if len(rel.parts)>1 and rel.parts[0]=='hw' and rel.parts[1].startswith('vivado'):continue
        if 'reports' in rel.parts and rel.parts[:2]!=('hw','reports'):continue
        if not p.is_file() or excluded.intersection(rel.parts) or p.suffix in ('.pyc','.log','.zip'):continue
        if '.local.' in p.name or 'secrets' in p.name.lower() or p.name=='machine.json':continue
        if a.platform and rel.parts[:2]==('overlay','tcb705'):continue
        if a.platform and a.platform.resolve() in p.resolve().parents:continue
        if p.resolve()==a.output.resolve():continue
        files.append((p,rel.as_posix()))
    if a.platform:
        cfg=json.loads((a.platform/'platform.json').read_text())
        for name in ['platform.json']+sorted(cfg['files']):
            files.append((a.platform/name,'overlay/tcb705/'+name))
    files.sort(key=lambda item:item[1])
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(a.output,'x',zipfile.ZIP_DEFLATED) as z:
        hashes={}
        for p,name in files:
            raw=p.read_bytes();z.writestr('ZYNQArm/'+name,raw);hashes[name]=hashlib.sha256(raw).hexdigest()
        z.writestr('ZYNQArm/DELIVERY_SHA256.json',json.dumps(hashes,indent=2))
    print(json.dumps({'archive':str(a.output),'files':len(files),'bytes':a.output.stat().st_size}))
if __name__=='__main__':main()
