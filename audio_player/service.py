"""One background control owner; HTTP and motion workers only enqueue commands."""
import copy
import threading
import time
from collections import deque
from .catalog import Catalog
from .device import open_device
from .player import Player


class AudioService:
    def __init__(self, catalog=None, factory=open_device):
        self.catalog = catalog
        self.factory = factory
        self.lock = threading.Lock()
        self.commands = deque()
        self.wake = threading.Event()
        self.quit = threading.Event()
        self.player = None
        self.epoch = 0
        self._items = []
        self._state = dict(available=False, initializing=True, playing=False, paused=False,
                           finished=False, volume=60, output='speaker', id=None, error=None,
                           position_s=0, duration_s=0, sentence=None, follow_owner=None,
                           init_attempt=0, phase='catalog', init_started_at=None, init_elapsed_s=0,
                           hardware=None, hardware_error=None, codec_probe=None)
        self._begin_initialization_locked()
        self.thread = threading.Thread(target=self._run, name='audio-control', daemon=True)
        self.thread.start()

    def _begin_initialization_locked(self):
        # Called before first startup, or under self.lock when the old worker has exited.
        self._init_started_monotonic = time.monotonic()
        self._state.update(initializing=True, available=False, error=None, phase='catalog',
                           init_attempt=self._state['init_attempt'] + 1,
                           init_started_at=time.time(), init_elapsed_s=0,
                           hardware=None, hardware_error=None, codec_probe=None)

    def _finish_initialization_locked(self, **values):
        if self._state['initializing']:
            self._state['init_elapsed_s'] = round(time.monotonic() - self._init_started_monotonic, 3)
        self._state.update(initializing=False, **values)

    def status(self):
        with self.lock:
            state = copy.deepcopy(self._state)
            if state['initializing']:
                state['init_elapsed_s'] = round(time.monotonic() - self._init_started_monotonic, 3)
            return state

    def listing(self):
        with self.lock:
            return dict(items=copy.deepcopy(self._items), available=self._state['available'])

    def _set(self, **values):
        with self.lock:
            self._state.update(values)

    def _snapshot_hardware(self, device, include_control=False):
        """Worker-only diagnostics: HTTP status returns this cache, never MMIO."""
        if not callable(getattr(device, 'counters', None)):
            return

        def read_snapshot():
            snapshot = dict(device.counters(), snapshot_at=time.time(),
                            frame_rate_hz=getattr(device, 'init_frame_hz', None),
                            frame_windows=getattr(device, 'frame_windows', None),
                            codec=getattr(device, 'codec_name', None),
                            native_sample_rate_hz=getattr(device, 'sample_rate', None))
            if include_control:
                snapshot.update(control=device.mmio.read(8), status=device.mmio.read(12))
            return snapshot

        try:
            if self.player is None:  # initialization has sole ownership of the device
                snapshot = read_snapshot()
            else:
                with self.player.lock:
                    snapshot = read_snapshot()
            self._set(hardware=snapshot, hardware_error=None)
        except Exception as exc:
            # Diagnostics are optional and cannot stop playback or arm execution.
            self._set(hardware_error=str(exc)[:200])

    def submit(self, action, data=None, owner=None):
        data = dict(data or {})
        if action == 'retry':
            with self.lock:
                if self.quit.is_set():raise RuntimeError('朗读服务正在关闭')
                if self.thread.is_alive():
                    reason = 'already_initializing' if self._state['initializing'] else 'already_running'
                    return dict(accepted=True, retry_started=False, reason=reason)
                self.commands.clear();self.player=None
                self._begin_initialization_locked()
                self.thread=threading.Thread(target=self._run,name='audio-control',daemon=True)
                self.thread.start()
            return dict(accepted=True, retry_started=True)
        if action not in ('play', 'pause', 'resume', 'stop', 'volume'):
            raise ValueError('未知朗读操作')
        if action == 'volume':
            value = data.get('volume')
            if type(value) is not int or not 0 <= value <= 100:
                raise ValueError('音量应为 0～100 的整数')
            if data.get('output', 'speaker') not in ('speaker', 'phone'):
                raise ValueError('请选择扬声器或耳机')
        with self.lock:
            if not self._state['available']:
                raise RuntimeError(self._state.get('error') or '朗读模块尚未准备好')
            if action == 'play' and data.get('id') not in self.catalog.items:
                raise ValueError('未找到所选诗文')
            if owner and action == 'stop' and self._state.get('follow_owner') != owner:
                return dict(accepted=True)  # never stop unrelated manual playback
            if action in ('play', 'stop'):
                self.epoch += 1
                self.commands.clear()
                self.player.stop_event.set()  # no device I/O or join in caller
                self._state['follow_owner'] = owner if action == 'play' else None
            if len(self.commands) >= 16:
                raise RuntimeError('朗读操作过于频繁，请稍后再试')
            self.commands.append((self.epoch, action, data))
        self.wake.set()
        return dict(accepted=True)

    def follow(self, action, key=None, owner=None):
        """Optional accompaniment: failure is contained and never affects arm commands."""
        try:
            return self.submit(action, {'id': key}, owner=owner)
        except (RuntimeError, ValueError):
            return dict(accepted=False)

    def _run(self):
        device = None
        initialized = False
        try:
            catalog = self.catalog or Catalog()
            with self.lock:
                self.catalog=catalog;self._items=catalog.public()
                if self.quit.is_set():return
                self._state['phase'] = 'attach'
            device = self.factory()  # verifies loaded platform before any AXI access
            if self.quit.is_set():return
            self._set(phase='codec_init')
            try:
                device.init_codec(speaker_pct=0, phone_pct=0)
                initialized = True
                self._snapshot_hardware(device)
            except Exception:
                self._snapshot_hardware(device, include_control=True)
                raise
            self.player = Player(device)
            with self.lock:
                self.catalog = catalog
                self._items = catalog.public()
                if self.quit.is_set():return
                self._finish_initialization_locked(available=True, phase='ready',
                                                   codec_probe=copy.deepcopy(getattr(device, 'codec_probe', None)))
            volume, output = 60, 'speaker'
            next_hardware_snapshot = time.monotonic() + 1.0
            while not self.quit.is_set():
                with self.lock:
                    command = self.commands.popleft() if self.commands else None
                if command:
                    epoch, action, data = command
                    try:
                        if action == 'play':
                            item, samples = catalog.load(data['id'])
                            with self.lock:
                                current = epoch == self.epoch
                            if current and not self.quit.is_set():
                                self.player.stop()
                                device.set_volume(volume if output == 'speaker' else 0,
                                                  volume if output == 'phone' else 0)
                                self._set(error=None)
                                self.player.play(item, samples)
                        elif action == 'stop':
                            self.player.stop()
                        elif action == 'pause':
                            self.player.pause()
                        elif action == 'resume':
                            self.player.resume()
                        elif action == 'volume':
                            volume, output = data['volume'], data.get('output', output)
                            with self.player.lock:
                                device.set_volume(volume if output == 'speaker' else 0,
                                                  volume if output == 'phone' else 0)
                            self._set(volume=volume, output=output)
                    except Exception as exc:
                        self.player.stop()
                        self._set(error=str(exc)[:200])
                status = self.player.status()
                if status.get('error') is None:
                    status.pop('error', None)
                self._set(**status)
                if time.monotonic() >= next_hardware_snapshot:
                    self._snapshot_hardware(device)
                    next_hardware_snapshot = time.monotonic() + 1.0
                self.wake.wait(0.04)
                self.wake.clear()
        except Exception as exc:
            with self.lock:
                self._finish_initialization_locked(available=False, error=str(exc)[:200],
                                                   codec_probe=copy.deepcopy(getattr(device, 'codec_probe', None)))
        finally:
            if self.player:
                try:
                    self.player.stop()
                except Exception:
                    pass
            # A slow initialization may complete after close() has returned.  Its worker
            # still owns the device and must leave it muted, without announcing readiness.
            if initialized:
                try:
                    device.set_ctrl(enable=False, mute=True)
                except Exception:
                    pass
                try:
                    device.set_volume(0, 0)
                except Exception:
                    pass
            with self.lock:
                if self.quit.is_set():
                    self._finish_initialization_locked(available=False, phase='closed', playing=False)

    def close(self):
        with self.lock:
            self.quit.set()
            self._state.update(available=False, phase='closing')
        if self.player:
            self.player.stop_event.set()
        self.wake.set()
        # Shutdown can join in the server shutdown thread, never in the motion worker.
        self.thread.join(timeout=2.0)
        if not self.thread.is_alive():
            with self.lock:
                self._finish_initialization_locked(available=False, phase='closed', playing=False)
