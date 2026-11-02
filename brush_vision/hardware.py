"""Platform contract and attach-only driver for tcb_brush_recog_0.

The FPGA is loaded once per boot by scripts/load_platform.py; this module only
attaches to the verified platform.  DMA buffers (frame, binary, page, results,
templates) are allocated once on first use and reused under a lock.
"""
import hashlib
import json
import re
import threading
import time
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from . import contract as c, model as m

FIELDS = {'mode': 1, 'params': 2, 'src': 2, 'dst': 2, 'tpl': 2, 'identity': 1, 'return': 1}
REGISTERS_NAME = 'tcb_brush_recog.registers.json'


# ----------------------------------------------------------------- contract
def validate_registers(registers):
    if registers.get('abi') != c.RECOG_ABI or registers.get('top') != c.RECOG_TOP:
        raise ValueError('brush recogniser register identity mismatch')
    occupied = {0, 4, 8, 12}
    for field, words in FIELDS.items():
        offset = registers.get(field)
        if type(offset) is not int or offset < 16 or offset % 4:
            raise ValueError('invalid recogniser register ' + field)
        slots = set(range(offset, offset + 4 * words, 4))
        if slots & occupied:
            raise ValueError('overlapping recogniser registers')
        occupied |= slots
    return registers


def extract_registers(header):
    header = Path(header)
    defs = dict(re.findall(r'^\s*#define\s+(\w+)\s+(0x[0-9a-fA-F]+|\d+)\b', header.read_text(), re.M))
    out = dict(abi=c.RECOG_ABI, top=c.RECOG_TOP, header_sha256=hashlib.sha256(header.read_bytes()).hexdigest())
    prefix = 'XTCB_BRUSH_RECOG_CONTROL_'
    for field, words in FIELDS.items():
        suffix = 'AP_RETURN' if field == 'return' else field.upper() + '_DATA'
        name = prefix + 'ADDR_' + suffix
        if name not in defs:
            raise ValueError('missing register ' + name)
        out[field] = int(defs[name], 0)
        if int(defs.get(prefix + 'BITS_' + suffix, '0'), 0) != words * 32:
            raise ValueError('incorrect width ' + field)
    return validate_registers(out)


def validate_hwh(path):
    tree = ET.parse(str(path))
    modules = [mm for mm in tree.iter('MODULE') if mm.get('INSTANCE') == c.RECOG_IP]
    if len(modules) != 1 or modules[0].get('MODTYPE') != c.RECOG_TOP:
        raise ValueError(c.RECOG_IP + ' missing or ambiguous in HWH')
    ranges = {(int(r.get('BASEVALUE'), 0), int(r.get('HIGHVALUE'), 0))
              for r in tree.iter('MEMRANGE') if r.get('INSTANCE') == c.RECOG_IP}
    if ranges != {(c.RECOG_BASE, c.RECOG_BASE + c.RECOG_SIZE - 1)}:
        raise ValueError('recogniser address differs from 0x%08x/64K' % c.RECOG_BASE)
    clocks = modules[0].findall('./PORTS/PORT[@NAME="ap_clk"]')
    if len(clocks) != 1 or int(clocks[0].get('CLKFREQUENCY', '0')) != 100000000:
        raise ValueError('brush recogniser requires FCLK0 100 MHz')
    ps = [mm for mm in tree.iter('MODULE') if mm.get('INSTANCE') == 'processing_system7_0']
    params = {p.get('NAME'): p.get('VALUE') for p in ps[0].findall('./PARAMETERS/PARAMETER')} if len(ps) == 1 else {}
    if params.get('C_USE_S_AXI_HP2') != '1':
        raise ValueError('HP2 is not enabled for the recogniser')
    return dict(abi=c.RECOG_ABI, ip_name=c.RECOG_IP, base=c.RECOG_BASE, size=c.RECOG_SIZE, clock_hz=100000000,
                camera='usb-uvc-yuyv-640x480')


def validate_manifest_section(cfg, folder, bit):
    entry = cfg.get('vision')
    if entry is None:
        return None
    expected = validate_hwh(Path(bit).with_suffix('.hwh'))
    if entry != {**expected, 'registers': REGISTERS_NAME}:
        raise ValueError('vision manifest/HWH mismatch')
    if REGISTERS_NAME not in cfg['files']:
        raise ValueError('vision registers are not sealed')
    registers = json.loads((Path(folder) / REGISTERS_NAME).read_text(encoding='utf-8'))
    return entry, validate_registers(registers)


# ----------------------------------------------------------------- PL driver
class VisionPL:
    """DMA access to the recogniser.  All public methods serialise on self.lock."""
    backend = 'PL'

    def __init__(self, mmio, registers, allocator, timeout_s=3.0):
        self.rec, self.regs = mmio, validate_registers(registers)
        self.allocate = allocator
        self.timeout_s = float(timeout_s)
        self.lock = threading.RLock()
        self.buffers = None
        self.tpls = {}           # template set name -> (CMA buffer, template count)
        self.poisoned = False

    def _ensure_buffers(self):
        if self.buffers is None:
            try:
                self.buffers = dict(
                    params=self.allocate(shape=(c.PARAM_WORDS,), dtype=np.uint64),
                    yuyv=self.allocate(shape=(c.YUYV_WORDS,), dtype=np.uint64),
                    binary=self.allocate(shape=(c.FRAME_WORDS + 2,), dtype=np.uint64),
                    rect=self.allocate(shape=(2048,), dtype=np.uint64),
                    results=self.allocate(shape=(m.MAX_BOXES * c.RESULT_WORDS,), dtype=np.uint64))
            except Exception as exc:
                raise RuntimeError('连续内存(CMA)不足，无法分配识别缓冲区：%s' % exc)
        return self.buffers

    def identity(self):
        with self.lock:
            b = self._ensure_buffers()
            self._run(0, b['params'], b['params'], None)
            return int(self.rec.read(self.regs['identity']))

    def load_templates(self, blob_u64, count, name='default', **_):
        """One template set per name (a calligraphy style, or the small scoring set)."""
        words = np.asarray(blob_u64, dtype=np.uint64)
        with self.lock:
            old = self.tpls.get(name)
            if old is not None and len(old[0]) == len(words):
                buf = old[0]                     # same size: overwrite in place
            else:
                if old is not None:
                    old[0].freebuffer()
                try:
                    buf = self.allocate(shape=(len(words),), dtype=np.uint64)
                except Exception as exc:
                    raise RuntimeError('连续内存(CMA)不足，无法加载模板 %s：%s' % (name, exc))
            buf[:] = words
            buf.flush()
            self.tpls[name] = (buf, int(count))

    def _addr(self, name, buf):
        a = int(buf.physical_address)
        if a % 8 or a + buf.nbytes > 2 ** 32:
            raise ValueError('invalid CMA address')
        self.rec.write(self.regs[name], a)
        self.rec.write(self.regs[name] + 4, 0)

    def _run(self, mode, src, dst, tpl):
        if self.poisoned:
            raise RuntimeError('识别核曾经超时，请重启板子后再使用')
        if not self.rec.read(0) & 4:
            raise RuntimeError('识别核忙')
        b = self.buffers
        b['params'].flush()
        src.flush()
        dst.flush()
        self.rec.write(self.regs['mode'], mode)
        self._addr('params', b['params']); self._addr('src', src); self._addr('dst', dst)
        self._addr('tpl', tpl if tpl is not None else b['params'])
        started = time.perf_counter()
        self.rec.write(0, 1)
        deadline = time.monotonic() + self.timeout_s
        while not self.rec.read(0) & 2:
            if time.monotonic() > deadline:
                self.poisoned = True
                raise TimeoutError('识别核 DMA 超时')
            time.sleep(0.0002)
        elapsed = time.perf_counter() - started
        if int(self.rec.read(self.regs['identity'])) != c.RECOG_ID:
            raise RuntimeError('识别核身份不符')
        rc = int(self.rec.read(self.regs['return']))
        if rc:
            raise RuntimeError('识别核拒绝参数 (返回 %d)' % rc)
        dst.invalidate()
        return elapsed

    def preprocess(self, yuyv_bytes, roi, otsu=True, manual=100, bias=0, ops=m.DEFAULT_OPS):
        """Mode 3: returns (binary 480x640, packed u32 words, stats, seconds)."""
        with self.lock:
            b = self._ensure_buffers()
            b['params'][:] = c.preprocess_params(roi, otsu, manual, bias, ops)
            b['yuyv'][:] = np.frombuffer(np.ascontiguousarray(yuyv_bytes, dtype=np.uint8).tobytes(), dtype='<u8')
            seconds = self._run(c.MODE_PREPROCESS, b['yuyv'], b['binary'], None)
            out = np.array(b['binary'])
        words = out[:c.FRAME_WORDS].view('<u4')
        return m.unpack_frame(words), words, c.parse_preprocess_stats(out[c.STATS_WORD:c.STATS_WORD + 2]), seconds

    def rectify(self, frame_words_u32, hq, size):
        with self.lock:
            b = self._ensure_buffers()
            b['params'][:] = c.rectify_params(hq, size)
            b['binary'][:c.FRAME_WORDS] = c.frame_u64(frame_words_u32)
            seconds = self._run(c.MODE_RECTIFY, b['binary'], b['rect'], None)
            out = np.array(b['rect'])
        col, row = c.unpack_proj(out, size)
        return c.unpack_rect(out, size), out, col, row, seconds

    def recognise(self, rect_words, size, boxes, expected=None, candidates=None, style='default'):
        if style not in self.tpls:
            raise RuntimeError('模板未加载：' + style)
        tpl, n_tpl = self.tpls[style]
        with self.lock:
            b = self._ensure_buffers()
            b['params'][:] = c.recognise_params(size, boxes, n_tpl, expected, candidates)
            words = np.asarray(rect_words, dtype=np.uint64)
            b['rect'][:] = 0
            b['rect'][:len(words)] = words      # PL output (2048) or ARM-repacked page (1600)
            seconds = self._run(c.MODE_RECOGNISE, b['rect'], b['results'], tpl)
            out = np.array(b['results'][:len(boxes) * c.RESULT_WORDS])
        return [c.parse_result(out[i * c.RESULT_WORDS:(i + 1) * c.RESULT_WORDS]) for i in range(len(boxes))], seconds


class SoftwareVision:
    """Same interface computed with the bit-exact model (PC demo / platform without the core)."""
    backend = 'CPU'

    def __init__(self):
        self.lock = threading.RLock()
        self.sets = {}

    def load_templates(self, blob_u64, count, name='default', feats=None, bitmaps=None):
        if feats is None:
            raw = np.asarray(blob_u64, dtype='<u8').view(np.uint8)
            feats = raw[:count * m.FEATURES].reshape(count, m.FEATURES)
            bitmaps = raw[count * m.FEATURES:].reshape(-1, 512)
        self.sets[name] = (feats, bitmaps)

    def preprocess(self, yuyv_bytes, roi, otsu=True, manual=100, bias=0, ops=m.DEFAULT_OPS):
        t = time.perf_counter()
        binary, stats = m.preprocess(m.yuyv_gray(yuyv_bytes), roi, otsu, manual, bias, ops)
        return binary, m.pack_frame(binary), stats, time.perf_counter() - t

    def rectify(self, frame_words_u32, hq, size):
        t = time.perf_counter()
        rect = m.rectify(m.unpack_frame(frame_words_u32), hq, size)
        col, row = m.projections(rect)
        return rect, c.pack_rect(rect), col, row, time.perf_counter() - t

    def recognise(self, rect_words, size, boxes, expected=None, candidates=None, style='default'):
        t = time.perf_counter()
        rect = c.unpack_rect(rect_words, size)
        feats, bitmaps = self.sets[style]
        out = []
        for i, b in enumerate(boxes):
            r = m.recognise_box(rect, size, b, feats, bitmaps, -1 if expected is None else expected[i], candidates)
            out.append(c.parse_result(c.result_words(r)))
        return out, time.perf_counter() - t


def open_platform():
    """Attach to the booted platform that carries a sealed vision section."""
    from tcb705.accel_runtime import platform_manifest, attached_identity, ps_ddr_allocator, ensure_event_loop
    ensure_event_loop()
    manifest = platform_manifest()
    if manifest is None:
        raise ValueError('没有配置 FPGA 平台')
    cfg, _, _, _, _ = attached_identity()
    bit = manifest.parent / cfg['bitfile']
    section = validate_manifest_section(cfg, manifest.parent, bit)
    if section is None:
        raise ValueError('当前 FPGA 平台不含字迹识别核（需要 tcb705_vision 平台）')
    entry, registers = section
    from pynq import MMIO, Overlay
    overlay = Overlay(str(bit), download=False)
    return VisionPL(MMIO(entry['base'], entry['size']), registers, ps_ddr_allocator(overlay))
