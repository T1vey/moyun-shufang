"""Stage the vision release on the board as the xilinx user (no root, no service change).

Copies the running release to RELEASE, overlays the vision files, installs the
sealed vision platform as overlay/tcb705/, then runs the offline checks on the
board.  Root activation is deploy/tcb705/vision/select_boot.py followed by a reboot.
"""
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = 'xilinx@192.168.2.99'
BASE = '/home/xilinx/tcb705_releases/20261024_ink_latency_r1/ZYNQArm'
RELEASE = '/home/xilinx/tcb705_releases/20261024_vision_r1/ZYNQArm'
FILES = ['app.py', 'platform_runtime.py', 'scripts/load_platform.py', 'scripts/package_tcb705_platform.py',
         'user_gui/display_server.py', 'user_gui/static/desktop.html', 'user_gui/static/desktop.js',
         'user_gui/static/vision.html', 'user_gui/static/vision.css', 'user_gui/static/vision.js',
         'tests/test_brush_vision.py', 'tools/build_vision_templates.py', 'tools/vision_vectors.py',
         'tools/stage_vision_release.py', 'deploy/tcb705/vision/select_boot.py', 'deploy/tcb705/vision/rollback.py',
         'data/vision/templates_v1.bin', 'data/vision/templates_v1.json',
         'hls_source/vision/tcb_brush_recog.cpp', 'hls_source/vision/tcb_brush_recog.h',
         'hls_source/vision/tb_brush_recog.cpp', 'hls_source/vision/brush_recog_2024.cfg',
         'hw/vision/create_vision.tcl', 'scripts/build_vision_hls.ps1', 'scripts/build_vision_vivado.ps1']
FILES += sorted(str(p.relative_to(ROOT)).replace('\\', '/') for p in (ROOT / 'brush_vision').glob('*.py'))
PLATFORM = ROOT / 'overlay/tcb705_vision'


def ssh(command, timeout=600):
    r = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', HOST, command],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    out = (r.stdout + r.stderr).strip()
    if r.returncode:
        raise SystemExit('remote command failed:\n' + command + '\n' + out[-3000:])
    return out


def bundle():
    buf = io.BytesIO()
    digests = {}
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for rel in FILES:
            tar.add(ROOT / rel, arcname=rel)
            digests[rel] = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        for p in sorted(PLATFORM.iterdir()):
            rel = 'overlay/tcb705/' + p.name
            tar.add(p, arcname=rel)
            digests[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        raw = json.dumps(digests, indent=1).encode()
        info = tarfile.TarInfo('VISION_SHA256.json'); info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))
    return buf.getvalue()


def main():
    blob = bundle()
    print('bundle', len(blob), 'bytes')
    # A previous incomplete stage may be replaced, never the release currently in service.
    print(ssh(f'if [ -e {RELEASE} ]; then test "$(readlink -f /home/xilinx/ZYNQArm)" != "{RELEASE}" && '
              f'test ! -e {RELEASE}/build/tcb705/vision_stage/STAGE_PASS && rm -rf {RELEASE}; fi && '
              f'mkdir -p {RELEASE} && cd {BASE} && '
              f'tar --exclude=./.venv --exclude=./build/tcb705/vision_stage -cf - . | tar -xf - -C {RELEASE} && '
              f'ln -s "$(readlink -f {BASE}/.venv)" {RELEASE}/.venv && rm -rf {RELEASE}/overlay/tcb705 && echo COPIED'))
    r = subprocess.run(['ssh', '-o', 'BatchMode=yes', HOST, f'tar -xzf - -C {RELEASE} && echo UNPACKED'],
                       input=blob, capture_output=True, timeout=300)
    print((r.stdout + r.stderr).decode(errors='replace').strip())
    if r.returncode:
        raise SystemExit('upload failed')
    check = f'''set -e
cd {RELEASE} && .venv/bin/python - <<'PY'
import hashlib,json,pathlib
for name,want in json.loads(pathlib.Path('VISION_SHA256.json').read_text()).items():
    assert hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest()==want,name
print('SOURCE_VERIFIED')
PY
export OPENBLAS_NUM_THREADS=1 TCB705_PL_MANIFEST={RELEASE}/overlay/tcb705/platform.json
.venv/bin/python -B scripts/load_platform.py --check --manifest overlay/tcb705/platform.json
.venv/bin/python -B -m unittest tests.test_brush_vision tests.test_tcb705_web tests.test_user_gui_workflow
mkdir -p build/tcb705/vision_stage && date > build/tcb705/vision_stage/STAGE_PASS && echo VISION_STAGE_PASS'''
    print(ssh(check, timeout=1800))


if __name__ == '__main__':
    main()
