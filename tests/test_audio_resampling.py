"""Native codec sample-rate correction without hardware or whole-recording SRC."""
import math
import threading
import time
import unittest

import numpy as np

from audio_player.player import MAX_OUTPUT_CHUNK, Player, _NativePCM


NATIVE_RATE = 12_500_000 / 256


def wait(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.002)
    raise AssertionError('background operation timed out')


def render(stream, start=0, chunks=(4096, 3334, 11998)):
    end = stream.padded_end(start)
    result, index = [], 0
    while start < end:
        chunk = stream.chunk(start, min(chunks[index % len(chunks)], end - start))
        result.append(chunk)
        start += len(chunk)
        index += 1
    return np.concatenate(result) if result else np.empty(0, dtype='<i2')


class ManualDevice:
    """FIFO consumption is advanced by the test while holding Player.lock."""
    depth = 16384
    sample_rate = NATIVE_RATE

    def __init__(self, partial_limit=None):
        self.fifo = []
        self.played = []
        self.enabled = False
        self.partial_limit = partial_limit
        self.push_sizes = []

    def level(self):
        return len(self.fifo)

    def set_ctrl(self, enable=None, clear=False, mute=None):
        if enable is not None:
            self.enabled = enable
        if clear:
            self.fifo = []

    def push(self, samples):
        self.push_sizes.append(len(samples))
        accepted = min(len(samples), self.depth - len(self.fifo))
        if self.partial_limit is not None:
            accepted = min(accepted, self.partial_limit)
        accepted &= ~1
        self.fifo.extend(samples[:accepted].tolist())
        return accepted

    def advance(self, count):
        if self.enabled:
            count = min(count, len(self.fifo))
            self.played.extend(self.fifo[:count])
            del self.fifo[:count]


class NativePCMTests(unittest.TestCase):
    def test_one_khz_pitch_count_and_duration_at_es8388_native_rate(self):
        source = np.rint(20000 * np.sin(2 * np.pi * 1000 * np.arange(48000) / 48000)).astype('<i2')
        stream = _NativePCM(source, NATIVE_RATE)
        self.assertIs(stream.samples, source)
        output = render(stream)
        self.assertEqual(stream.native_frames, 48829)
        self.assertEqual(len(output), 48830)
        self.assertEqual(output[-1], 0)
        self.assertAlmostEqual(len(output) / NATIVE_RATE, 1.0, delta=2 / NATIVE_RATE)
        spectrum = np.abs(np.fft.rfft(output[:stream.native_frames]))
        peak = np.argmax(spectrum[1:]) + 1
        measured_hz = peak * NATIVE_RATE / stream.native_frames
        self.assertAlmostEqual(measured_hz, 1000, delta=0.05)

    def test_chunks_keep_absolute_phase_and_bound_allocations(self):
        source = np.arange(48000, dtype='<i2')
        stream = _NativePCM(source, NATIVE_RATE)
        a = render(stream, chunks=(12000,))
        b = render(stream, chunks=(2, 1026, 3332, 7998))
        np.testing.assert_array_equal(a, b)
        positions = np.arange(stream.native_frames) * (48000 / NATIVE_RATE)
        reference = np.rint(np.interp(positions, np.arange(len(source) + 1),
                                    np.append(source, 0))).astype('<i2')
        np.testing.assert_array_equal(a[:stream.native_frames], reference)
        self.assertEqual(len(stream.chunk(0, 1000000)), MAX_OUTPUT_CHUNK)
        self.assertIs(stream.samples, source)

    def test_48000_is_bit_exact_and_odd_final_frame_is_zero_padded(self):
        source = np.array([-32768, 32767, -1, 0, 123], dtype='<i2')
        stream = _NativePCM(source, 48000)
        self.assertTrue(np.shares_memory(stream.chunk(0, 4), source))
        np.testing.assert_array_equal(render(stream), [-32768, 32767, -1, 0, 123, 0])
        self.assertEqual(stream.duration_s, 5 / 48000)

    def test_invalid_rate_and_empty_input(self):
        for rate in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                _NativePCM(np.zeros(2, dtype='<i2'), rate)
        stream = _NativePCM(np.empty(0, dtype='<i2'), NATIVE_RATE)
        self.assertEqual(stream.native_frames, 0)
        self.assertEqual(len(render(stream)), 0)


class NativePlayerTests(unittest.TestCase):
    def make_player(self, device):
        return Player(device, sleep=lambda _: time.sleep(0.001))

    def finish(self, player, device):
        deadline = time.monotonic() + 2
        while not player.finished and time.monotonic() < deadline:
            with player.lock:
                device.advance(100000)
            time.sleep(0.002)
        self.assertTrue(player.finished, player.error)
        player.stop()

    def test_partial_fifo_push_does_not_skip_resampling_phase(self):
        source = (np.arange(2400) * 13).astype('<i2')
        device = ManualDevice(partial_limit=62)
        player = self.make_player(device)
        try:
            player.play({'id': 'partial'}, source)
            self.finish(player, device)
            np.testing.assert_array_equal(device.played, render(_NativePCM(source, NATIVE_RATE)))
            self.assertTrue(all(size <= MAX_OUTPUT_CHUNK for size in device.push_sizes))
            self.assertEqual(player.position_s(), len(source) / 48000)
        finally:
            player.stop()

    def test_nonzero_start_uses_native_index_but_status_reports_seconds(self):
        source = (np.arange(4800) * 3).astype('<i2')
        device = ManualDevice()
        player = self.make_player(device)
        try:
            start_s = 101.4 / NATIVE_RATE
            player.play({'id': 'seek', 'timeline': [dict(start=0, end=.1, text='一句')]}, source,
                        start_s=start_s)
            self.assertAlmostEqual(player.position_s(), 101 / NATIVE_RATE)
            self.assertEqual(player.status()['sentence'], 0)
            self.assertEqual(player.status()['duration_s'], .1)
            self.finish(player, device)
            np.testing.assert_array_equal(device.played, render(_NativePCM(source, NATIVE_RATE), start=101))
            self.assertEqual(player.position_s(), .1)
        finally:
            player.stop()

    def test_pause_resume_odd_native_index_keeps_every_payload_sample(self):
        source = (np.arange(1001) * 17).astype('<i2')
        device = ManualDevice()
        player = self.make_player(device)
        try:
            player.play({'id': 'pause'}, source)
            with player.lock:
                device.advance(101)
            player.pause()
            self.assertFalse(device.enabled)
            self.assertEqual(player.queued, 101)
            self.assertAlmostEqual(player.position_s(), 101 / NATIVE_RATE)
            frozen = player.position_s()
            time.sleep(.01)
            self.assertEqual(player.position_s(), frozen)
            player.resume()
            self.finish(player, device)
            stream = _NativePCM(source, NATIVE_RATE)
            expected = np.concatenate((stream.chunk(0, 101), render(stream, start=101)))
            np.testing.assert_array_equal(device.played, expected)
            self.assertEqual(len(device.played), stream.padded_end(101))
            self.assertEqual(player.position_s(), len(source) / 48000)
        finally:
            player.stop()

    def test_start_at_end_and_empty_audio_finish_without_samples(self):
        for source, start in ((np.arange(10, dtype='<i2'), 1.0),
                              (np.empty(0, dtype='<i2'), 0.0)):
            device = ManualDevice()
            player = self.make_player(device)
            try:
                player.play({'id': 'empty'}, source, start_s=start)
                wait(lambda: player.finished)
                self.assertEqual(device.played, [])
                self.assertEqual(device.fifo, [])
                self.assertEqual(player.position_s(), len(source) / 48000)
            finally:
                player.stop()


if __name__ == '__main__':
    unittest.main()
