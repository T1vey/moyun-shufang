"""PYNQ adapter for z20_wls_step; addresses come from the generated HLS header."""
import json
from pathlib import Path
import time
import numpy as np
from pl_contract import validate_registers, validate_ip


class PynqStep:
    name = 'PL_z20_wls_step'

    def __init__(self, bitfile=None, ip_name='z20_wls_step_0', mmio=None, registers=None, timeout_s=.5):
        if not np.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError('PL timeout must be finite and positive')
        if mmio is None:
            from pynq import Overlay
            bitfile = Path(bitfile).resolve()
            if not bitfile.is_file() or not bitfile.with_suffix('.hwh').is_file():
                raise ValueError('同目录提供实际 CLG400 板卡自行综合的 bit 和同名 hwh')
            registers = json.loads(bitfile.with_suffix('.registers.json').read_text(encoding='utf-8'))
            required_bytes = validate_registers(registers, require_identity=True)
            self.overlay = Overlay(str(bitfile), download=False)
            if ip_name not in self.overlay.ip_dict:
                raise ValueError('overlay 中找不到 IP '+ip_name+'；可用 IP：'+', '.join(self.overlay.ip_dict))
            validate_ip(self.overlay.ip_dict[ip_name], required_bytes)
            self.overlay.download()
            mmio = getattr(self.overlay, ip_name).mmio
        self.mmio, self.registers, self.timeout_s = mmio, registers, timeout_s
        self.calls = 0; self.total_s = 0.; self.faulted = False
        self.write_s = 0.; self.wait_s = 0.; self.read_s = 0.
        required_bytes = validate_registers(registers)
        array = getattr(mmio, 'array', None)
        self.array = array if (isinstance(array, np.ndarray) and array.ndim == 1 and
            array.dtype == np.dtype('uint32') and array.flags.c_contiguous and
            array.flags.writeable and array.size*4 >= required_bytes) else None

    def write_words(self, field, words):
        offset = self.registers[field]
        if self.array is not None:
            self.array[offset//4:offset//4+len(words)] = words
        else:
            for index, word in enumerate(words):
                self.mmio.write(offset+4*index, int(word))

    def read_words(self, field, count):
        offset = self.registers[field]
        if self.array is not None:
            return self.array[offset//4:offset//4+count].copy()
        return np.array([self.mmio.read(offset+4*i) for i in range(count)], dtype=np.uint32)

    def metrics(self):
        return dict(calls=self.calls, total_s=self.total_s, write_s=self.write_s,
                    wait_s=self.wait_s, read_s=self.read_s,
                    transport='mapped_array' if self.array is not None else 'register_calls')

    def __call__(self, j, e, w, s, mu, mode='wls'):
        import planning  # ensures the bundled planner is on sys.path
        from r1a.native import quantized
        arrays, damping = quantized(j,e,w,s,mu,mode)
        if self.faulted:
            raise FloatingPointError('PL 已超时，请重启服务重新加载 overlay')
        # Consume stale done before start (AP_DONE is clear-on-read).
        self.mmio.read(0)
        started = time.monotonic()
        for field, values in zip(('j','e','w','scales'), arrays):
            self.write_words(field, values.reshape(-1).view(np.uint32))
        self.mmio.write(self.registers['mu'], int(np.asarray(damping).view(np.uint32)))
        self.mmio.write(self.registers['mode'], 0 if mode == 'wls' else 1)
        self.mmio.write(0, 1)
        written = time.monotonic()
        deadline = written+self.timeout_s
        polls = 0
        while not self.mmio.read(0) & 2:
            if time.monotonic() >= deadline:
                self.faulted = True
                raise FloatingPointError('PL WLS timeout')
            # Fast cores usually finish during these bounded immediate polls.
            # Slow or faulted cores yield instead of monopolizing the A9 CPU.
            polls += 1
            if polls >= 32:
                time.sleep(.0001)
        completed = time.monotonic()
        status = self.mmio.read(self.registers['return'])
        words = self.read_words('dq', 5)
        ended = time.monotonic()
        self.calls += 1; self.total_s += ended-started
        self.write_s += written-started; self.wait_s += completed-written; self.read_s += ended-completed
        if status:
            raise FloatingPointError('PL WLS status=%d' % status)
        values = words.view(np.float32).astype(float)
        if not np.isfinite(values).all():
            raise FloatingPointError('PL 返回非有限值')
        return values
