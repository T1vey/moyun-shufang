"""audio_out_0 driver: WM8960 I2C writes and FIFO filling over AXI-Lite (no DMA)."""
import time
import numpy as np
from . import codec, contract as c


class AudioPL:
    def __init__(self, mmio, sleep=time.sleep, clock=time.monotonic):
        self.mmio, self.sleep, self.clock = mmio, sleep, clock
        ident, version = mmio.read(c.ID), mmio.read(c.VER)
        if ident != c.IDENTITY or version != c.VERSION:
            raise RuntimeError('audio_out_0 identity mismatch: %08x/%08x' % (ident, version))
        self.depth = mmio.read(c.DEPTH)
        if not 4 <= self.depth <= 16384:
            raise RuntimeError('Invalid audio FIFO depth')
        self.ctrl = c.CTRL_MCLK
        self.codec_probe = {}
        self.codec = codec
        self.codec_name = 'WM8960'
        self.codec_address = c.WM8960_ADDR
        self.sample_rate = float(c.SAMPLE_RATE)
        required = c.CAP_BUS_DIAG | c.CAP_ADDRESS_PROBE
        if mmio.read(c.CAPS) & required != required:
            raise RuntimeError('Audio FPGA needs the SDA/IOBUF repair; restart with the repaired platform')

    # -------------------------------------------------------------- codec
    def _transfer(self, word, timeout=0.05):
        status = self._wait_i2c(timeout)
        if not status & c.STATUS_SDA:
            raise RuntimeError('Audio I2C SDA is held low; check the FPGA IOBUF and codec bus')
        before = self.mmio.read(c.I2C_DONE)
        self.mmio.write(c.I2C, word)
        expected = (before + 1) & 0xffffffff
        deadline = self.clock() + timeout
        while True:
            done = self.mmio.read(c.I2C_DONE)
            status = self.mmio.read(c.STATUS)
            if done == expected and not status & c.STATUS_I2C_BUSY:
                if status & c.STATUS_BUS_STUCK:
                    raise RuntimeError('Audio I2C bus was not idle before START')
                return not bool(status & c.STATUS_I2C_NACK)
            if done not in (before, expected):
                raise RuntimeError('Audio I2C transaction counter changed unexpectedly')
            if self.clock() > deadline:
                raise TimeoutError('Audio I2C transaction did not complete')
            self.sleep(0.0002)

    def probe_address(self, address):
        if not 0x08 <= address <= 0x77:
            raise ValueError('Invalid I2C device address')
        # Address + W + ACK + STOP only; no codec register is written.
        return self._transfer(c.I2C_PROBE | address)

    def probe_codec(self):
        self.codec_probe = {}
        # This board routes this bus only to its audio codec. An absent address
        # must NACK, otherwise apparent ACKs cannot establish device identity.
        for address in (0x22, 0x10, 0x11, c.WM8960_ADDR):
            self.codec_probe['0x%02x' % address] = self.probe_address(address)
        if self.codec_probe['0x22']:
            raise RuntimeError('Audio I2C negative-control address ACKed; cannot identify codec reliably')
        addresses = [a for a in (0x10, 0x11, c.WM8960_ADDR)
                     if self.codec_probe['0x%02x' % a]]
        if not addresses:
            raise RuntimeError('No audio codec ACK at 0x1A, 0x10 or 0x11')
        if len(addresses) != 1:
            raise RuntimeError('Multiple audio codec addresses responded; refusing ambiguous initialization')
        self.codec_address = addresses[0]
        if self.codec_address in (0x10, 0x11):
            from . import codec_es8388
            self.codec = codec_es8388
            self.codec_name = 'ES8388'
            self.sample_rate = codec_es8388.SAMPLE_RATE
        else:
            self.codec = codec
            self.codec_name = 'WM8960'
            self.sample_rate = float(c.SAMPLE_RATE)

    def write_reg(self, reg, value, timeout=0.05):
        if self.codec_name == 'ES8388':
            if not 0 <= reg <= 0xff or not 0 <= value <= 0xff:
                raise ValueError('ES8388 register/value out of range')
            word = self.codec_address | (reg << 8) | (value << 16)
        else:
            word = c.i2c_word(reg, value)
        if not self._transfer(word, timeout):
            raise RuntimeError('%s did not acknowledge register 0x%02x' % (self.codec_name, reg))

    def _wait_i2c(self, timeout):
        deadline = self.clock() + timeout
        while True:
            status = self.mmio.read(c.STATUS)
            if not status & c.STATUS_I2C_BUSY:
                return status
            if self.clock() > deadline:
                raise TimeoutError('audio I2C busy')
            self.sleep(0.0002)

    def init_codec(self, speaker_pct=60, phone_pct=60):
        self.set_ctrl(enable=False, clear=True)
        self.probe_codec()
        for item in self.codec.init_sequence(speaker_pct, phone_pct):
            if item[0] == 'wait':
                self.sleep(item[1])
            else:
                self.write_reg(*item)
        self.check_frame_rate()

    def measure_frame_rate(self, settle_s=0.25, windows=3, window_s=0.3):
        """LRCK rate from the PL frame counter over several windows after the codec settles.

        A 50 ms window right after the DAC leaves reset read 35-40 kHz on the board
        (2026-10-27) while 30 s windows between re-inits read 48.67 kHz: the codec's
        start-up gap, not the clock.  Each window brackets its counter reads with clock
        reads, giving bounds that include MMIO and scheduling delay.
        """
        self.sleep(settle_s)
        result = []
        for _ in range(windows):
            t0 = self.clock(); f0 = self.mmio.read(c.FRAMES); t0b = self.clock()
            self.sleep(window_s)
            t1 = self.clock(); f1 = self.mmio.read(c.FRAMES); t1b = self.clock()
            frames = (f1 - f0) & 0xffffffff
            longest, shortest = max(t1b - t0, 1e-6), max(t1 - t0b, 1e-6)
            result.append(dict(frames=frames, elapsed_s=round((t1 + t1b - t0 - t0b) / 2, 4),
                               rate_hz=round(frames * 2 / max(t1 + t1b - t0 - t0b, 1e-6), 1),
                               low_hz=round(frames / longest, 1), high_hz=round(frames / shortest, 1),
                               read_s=round(max(t0b - t0, t1b - t1), 5)))
        return result

    def check_frame_rate(self, tolerance=0.005):
        windows = self.frame_windows = self.measure_frame_rate()
        rates = sorted(w['rate_hz'] for w in windows)
        self.init_frame_hz = rates[len(rates) // 2]
        if all(w['frames'] < 1000 for w in windows):
            raise RuntimeError('%s is not producing I2S frames (check MCLK)' % self.codec_name)
        # A window agrees when the expected rate lies within its timing bounds (plus
        # 0.5 % for the codec's own clock); a real divider error (e.g. 34.8 kHz) fails all.
        agree = [w for w in windows if w['low_hz'] * (1 - tolerance) <= self.sample_rate <= w['high_hz'] * (1 + tolerance)]
        if len(agree) * 2 <= len(windows):
            raise RuntimeError('Audio frame rate %.1f Hz differs from %.3f Hz (windows %s)' % (
                self.init_frame_hz, self.sample_rate, ', '.join('%.1f' % w['rate_hz'] for w in windows)))

    def set_volume(self, speaker_pct, phone_pct):
        for reg, value in self.codec.output_volume(speaker_pct, phone_pct):
            self.write_reg(reg, value)

    # -------------------------------------------------------------- stream
    def set_ctrl(self, enable=None, clear=False, mute=None):
        if enable is not None:
            self.ctrl = (self.ctrl | c.CTRL_ENABLE) if enable else (self.ctrl & ~c.CTRL_ENABLE)
        if mute is not None:
            self.ctrl = (self.ctrl | c.CTRL_MUTE) if mute else (self.ctrl & ~c.CTRL_MUTE)
        self.mmio.write(c.CTRL, self.ctrl | (c.CTRL_CLEAR if clear else 0))
        if clear:
            deadline = self.clock() + 0.02
            while self.level():
                if self.clock() > deadline:
                    raise TimeoutError('Audio FIFO clear timeout')
                self.sleep(0.0002)

    def level(self):
        return c.level(self.mmio.read(c.STATUS))

    def free(self):
        return self.depth - self.level()

    def push(self, samples):
        """Queue int16 mono samples (even count; truncated to the free space)."""
        samples = np.asarray(samples, dtype='<i2')
        n = min(len(samples), self.free()) & ~1
        words = samples[:n].view('<u4')
        done = 0
        while done < len(words):
            chunk = words[done:done + c.FIFO_WINDOW_WORDS]
            self.mmio.array[c.FIFO_WINDOW // 4:c.FIFO_WINDOW // 4 + len(chunk)] = chunk
            done += len(chunk)
        return n

    def counters(self):
        return dict(underruns=self.mmio.read(c.UNDERRUN), overflows=self.mmio.read(c.OVERFLOW),
                    frames=self.mmio.read(c.FRAMES), level=self.level())


def open_device():
    """Attach to the loaded platform (no bitstream download)."""
    from .hardware import attached_audio
    entry = attached_audio()
    from tcb705.accel_runtime import verify_planner_clock, attached_identity, ensure_event_loop
    ensure_event_loop()  # PYNQ device discovery requires a loop in this worker thread.
    cfg, _, _, _, _ = attached_identity()
    verify_planner_clock(cfg['accelerator_clock_hz'], cfg['accelerator_abi'])
    from pynq import MMIO
    return AudioPL(MMIO(entry['base'], entry['size']))
