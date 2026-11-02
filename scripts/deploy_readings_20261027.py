"""Stage/install verified files over SSH; never sudo, restart, program PL or move an arm."""
import argparse,hashlib,json,shlex,tarfile
from pathlib import Path
import paramiko

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/tcb705/deployment/pending_20261027/deploy9_audio'
BASE='/home/xilinx/tcb705_releases/20261025_styles_r1/ZYNQArm'
STAGE='/home/xilinx/styles_check/audio_fp32_20261027'

def md5(raw):return hashlib.md5(raw).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--install',action='store_true');p.add_argument('--package-only',action='store_true');a=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    deploy8=ROOT/'build/tcb705/deployment/pending_20261027/deploy8'
    expected={name.strip():digest for digest,name in (line.split(None,1) for line in (deploy8/'expected_old_md5.txt').read_text().splitlines())}
    mapping={name:ROOT/name for name in expected}
    for name in ['platform_runtime.py','scripts/load_platform.py','user_gui/static/audio.js','user_gui/static/audio.css','tests/test_audio_player.py','tests/test_audio_api.py','tests/test_audio_service_init.py','tests/test_audio_es8388.py','tests/test_audio_resampling.py']:
        mapping[name]=ROOT/name
    for folder in ['audio_player','data/audio']:
        for src in (ROOT/folder).rglob('*'):
            if src.is_file() and '__pycache__' not in src.parts and src.suffix in ('.py','.json','.wav'):
                mapping[src.relative_to(ROOT).as_posix()]=src
    for src in (ROOT/'overlay/tcb705_audio_iobuf_20261027').iterdir():
        if src.is_file():mapping['overlay/tcb705/'+src.name]=src
    new={name:md5(src.read_bytes()) for name,src in sorted(mapping.items())}
    package=OUT/'readings_fp32_20261027.tar'
    with tarfile.open(package,'w') as t:
        for name,src in sorted(mapping.items()):t.add(src,arcname=name,recursive=False)
    (OUT/'new_md5.json').write_text(json.dumps(new,indent=2))
    (OUT/'new_md5.txt').write_text(''.join(h+'  '+n+'\n' for n,h in new.items()),encoding='ascii')
    if a.package_only:
        print('PACKAGE_READY',len(new),str(package));return
    c=paramiko.SSHClient();c.load_system_host_keys();c.connect('192.168.2.99',username='xilinx',timeout=8)
    s=c.open_sftp();old={}
    for name in mapping:
        try:raw=s.open(BASE+'/'+name,'rb').read();old[name]=md5(raw)
        except FileNotFoundError:old[name]=None
        if name in expected and old[name]!=expected[name]:raise RuntimeError('Baseline mismatch: '+name)
    for name in ('platform_runtime.py','scripts/load_platform.py'):
        before=ROOT/'build/tcb705/audio_20261027/pre_integration'/name
        if md5(before.read_bytes())!=old[name]:raise RuntimeError('Platform runtime baseline differs: '+name)
    prior=json.loads(s.open(BASE+'/overlay/tcb705/platform.json','rb').read())
    if prior['build_id']!='tcb705-parallel-fp32-20261024':raise RuntimeError('Unexpected active platform')
    (OUT/'expected_old_md5.json').write_text(json.dumps(old,indent=2))
    def run(command):
        _,out,err=c.exec_command(command);code=out.channel.recv_exit_status();stdout=out.read().decode();stderr=err.read().decode()
        if code:raise RuntimeError('Remote step failed: '+stderr[-1500:]+stdout[-1000:])
        print(stdout.strip(),flush=True)
    run('mkdir -p '+shlex.quote(STAGE))
    for src in (package,OUT/'new_md5.json',OUT/'expected_old_md5.json',ROOT/'scripts/install_readings_stage.py'):
        s.put(str(src),STAGE+'/'+src.name)
    run('python3 '+STAGE+'/install_readings_stage.py --stage '+STAGE+(' --install' if a.install else ''))
    s.close();c.close()

if __name__=='__main__':main()
