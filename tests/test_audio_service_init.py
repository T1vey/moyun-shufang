"""Initialization lifecycle regressions; no PYNQ mapping or board access."""
import threading
import time
import unittest

from audio_player.service import AudioService


def wait(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.002)
    raise AssertionError('background operation timed out')


class Catalog:
    items = {}

    def public(self):
        return []


class Device:
    depth = 16384
    codec_probe = {'0x1a': True, '0x22': False}

    def __init__(self):
        self.calls = []

    def init_codec(self, **kwargs):
        self.calls.append(('init', kwargs))

    def set_ctrl(self, **kwargs):
        self.calls.append(('ctrl', kwargs))

    def set_volume(self, *args):
        self.calls.append(('volume', args))

    def level(self):
        return 0


class AudioInitializationTests(unittest.TestCase):
    def test_hardware_snapshots_refresh_in_worker_not_status(self):
        owner = {}

        class CountingDevice(Device):
            init_frame_hz = 48000.0

            def __init__(self):
                super().__init__()
                self.reads = []

            def counters(self):
                lock_held = None
                if 'service' in owner:
                    lock = owner['service'].player.lock
                    acquired = lock.acquire(blocking=False)
                    lock_held = not acquired
                    if acquired:
                        lock.release()
                self.reads.append((time.monotonic(), threading.current_thread().name, lock_held))
                return dict(frames=len(self.reads) * 48000, underruns=0, overflows=0, level=10)

        device = CountingDevice()
        service = AudioService(Catalog(), lambda: device)
        try:
            wait(lambda: service.status()['available'])
            owner['service'] = service
            initial = service.status()['hardware']
            self.assertEqual(initial['frames'], 48000)
            self.assertEqual(initial['frame_rate_hz'], 48000.0)
            self.assertIsInstance(initial['snapshot_at'], float)
            for _ in range(100):
                self.assertEqual(service.status()['hardware'], initial)
            self.assertEqual(len(device.reads), 1)
            wait(lambda: service.status()['hardware']['frames'] == 96000)
            refreshed = service.status()['hardware']
            self.assertGreater(refreshed['snapshot_at'], initial['snapshot_at'])
            self.assertGreaterEqual(device.reads[1][0] - device.reads[0][0], 1.0)
            self.assertEqual([call[1] for call in device.reads], ['audio-control', 'audio-control'])
            self.assertTrue(device.reads[1][2])
            for _ in range(100):
                service.status()
            self.assertEqual(len(device.reads), 2)
        finally:
            service.close()

    def test_counter_failure_does_not_mark_audio_unavailable(self):
        class FlakyDevice(Device):
            def __init__(self):
                super().__init__()
                self.reads = 0

            def counters(self):
                self.reads += 1
                if self.reads == 1:
                    raise OSError('diagnostic read failed')
                return dict(frames=48000, underruns=0)

        service = AudioService(Catalog(), FlakyDevice)
        try:
            wait(lambda: service.status()['available'])
            state = service.status()
            self.assertIsNone(state['error'])
            self.assertEqual(state['hardware_error'], 'diagnostic read failed')
            self.assertTrue(service.thread.is_alive())
            wait(lambda: service.status()['hardware'] is not None)
            self.assertIsNone(service.status()['hardware_error'])
            self.assertTrue(service.status()['available'])
        finally:
            service.close()

    def test_slow_factory_status_remains_readable_and_marks_phase(self):
        entered, release = threading.Event(), threading.Event()

        def factory():
            entered.set()
            if not release.wait(2):
                raise TimeoutError('test factory release')
            return Device()

        service = AudioService(Catalog(), factory)
        try:
            self.assertTrue(entered.wait(1))
            start = time.monotonic()
            state = service.status()
            self.assertLess(time.monotonic() - start, 0.05)
            self.assertTrue(state['initializing'])
            self.assertFalse(state['available'])
            self.assertEqual(state['phase'], 'attach')
            self.assertEqual(state['init_attempt'], 1)
            self.assertIsInstance(state['init_started_at'], float)
            time.sleep(0.02)
            self.assertGreater(service.status()['init_elapsed_s'], state['init_elapsed_s'])
            release.set()
            wait(lambda: service.status()['available'])
            self.assertEqual(service.status()['phase'], 'ready')
            self.assertEqual(service.status()['codec_probe'], Device.codec_probe)
        finally:
            release.set()
            service.close()

    def test_concurrent_retry_starts_only_one_attempt_and_clears_old_snapshot(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        class FailedDevice(Device):
            class MMIO:
                def read(self, addr):
                    return 4 if addr == 8 else 0x40000

            mmio = MMIO()

            def counters(self):
                return dict(frames=0)

            def init_codec(self, **kwargs):
                raise RuntimeError('no clock')

        def factory():
            calls.append(1)
            if len(calls) == 1:
                return FailedDevice()
            entered.set()
            if not release.wait(2):
                raise TimeoutError('test factory release')
            return Device()

        service = AudioService(Catalog(), factory)
        try:
            wait(lambda: not service.thread.is_alive())
            failed = service.status()
            self.assertEqual(failed['phase'], 'codec_init')
            self.assertEqual(failed['error'], 'no clock')
            self.assertEqual(failed['hardware']['frames'], 0)
            self.assertEqual(failed['codec_probe'], Device.codec_probe)
            results = []
            contenders = [threading.Thread(target=lambda: results.append(service.submit('retry')))
                          for _ in range(8)]
            for thread in contenders:
                thread.start()
            for thread in contenders:
                thread.join(1)
                self.assertFalse(thread.is_alive())
            self.assertTrue(entered.wait(1))
            self.assertEqual(sum(result['retry_started'] for result in results), 1)
            self.assertEqual(sum(result.get('reason') == 'already_initializing' for result in results), 7)
            self.assertEqual(len(calls), 2)
            state = service.status()
            self.assertEqual(state['init_attempt'], 2)
            self.assertEqual(state['phase'], 'attach')
            self.assertIsNone(state['hardware'])
            self.assertIsNone(state['codec_probe'])
            self.assertIsNone(state['error'])
            release.set()
            wait(lambda: service.status()['available'])
        finally:
            release.set()
            service.close()

    def test_close_during_codec_initialization_never_announces_ready(self):
        entered, release = threading.Event(), threading.Event()

        class SlowDevice(Device):
            def init_codec(self, **kwargs):
                entered.set()
                if not release.wait(2):
                    raise TimeoutError('test codec release')
                super().init_codec(**kwargs)

        device = SlowDevice()
        service = AudioService(Catalog(), lambda: device)
        closer = threading.Thread(target=service.close)
        try:
            self.assertTrue(entered.wait(1))
            self.assertEqual(service.status()['phase'], 'codec_init')
            closer.start()
            self.assertTrue(service.quit.wait(1))
            self.assertFalse(service.status()['available'])
            with self.assertRaisesRegex(RuntimeError, '关闭'):
                service.submit('retry')
            release.set()
            closer.join(1)
            self.assertFalse(closer.is_alive())
            self.assertFalse(service.thread.is_alive())
            state = service.status()
            self.assertFalse(state['available'])
            self.assertFalse(state['initializing'])
            self.assertEqual(state['phase'], 'closed')
            self.assertIn(('ctrl', {'enable': False, 'mute': True}), device.calls)
            self.assertIn(('volume', (0, 0)), device.calls)
        finally:
            release.set()
            service.close()
            if closer.ident:
                closer.join(1)


if __name__ == '__main__':
    unittest.main()
