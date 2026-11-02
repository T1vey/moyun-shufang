"""Keep the phone-upload service, local kiosk and settings desktop coordinated.

The display bridge owns this process. Switching the visible interface never
restarts the backend, reloads the overlay, or submits an execution request.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


class ScreenClient:
    """Only the local, fixed settings endpoints are exposed to the supervisor."""

    def __init__(self, port):
        self.base = 'http://127.0.0.1:%d' % port
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, path):
        if path not in ('/api/state', '/api/view'):
            raise ValueError('Unsupported local desktop endpoint')
        with self.opener.open(self.base + path, timeout=2) as response:
            result = json.load(response)
        if not isinstance(result, dict):
            raise ValueError('Invalid desktop response')
        return result

    def close_settings(self):
        state = self.get('/api/state')
        token = state.get('control_token')
        if not isinstance(token, str) or not token:
            raise ValueError('Local screen token is unavailable')
        request = urllib.request.Request(
            self.base + '/api/settings/close', data=b'{}', method='POST',
            headers={'Content-Type': 'application/json', 'X-Screen-Token': token})
        with self.opener.open(request, timeout=2) as response:
            return json.load(response)


def server_command(args):
    return [sys.executable, '-B', str(ROOT / 'user_gui/display_server.py'),
            '--no-browser', '--bind', '0.0.0.0', '--port', str(args.web_port),
            '--uploads', str(args.data_dir / 'user_gui/uploads'), '--workflow',
            '--backend-url', 'http://127.0.0.1:%d' % args.port,
            '--data-dir', str(args.data_dir), '--secrets-file', str(args.secrets_file)]


def settings_command(args):
    command = [sys.executable, '-B', str(ROOT / 'scripts/run_touch_gui.py'),
               '--windowed', '--return-user-gui', '--data-dir', str(args.data_dir),
               '--port', str(args.port), '--secrets-file', str(args.secrets_file)]
    if args.offline:
        command.append('--offline')
    return command


def kiosk_command(args):
    return [args.browser_python, '-B', str(ROOT / 'scripts/user_gui_kiosk.py'),
            '--port', str(args.web_port)]


def start_process(command):
    return subprocess.Popen(command, cwd=str(ROOT), start_new_session=True)


def stop_process(process, timeout=2):
    if process is None:
        return
    # WebKit has renderer children. Always address its process group, including
    # when its main process has already exited, so no orphan owns an X window.
    def send(sig):
        try:
            if os.name == 'posix':
                os.killpg(process.pid, sig)
            elif process.poll() is None:
                process.terminate() if sig == signal.SIGTERM else process.kill()
        except ProcessLookupError:
            pass
    send(signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        send(signal.SIGKILL if hasattr(signal, 'SIGKILL') else signal.SIGTERM)
        process.wait(timeout=3)
    if os.name == 'posix':
        # Parent exit is not proof that a WebKit renderer exited with it.
        send(signal.SIGKILL)


class DesktopSupervisor:
    def __init__(self, args, client=None, launcher=start_process, stopper=stop_process):
        self.args = args
        self.client = client or ScreenClient(args.web_port)
        self.launcher = launcher
        self.stopper = stopper
        self.server = None
        self.kiosk = None
        self.settings = None
        self.return_pending = False
        self.kiosk_crashes = []
        self.errors = 0

    def start(self, stopped):
        self.server = self.launcher(server_command(self.args))
        deadline = time.monotonic() + 40
        while not stopped.is_set():
            if self.server.poll() is not None:
                raise RuntimeError('User interface service exited during startup')
            try:
                self.client.get('/api/view')
                break
            except (OSError, ValueError):
                if time.monotonic() >= deadline:
                    raise RuntimeError('User interface service did not become ready')
                stopped.wait(.3)
        if not stopped.is_set():
            self.kiosk = self.launcher(kiosk_command(self.args))

    def step(self):
        if self.server.poll() is not None:
            raise RuntimeError('User interface service exited')
        if self.kiosk is None or self.kiosk.poll() is not None:
            if self.kiosk is not None:
                self.stopper(self.kiosk)
                now = time.monotonic()
                self.kiosk_crashes = [t for t in self.kiosk_crashes if now-t < 60] + [now]
                if len(self.kiosk_crashes) >= 3:
                    raise RuntimeError('WebKit repeatedly exited; inspect the desktop log')
                print('USER_GUI_RESTARTING_KIOSK', flush=True)
            self.kiosk = self.launcher(kiosk_command(self.args))

        if self.settings is not None and self.settings.poll() is not None:
            self.stopper(self.settings)
            self.settings = None
            self.return_pending = True
        if self.return_pending:
            # Returning is a view change, not a request to cancel or execute a
            # task. The API allows recovery even after an unexpected Tk exit.
            self.client.close_settings()
            self.return_pending = False
        view = self.client.get('/api/view').get('view')
        if view not in ('user', 'settings'):
            raise ValueError('Invalid local desktop view')
        if view == 'settings' and self.settings is None:
            self.settings = self.launcher(settings_command(self.args))
            print('USER_GUI_SETTINGS_OPEN', flush=True)
        # A settings-close request can only come from a local screen. Normally
        # it is sent above after Tk exits. Do not kill a live settings window:
        # its own busy guard must retain ownership of ongoing work.

    def close(self):
        for process in (self.settings, self.kiosk, self.server):
            self.stopper(process)
        self.settings = self.kiosk = self.server = None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path('/home/xilinx/so101_data_work107'))
    parser.add_argument('--secrets-file', type=Path, default=Path('/home/xilinx/.config/so101/secrets.local.json'))
    parser.add_argument('--port', type=int, default=8765, help='Existing drawing backend port')
    parser.add_argument('--web-port', type=int, default=8090)
    parser.add_argument('--browser-python', default=os.environ.get('SO101_BROWSER_PYTHON', '/usr/bin/python3'))
    parser.add_argument('--windowed', action='store_true', help='Accepted for display-launcher compatibility')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--classic', action='store_true', help='Launch the original settings console only')
    args = parser.parse_args(argv)
    if not all(1024 <= port <= 65535 for port in (args.port, args.web_port)):
        parser.error('Invalid backend or user interface port')
    if args.port == args.web_port:
        parser.error('Backend and user interface need distinct ports')
    return args


def main(argv=None):
    args = parse_args(argv)
    for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[key] = '1'
    if args.classic:
        command = settings_command(args)
        command.remove('--return-user-gui')
        os.execv(sys.executable, command)
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    desktop = DesktopSupervisor(args)
    try:
        desktop.start(stopped)
        while not stopped.wait(.5):
            try:
                desktop.step()
                desktop.errors = 0
            except (OSError, ValueError) as error:
                desktop.errors += 1
                if desktop.errors >= 10:
                    raise RuntimeError('Local desktop service stopped responding') from error
    finally:
        desktop.close()


if __name__ == '__main__':
    main()
