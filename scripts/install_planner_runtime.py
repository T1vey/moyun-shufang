"""Install a sealed planner release in place; preserve calibration and roll back.

The release must already be extracted into a NEW permanent directory. This
installer never opens serial devices or requests motion. It keeps the currently
authorized --allow-motion setting, unless --disable-motion is explicitly given.
Run --prepare-only first to build the ARM library without stopping services.
Hardware rollback is prohibited if any DMA owner failed to drain or a persistent
planner in-flight marker exists; in that case services remain stopped for reboot.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
UNITS = ('so101-platform.service', 'so101-workbench.service',
         'so101-md0700r.service', 'so101-gt911.service')
STOP_ORDER = tuple(reversed(UNITS))
CONTROL_KEYS = ('XILINX_XRT', 'PYTHONPATH', 'LD_LIBRARY_PATH')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024*1024), b''):
            h.update(part)
    return h.hexdigest()


def atomic_write(path, contents, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(contents.encode('utf-8') if isinstance(contents, str) else contents)
            stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists(): temporary.unlink()


def read_service_environment(path):
    result = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        key, sep, value = line.partition('=')
        if key not in CONTROL_KEYS: continue
        if not sep: raise ValueError('Invalid PYNQ service environment')
        if value.startswith('"'):
            value = json.loads(value)
        elif value.startswith("'"):
            parsed = shlex.split(value)
            if len(parsed) != 1: raise ValueError('Invalid PYNQ service environment')
            value = parsed[0]
        if any(c in value for c in '\n\r\0'): raise ValueError('Invalid PYNQ environment value')
        result[key] = value
    if not result.get('XILINX_XRT'):
        raise ValueError('Previous release must contain its working XILINX_XRT service environment')
    return result


def migrated_profile(previous, root):
    """Change only the accelerator selection, preserving cloud/network options."""
    body = dict(previous)
    if body.get('schema') != 'so101-runtime-v1':
        raise ValueError('Unsupported existing runtime profile')
    body.update(pl_mode='planner', overlay=str(root/'overlay/planner_platform/drawing_planner.bit'),
                ip_name='planner_accel_v2_0', pl_load_policy='attach',
                platform_manifest=str(root/'overlay/planner_platform/platform.json'))
    return body


def data_manifest(directory):
    """Record data content without rewriting, copying, or pruning user jobs."""
    directory = Path(directory)
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            result[path.relative_to(directory).as_posix()] = 'SYMLINK:' + os.readlink(str(path))
        elif path.is_file():
            result[path.relative_to(directory).as_posix()] = sha(path)
    return result


def request_json(port, endpoint):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        connection.request('GET', endpoint)
        response = connection.getresponse()
        if response.status != 200: raise RuntimeError('HTTP readiness: ' + str(response.status))
        return json.loads(response.read())
    finally: connection.close()


class Installer:
    def __init__(self, args):
        self.args = args
        self.root = ROOT.resolve()
        self.old = args.previous_runtime.resolve()
        self.data = args.data_dir.resolve()
        self.profile = args.profile.resolve()
        self.backup = args.backup.resolve()
        self.py = self.root/'.venv/bin/python'
        self.env = dict(os.environ)
        self.env.update(read_service_environment(self.old/'.pynq-service.env'))
        self.env.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
                        PYTHONDONTWRITEBYTECODE='1')
        self.states = {}
        self.saved = {}
        self.changed = False
        self.hardware_attempted = False
        self.previous = json.loads(self.profile.read_text(encoding='utf-8'))
        self.port = int(self.previous.get('port', 8765))

    def run(self, argv, capture=False, check=True):
        result = subprocess.run([str(v) for v in argv], cwd=str(self.root), env=self.env,
                                check=check, universal_newlines=True,
                                stdout=subprocess.PIPE if capture else None,
                                stderr=subprocess.PIPE if capture else None)
        return result.stdout.strip() if capture else result

    def property(self, unit, prop):
        return self.run(['systemctl', 'show', unit, '--property='+prop, '--value'], capture=True)

    def active(self, unit):
        return self.property(unit, 'ActiveState') == 'active'

    def prepare(self):
        from scripts.verify_package import verify
        from platform_runtime import validate_manifest, PLANNER_ABI, accelerator_identity
        if (self.root == self.old or self.root == self.data or self.root in self.data.parents
                or self.data in self.root.parents or self.root in self.old.parents or self.old in self.root.parents):
            raise ValueError('New release, old release and shared data must be separate directories')
        if not self.data.is_dir(): raise ValueError('Existing shared data directory is required')
        if any(self.backup == p or p in self.backup.parents for p in (self.data, self.root, self.old)):
            raise ValueError('Backup must be outside runtime and shared data directories')
        if platform.machine() not in ('armv7l', 'armv8l'):
            raise RuntimeError('Installation requires the Zynq ARM Linux board')
        verify(self.root)
        cfg, *_ = validate_manifest(self.root/'overlay/planner_platform/platform.json', platform.release())
        if accelerator_identity(cfg)[0] != PLANNER_ABI or cfg.get('display_backend') != 'pynq-mmio':
            raise ValueError('This installer requires planner-v2 with PYNQ MMIO display')
        if cfg.get('bitfile') != 'drawing_planner.bit':
            raise ValueError('This runtime profile requires drawing_planner.bit')
        previous_bit = Path(self.previous['overlay'])
        if not previous_bit.is_absolute(): previous_bit = self.old/previous_bit
        self.previous_bit = previous_bit.resolve()
        from ik_target_contract import validate_overlay_files
        if self.previous.get('pl_mode') != 'target':
            raise ValueError('This migration installer requires the existing verified target runtime')
        validate_overlay_files(self.previous_bit, self.previous.get('ip_name', 'z20_ik_target_0'))
        if not self.py.exists():
            old_py = self.old/'.venv/bin/python'
            self.run([old_py, '-m', 'venv', '--system-site-packages', self.root/'.venv'])
            paths = json.loads(self.run([old_py, '-c',
                'import json,sys; print(json.dumps([p for p in sys.path if p.endswith(("site-packages","dist-packages"))]))'], capture=True))
            destination = self.run([self.py, '-c', 'import site; print(site.getsitepackages()[0])'], capture=True)
            atomic_write(Path(destination)/'so101-pynq-runtime.pth', ''.join(p+'\n' for p in paths), 0o644)
        self.run([self.py, '-m', 'pip', '--disable-pip-version-check', 'install', '--no-index', '--no-deps',
                  '--find-links', self.root/'dependencies/pynq_wheels', '-r', self.root/'requirements-pynq.txt'])
        self.run([self.py, '-B', self.root/'scripts/doctor.py', '--require-pynq'])
        self.run([self.py, '-B', self.root/'native/build.py', '--cxx', 'g++'])
        self.run([self.py, '-B', '-c',
                  'from native.geometry import get_kernel; assert get_kernel() is not None, "ARM native load failed"'])
        atomic_write(self.root/'.pynq-service.env', ''.join(k+'='+json.dumps(self.env[k])+'\n'
                                                         for k in CONTROL_KEYS if self.env.get(k)))
        print('PLANNER_PREPARE_PASS; no services stopped and no PL programmed', flush=True)

    def remember(self, path):
        path = Path(path)
        key = str(path)
        if key in self.saved: return
        if path.is_symlink(): raise RuntimeError('Refuse replacing a symlink: '+key)
        entry = dict(existed=path.exists())
        if path.exists():
            if not path.is_file(): raise RuntimeError('Expected regular configuration file: '+key)
            dest = self.backup/'files'/path.relative_to('/')
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            entry.update(copy=str(dest), mode=path.stat().st_mode & 0o777, sha256=sha(path))
        self.saved[key] = entry

    def put(self, path, content, mode=0o644):
        self.remember(path)
        self.saved[str(Path(path))]['modified'] = True
        self.changed = True
        self.journal('CONFIGURING')
        atomic_write(path, content, mode)

    def journal(self, state, **extra):
        body = dict(schema='so101-planner-install-v1', status=state, runtime=str(self.root),
                    previous_runtime=str(self.old), shared_data=str(self.data), files=self.saved,
                    previous_services=self.states, hardware_attempted=self.hardware_attempted,
                    motor_motion_sent=False, boot_files_changed=False, **extra)
        atomic_write(self.backup/'install.json', json.dumps(body, indent=2)+'\n')

    def stop_all(self):
        # Explicit reverse dependency order allows LCD DDR to drain before PL changes.
        for unit in STOP_ORDER:
            self.run(['systemctl', 'stop', unit], check=False)
        for unit in STOP_ORDER:
            if self.property(unit, 'MainPID') not in ('', '0') or self.active(unit):
                raise RuntimeError('Service did not stop: '+unit)
            if self.property(unit, 'Result') in ('timeout', 'signal', 'watchdog', 'core-dump'):
                raise RuntimeError('Unsafe forced service stop: '+unit+'; reboot before programming PL')
        from planner_accel_lease import acquire_planner_lease
        with acquire_planner_lease(0x40000000): pass
        # Old display/touch versions left status files after clean shutdown.
        for name in ('status.json', 'touch.json'):
            path = Path('/run/so101-lcd')/name
            if path.exists(): path.unlink()

    def configure(self):
        allow = self.allow_motion and not self.args.disable_motion
        profile = migrated_profile(self.previous, self.root)
        self.put('/etc/so101/runtime.desktop.json', json.dumps(profile, indent=2)+'\n', 0o600)
        config = dict(SO101_APP=str(self.root), SO101_PLATFORM=str(self.root/'overlay/planner_platform/platform.json'),
                      SO101_DATA=str(self.data), SO101_PYTHON=str(self.py),
                      SO101_PROFILE='/etc/so101/runtime.desktop.json', SO101_ALLOW_MOTION='1' if allow else '0')
        self.put('/etc/so101/desktop.env', ''.join(k+'='+shlex.quote(v)+'\n' for k,v in config.items()), 0o600)
        for name, source in (
            ('so101-platform-start', 'deploy/standalone'),
            ('so101-workbench-start', 'deploy/standalone'),
            ('so101-md0700r-start', 'deploy/pynq-md0700r'),
            ('so101-gt911-start', 'deploy/pynq-md0700r')):
            self.put('/usr/local/bin/'+name, (self.root/source/name).read_bytes(), 0o755)
        for name, source in (
            ('so101-platform.service', 'deploy/standalone'),
            ('so101-md0700r.service', 'deploy/pynq-md0700r'),
            ('so101-gt911.service', 'deploy/pynq-md0700r')):
            self.put('/etc/systemd/system/'+name, (self.root/source/name).read_bytes())
        # Keep USB host dependencies and existing units/drop-ins. This final
        # override supersedes cloud.conf's old executable, using its copied profile.
        command = ' '.join(json.dumps(str(v)) for v in
            (self.py, '-B', self.root/'scripts/run_board.py', '--profile', '/etc/so101/runtime.desktop.json',
             '--data-dir', self.data)) + (' --allow-motion' if allow else '')
        dropin = ('[Unit]\nRequires=so101-platform.service\nAfter=so101-platform.service\n'
                  'PartOf=so101-platform.service\nWants=so101-md0700r.service\n[Service]\n'
                  'WorkingDirectory='+str(self.root)+'\nEnvironmentFile=\nEnvironmentFile='+str(self.root/'.pynq-service.env')+'\n'
                  'ExecStart=\nExecStart='+command+'\nTimeoutStopSec=infinity\n')
        self.put('/etc/systemd/system/so101-workbench.service.d/zzzz-planner.conf', dropin)
        self.put('/etc/systemd/system/so101-platform.service.d/runtime.conf',
                 '[Service]\nEnvironmentFile='+str(self.root/'.pynq-service.env')+'\n')
        self.put('/etc/systemd/system/so101-md0700r.service.d/runtime.conf',
                 '[Service]\nEnvironmentFile='+str(self.root/'.pynq-service.env')+'\n')
        self.run(['systemctl', 'daemon-reload'])

    def wait_ready(self):
        # Display startup allows up to 100 s for GUI plus 15 s before its first
        # hardware-frame status. Leave margin on the ARM board before rollback.
        deadline = time.monotonic()+180
        last = None
        while time.monotonic() < deadline:
            try:
                status = request_json(self.port, '/api/status')
                if status.get('ik_backend') != 'PL_planner_accel_v2':
                    raise RuntimeError('Wrong planner backend')
                if status.get('ik_metrics', {}).get('faulted'):
                    raise RuntimeError('Planner backend faulted')
                for unit in UNITS:
                    if not self.active(unit): raise RuntimeError('Service not active: '+unit)
                display = json.loads(Path('/run/so101-lcd/status.json').read_text())
                touch = json.loads(Path('/run/so101-lcd/touch.json').read_text())
                if display.get('status') != 'RUNNING' or touch.get('status') != 'RUNNING':
                    raise RuntimeError('Display/touch readiness pending')
                expected = sha(self.root/'overlay/planner_platform/drawing_planner.bit')
                if display.get('bit_sha256') != expected or not display.get('hardware_frames_verified'):
                    raise RuntimeError('Display identity/frame verification failed')
                return dict(backend=status.get('ik_backend'), display=display, touch=touch,
                            allow_motion=self.allow_motion and not self.args.disable_motion)
            except (OSError, ValueError, RuntimeError) as exc:
                last = str(exc); time.sleep(.5)
        raise RuntimeError('Planner service readiness failed: '+str(last))

    def rollback(self):
        # stop_all refuses stale markers/force-killed DMA. Never blindly reload.
        self.stop_all()
        for name, entry in reversed(list(self.saved.items())):
            if not entry.get('modified'): continue
            path = Path(name)
            if entry['existed']:
                atomic_write(path, Path(entry['copy']).read_bytes(), entry['mode'])
            elif path.exists(): path.unlink()
        self.run(['systemctl', 'daemon-reload'])
        for unit, state in self.states.items():
            if state['enabled'] not in ('enabled', 'enabled-runtime'):
                self.run(['systemctl', 'disable', unit], check=False)
        if self.hardware_attempted:
            ready = Path('/run/so101-platform/ready.json')
            if ready.exists(): ready.unlink()
            from planner_accel_lease import acquire_planner_lease
            with acquire_planner_lease(0x40000000):
                self.run([self.old/'.venv/bin/python', '-B', self.old/'scripts/check_target_overlay.py',
                          '--overlay', self.previous_bit, '--output', self.backup/'rollback_target_gate.json'])
        for unit in UNITS:
            if self.states.get(unit, {}).get('active'):
                self.run(['systemctl', 'start', unit])
        self.journal('ROLLED_BACK')

    def install(self):
        if self.backup.exists(): raise ValueError('Backup directory already exists; choose a fresh directory')
        self.backup.mkdir(parents=True, mode=0o700)
        os.chmod(self.backup, 0o700)
        # Snapshot all old unit text and protected user files before touching services.
        for unit in UNITS:
            self.states[unit] = dict(active=self.active(unit), enabled=self.property(unit, 'UnitFileState'))
            atomic_write(self.backup/(unit+'.txt'), self.run(['systemctl', 'cat', unit], capture=True, check=False))
        self.allow_motion = '--allow-motion' in self.property('so101-workbench.service', 'ExecStart')
        if self.states['so101-workbench.service']['active']:
            jobs = request_json(self.port, '/api/jobs')
            if jobs.get('active') is not None: raise RuntimeError('Active board job; installation did not stop it')
        self.remember(self.profile)
        for path in [self.data/'machine.json']+list((self.data/'calibration_defaults').glob('*')):
            if path.is_file(): self.remember(path)
        self.journal('SNAPSHOT_COMPLETE')
        try:
            self.stop_all()
            before = data_manifest(self.data)
            atomic_write(self.backup/'data_before.json', json.dumps(before, indent=2)+'\n')
            self.configure()
            ready = Path('/run/so101-platform/ready.json')
            if ready.exists():
                self.remember(ready)
                self.saved[str(ready)]['modified'] = True
                ready.unlink()
            self.hardware_attempted = True
            self.journal('LOADING_PLATFORM')
            self.run(['systemctl', 'start', 'so101-platform.service'])
            if data_manifest(self.data) != before:
                raise RuntimeError('Shared data changed during installation; refusing to start workbench')
            self.run(['systemctl', 'start', 'so101-workbench.service'])
            self.run(['systemctl', 'start', 'so101-md0700r.service', 'so101-gt911.service'])
            result = self.wait_ready()
            for name, entry in self.saved.items():
                path = Path(name)
                if (path == self.data/'machine.json' or path.parent == self.data/'calibration_defaults') and sha(path) != entry['sha256']:
                    raise RuntimeError('Calibration changed during startup')
            self.run(['systemctl', 'enable']+list(UNITS))
            self.journal('INSTALLED_NO_MOTION_SMOKE_PASS', readiness=result,
                         board_acceptance='IK_FK_DDR_AND_DISPLAY_SMOKE_ONLY',
                         touch_physical_test='NOT_RUN', planning_timing='NOT_RUN')
            print('PLANNER_INSTALLED_NO_MOTION_SMOKE_PASS backup='+str(self.backup), flush=True)
        except BaseException as exc:
            self.journal('FAILED', error=str(exc))
            try: self.rollback()
            except BaseException as rollback_error:
                self.journal('RECOVERY_REQUIRED_SERVICES_STOPPED', error=str(exc), rollback_error=str(rollback_error))
                print('Automatic rollback unsafe/failed; leave services stopped and inspect '+str(self.backup), file=sys.stderr)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous-runtime', type=Path, required=True)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--disable-motion', action='store_true')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        parser.error('Run as root on the board; no boot files or motor commands are changed')
    import fcntl
    Path('/run/lock').mkdir(exist_ok=True)
    with open('/run/lock/so101-installer.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        installer = Installer(args)
        installer.prepare()
        if not args.prepare_only: installer.install()


if __name__ == '__main__': main()
