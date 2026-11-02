# Synchronize documentation/deployment helpers after the validated source build.
# Application changes require a fresh build/test and are rejected by this script.
set -eu
python3 - <<'PY'
import hashlib,json,pathlib,zipfile
root=pathlib.Path('/home/xilinx/tcb705_releases/20261017_ethernet_preparation/ZYNQArm').resolve()
archive=pathlib.Path('/home/xilinx/TCB705_20261017_ethernet_final.zip')
with zipfile.ZipFile(archive) as z:
    manifest=json.loads(z.read('ZYNQArm/DELIVERY_SHA256.json'))
    changed=[]
    for name,expected in manifest.items():
        rel=pathlib.PurePosixPath(name)
        target=(root/name).resolve()
        if rel.is_absolute() or '..' in rel.parts or root not in target.parents:
            raise ValueError('Invalid archive path')
        raw=z.read('ZYNQArm/'+name)
        if hashlib.sha256(raw).hexdigest()!=expected:
            raise ValueError('Archive hash mismatch: '+name)
        current=hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
        if current!=expected:
            if name!='README.md' and rel.parts[0] not in ('docs','deploy','tools'):
                raise ValueError('Runtime application changed; rebuild/test required: '+name)
            changed.append((name,raw))
    for name,raw in changed:
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    (root/'DELIVERY_SHA256.json').write_text(json.dumps(manifest,indent=2))
    for name,expected in manifest.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('Deployed hash mismatch: '+name)
    print(json.dumps({'final_source_files':len(manifest),'documentation_and_deploy_files_synced':len(changed),
                      'runtime_application_unchanged':True,'all_source_hashes_match':True}))
PY
