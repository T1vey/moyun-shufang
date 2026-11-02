"""PYNQ full task-step adapter. Geometry, tool and ABI are checked explicitly."""
import json
from pathlib import Path
import time
import numpy as np
from ik_contract import MAGIC, model_matches_nominal, validate_ip, validate_registers


class PynqIKStep:
    name = "PL_z20_ik_step"

    def __init__(self, bitfile=None, ip_name="z20_ik_step_0", mmio=None,
                 registers=None, timeout_s=.5):
        if not np.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout must be positive")
        if mmio is None:
            from pynq import Overlay
            bitfile = Path(bitfile).resolve()
            if not bitfile.is_file() or not bitfile.with_suffix('.hwh').is_file():
                raise ValueError("提供实际 CLG400 板卡 bit/hwh")
            registers = json.loads(bitfile.with_suffix('.registers.json').read_text(encoding='utf-8'))
            required = validate_registers(registers, True)
            self.overlay = Overlay(str(bitfile), download=False)
            validate_ip(self.overlay.ip_dict.get(ip_name, {}), required)
            self.overlay.download()
            mmio = getattr(self.overlay, ip_name).mmio
        required = validate_registers(registers)
        self.mmio, self.registers, self.timeout_s = mmio, dict(registers), timeout_s
        array = getattr(mmio, 'array', None)
        self.array = array if (isinstance(array, np.ndarray) and array.ndim == 1
            and array.dtype == np.dtype('uint32') and array.flags.c_contiguous
            and array.flags.writeable and array.nbytes >= required) else None
        self.calls = self.input_words = self.output_words = 0
        self.total_s = self.write_s = self.wait_s = self.read_s = 0.
        self.faulted = False
        self.model = None
        self._cache = {}

    def validate_model(self, model):
        valid = model_matches_nominal(model)
        self.model = model if valid else None
        return valid

    def _write(self, field, values, integer=False, cache=False):
        words = np.ascontiguousarray(values, dtype=np.uint32 if integer else np.float32).reshape(-1)
        if not integer:
            words = words.view(np.uint32)
        data = words.tobytes()
        if cache and self._cache.get(field) == data:
            return
        start = self.registers[field]//4
        if self.array is not None:
            self.array[start:start+len(words)] = words
        else:
            for i, word in enumerate(words):
                self.mmio.write(4*(start+i), int(word))
        self.input_words += len(words)
        if cache:
            self._cache[field] = data

    def _read(self, field, count):
        offset = self.registers[field]
        self.output_words += count
        if self.array is not None:
            return self.array[offset//4:offset//4+count].copy().view(np.float32).astype(float)
        return np.array([self.mmio.read(offset+4*i) for i in range(count)], np.uint32).view(np.float32).astype(float)

    def solve_task(self, position, axis, q, weights, scales, mu, max_step=.12, mode='wls'):
        if self.model is None:
            raise ValueError('先绑定匹配的 SO-101 模型')
        if self.faulted:
            raise FloatingPointError('PL 已故障，请重载 overlay')
        arrays = [np.asarray(x, dtype=float) for x in (q,position,axis,weights,scales)]
        if [a.shape for a in arrays] != [(5,),(3,),(3,),(6,),(6,)] or any(not np.isfinite(a).all() for a in arrays):
            raise ValueError('invalid task-step arrays')
        if (mode not in ('wls','rhs_only') or not np.isfinite([mu,max_step]).all()
                or min(mu,max_step) <= 0 or np.any(arrays[3]<0) or np.any(arrays[4]<=0)
                or abs(np.linalg.norm(arrays[2])-1)>1e-8 or not self.model.legal(arrays[0])):
            raise ValueError('invalid task-step values')
        all_values = arrays + [self.model.tool,self.model.tool_axis,self.model.limits,
                              np.asarray([mu,max_step])]
        if any(np.max(np.abs(v)) > np.finfo(np.float32).max for v in all_values):
            raise ValueError('task-step exceeds float32 range')
        if np.float32(mu)<=0 or np.float32(max_step)<=0 or np.any(arrays[4].astype(np.float32)<=0):
            raise ValueError('task-step float32 underflow')
        started = time.monotonic()
        try:
            self.mmio.read(0)  # clear stale done
            for field, value in zip(('q','target_position','target_axis','weights','scales'),arrays):
                self._write(field,value,cache=field not in ('q','target_position'))
            for field, value in (('tool',self.model.tool),('tool_axis',self.model.tool_axis),
                                 ('limits',self.model.limits),('mu',[mu]),('max_step',[max_step])):
                self._write(field,value,cache=True)
            self._write('mode',[int(mode=='rhs_only')],integer=True,cache=True)
            self.mmio.write(0,1)
            written = time.monotonic()
            deadline = written+self.timeout_s
            polls = 0
            while not (self.mmio.read(0)&2):
                if time.monotonic()>=deadline:
                    raise FloatingPointError('PL IK timeout')
                polls += 1
                if polls>32:
                    time.sleep(.0001)
            completed = time.monotonic()
            status = int(self.mmio.read(self.registers['return']))
            magic = int(self.mmio.read(self.registers['abi_version']))
            self.output_words += 2
            if status or magic!=MAGIC:
                raise FloatingPointError('PL IK status=%d ABI=0x%08X' % (status,magic))
            out = dict(dq=self._read('dq',5),q_next=self._read('q_next',5),
                       error=self._read('error',6),position_error_m=float(self._read('position_error',1)[0]),
                       tilt_error_rad=float(self._read('tilt_error',1)[0]),status=status)
            if any(not np.isfinite(out[k]).all() for k in ('dq','q_next','error')) or not np.isfinite([out['position_error_m'],out['tilt_error_rad']]).all():
                raise FloatingPointError('PL IK returned nonfinite output')
            if (np.max(np.abs(out['dq']))>max_step+2e-6 or
                    not np.allclose(arrays[0]+out['dq'],out['q_next'],atol=2e-6,rtol=0) or
                    np.any(out['q_next'] < self.model.limits[:,0]-2e-6) or
                    np.any(out['q_next'] > self.model.limits[:,1]+2e-6)):
                raise FloatingPointError('PL IK step contract mismatch')
        except Exception:
            self.faulted = True
            self._cache.clear()
            raise
        ended = time.monotonic()
        self.calls += 1
        self.total_s += ended-started
        self.write_s += written-started
        self.wait_s += completed-written
        self.read_s += ended-completed
        return out

    def metrics(self):
        return dict(calls=self.calls,total_s=self.total_s,write_s=self.write_s,
                    wait_s=self.wait_s,read_s=self.read_s,input_words=self.input_words,
                    output_words=self.output_words,static_input_cache=True,
                    transport='mapped_array' if self.array is not None else 'register_calls',
                    kernel='z20_ik_step',abi='so101-ik-step-v2')
