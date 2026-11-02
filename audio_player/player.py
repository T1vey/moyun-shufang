"""Stream 48 kHz speech to the codec's native sample rate in bounded chunks.

Linear interpolation preserves duration/pitch for the small 48k -> 48,828.125 Hz
ES8388 rate correction. It is speech-oriented, not a band-limited music SRC;
high frequencies can attenuate, and arbitrary downsampling has no anti-alias filter.
The original WAV is kept unchanged; no second full-length audio array is built.
"""
import math
import threading
import time
import wave
import numpy as np
from . import contract as c

TARGET_S = 0.25      # keep about this much audio queued in the PL FIFO
TICK_S = 0.04
MAX_OUTPUT_CHUNK = 12000


def load_wav(path):
    with wave.open(str(path), 'rb') as w:
        if (w.getframerate(), w.getsampwidth(), w.getnchannels()) != (c.SAMPLE_RATE, 2, 1):
            raise ValueError('朗读音频必须是 48 kHz、16 位、单声道 WAV：' + str(path))
        return np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').copy()


class _NativePCM:
    """Random-access streaming SRC, with absolute output indices as the phase.

    Only a requested <=12000-sample output chunk has interpolation work arrays.
    Retrying a partial FIFO write regenerates the same unaccepted output samples.
    """
    def __init__(self, samples, sample_rate):
        self.samples = np.asarray(samples, dtype='<i2')
        if self.samples.ndim != 1:
            raise ValueError('Audio samples must be mono')
        self.sample_rate = float(sample_rate)
        if not math.isfinite(self.sample_rate) or self.sample_rate <= 0:
            raise ValueError('Invalid native audio sample rate')
        self.duration_s = len(self.samples) / c.SAMPLE_RATE
        self.native_frames = math.ceil(len(self.samples) * self.sample_rate / c.SAMPLE_RATE)

    def padded_end(self, start):
        """Pair packing may need one trailing zero, including after an odd resume."""
        remaining = max(0, self.native_frames - start)
        return start + remaining + (remaining & 1)

    def chunk(self, start, count):
        count = max(0, min(int(count), MAX_OUTPUT_CHUNK))
        if start < 0:
            raise ValueError('Negative audio sample position')
        if self.sample_rate == c.SAMPLE_RATE:
            # Preserve all original PCM bits and avoid copying ordinary chunks.
            payload = self.samples[start:start + count]
            if len(payload) == count:
                return payload
            result = np.zeros(count, dtype='<i2')
            result[:len(payload)] = payload
            return result
        result = np.zeros(count, dtype='<i2')
        valid = min(count, max(0, self.native_frames - start))
        if not valid:
            return result
        positions = (start + np.arange(valid, dtype=np.float64)) * (c.SAMPLE_RATE / self.sample_rate)
        left = np.floor(positions).astype(np.int64)
        # The sample immediately after the source is zero, so the last fractional
        # interval fades to silence; any pair-packing sample also stays zero.
        a = self.samples[np.minimum(left, len(self.samples) - 1)].astype(np.float64)
        a[left >= len(self.samples)] = 0
        right = left + 1
        b = np.zeros(valid, dtype=np.float64)
        inside = right < len(self.samples)
        b[inside] = self.samples[right[inside]]
        result[:valid] = np.rint(a + (positions - left) * (b - a)).astype('<i2')
        return result


class Player:
    def __init__(self, device, clock=time.monotonic, sleep=time.sleep):
        self.device, self.clock, self.sleep = device, clock, sleep
        self.sample_rate = float(getattr(device, 'sample_rate', c.SAMPLE_RATE))
        if not math.isfinite(self.sample_rate) or self.sample_rate <= 0:
            raise ValueError('Invalid native audio sample rate')
        self.lock = threading.Lock()
        self.thread = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.item = None
        self.samples = None
        self.stream = None
        self.output_end = 0
        self.queued = 0          # absolute native-rate sample index after the FIFO tail
        self.error = None
        self.finished = False
        self.last_position = 0.0

    def play(self, item, samples, start_s=0.0):
        self.stop()
        with self.lock:
            stream = _NativePCM(samples, self.sample_rate)
            start_s = float(start_s)
            if not math.isfinite(start_s):
                raise ValueError('Invalid audio start position')
            start_s = max(0.0, start_s)
            self.item, self.samples, self.stream = item, stream.samples, stream
            self.queued = (stream.native_frames if start_s >= stream.duration_s else
                           int(start_s * self.sample_rate))
            self.output_end = stream.padded_end(self.queued)
            self.error, self.finished = None, False
            self.last_position = self._seconds(self.queued)
            self.stop_event.clear(); self.pause_event.clear()
            self.device.set_ctrl(enable=False, clear=True, mute=False)
            self._prefill()
            self.device.set_ctrl(enable=True)
            self.thread = threading.Thread(target=self._run, name='audio-player', daemon=True)
            self.thread.start()

    def _seconds(self, native_index):
        return min(self.stream.duration_s, max(0, native_index) / self.sample_rate)

    def _target(self):
        return max(0, min(int(TARGET_S * self.sample_rate), self.device.depth - 2,
                          MAX_OUTPUT_CHUNK)) & ~1

    def _queue(self, count):
        count = min(max(0, int(count)), MAX_OUTPUT_CHUNK, self.output_end - self.queued) & ~1
        if not count:
            return
        samples = self.stream.chunk(self.queued, count)
        accepted = self.device.push(samples)
        if not isinstance(accepted, (int, np.integer)) or accepted < 0 or accepted > count or accepted & 1:
            raise RuntimeError('Audio FIFO returned an invalid paired sample count')
        self.queued += int(accepted)

    def _prefill(self):
        self._queue(self._target() - self.device.level())

    def _run(self):
        target = self._target()
        try:
            while not self.stop_event.is_set():
                if self.pause_event.is_set():
                    self.sleep(TICK_S); continue
                with self.lock:
                    if self.pause_event.is_set():
                        continue
                    level = self.device.level()
                    self.last_position = self._seconds(self.queued - level)
                    if self.queued >= self.output_end:
                        if level == 0:
                            self.finished = True
                            self.last_position = self.stream.duration_s
                            break
                    else:
                        self._queue(target - level)
                self.sleep(TICK_S)
        except Exception as exc:   # noqa: BLE001 - surfaced through status()
            self.error = str(exc)
        finally:
            try:
                with self.lock:
                    self.device.set_ctrl(enable=False, clear=True)
            except Exception:      # noqa: BLE001
                pass

    def pause(self):
        if self.thread and self.thread.is_alive():
            self.pause_event.set()
            # Stop consumption before sampling the FIFO level.  Absolute output
            # indices preserve fractional SRC phase, even after an odd frame count.
            with self.lock:
                self.device.set_ctrl(enable=False)
                self.queued = max(0, self.queued - self.device.level())
                self.last_position = self._seconds(self.queued)
                self.output_end = self.stream.padded_end(self.queued)
                self.device.set_ctrl(enable=False, clear=True)

    def resume(self):
        with self.lock:
            if self.thread and self.thread.is_alive() and self.pause_event.is_set():
                self._prefill()
                self.device.set_ctrl(enable=True)
                self.pause_event.clear()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                raise RuntimeError('朗读线程尚未停止，已拒绝启动第二个播放器')
        self.thread = None

    def position_s(self):
        with self.lock:
            if self.samples is None:
                return 0.0
            return self.last_position

    def status(self):
        playing = bool(self.thread and self.thread.is_alive())
        item = self.item or {}
        pos = self.position_s()
        sentence = None
        for i, seg in enumerate(item.get('timeline', [])):
            if seg['start'] <= pos < seg['end']:
                sentence = i
        return dict(playing=playing and not self.pause_event.is_set(), paused=playing and self.pause_event.is_set(),
                    finished=self.finished, id=item.get('id'), title=item.get('title'), position_s=round(pos, 2),
                    duration_s=round(self.stream.duration_s, 2) if self.stream is not None else 0,
                    sentence=sentence, error=self.error)
