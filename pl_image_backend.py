"""PYNQ adapter for the z20_pl_image streaming image-pipeline core.

独立旁路：与规划/运动链路完全隔离。此后端只负责
  1) 加载包含 z20_pl_image 的 overlay（bit/hwh/registers.json 三件套）
  2) 配置 width/height/mode/sobel_thr
  3) 把 OV7725 采集的 YUV422 像素流写入 pixels_in（AXI-Stream）
  4) 从 pixels_out 读回二值轮廓帧，返回给调用方

不会打开舵机、不会碰 planning/motion。原方案（云端链路）不加载此
overlay 时行为完全不变。寄存器地址必须来自本核 HLS 生成的头文件
（scripts/export_image_register_map.py 导出），不猜测偏移。
"""
import json
from pathlib import Path
import time
import numpy as np

from pl_image_contract import ABI, TOP, validate_registers


def validate_ip(description, required_bytes):
    vlnv = str(description.get('type', '')).split(':')
    if len(vlnv) != 4 or vlnv[2] != TOP:
        raise ValueError('软件要求 z20_pl_image，hwh 中实际为 ' + str(description.get('type')))
    size = description.get('addr_range')
    if type(size) is not int or size < required_bytes:
        raise ValueError('hwh 的 AXI 地址窗口不足以容纳此寄存器映射')


class PlImageBackend:
    name = 'PL_z20_pl_image'

    def __init__(self, bitfile=None, ip_name='z20_pl_image_0', mmio=None,
                 registers=None, timeout_s=2.0):
        if not np.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError('PL timeout must be finite and positive')
        self.timeout_s = float(timeout_s)
        if mmio is None:
            from pynq import Overlay
            bitfile = Path(bitfile).resolve()
            if not bitfile.is_file() or not bitfile.with_suffix('.hwh').is_file():
                raise ValueError('同目录提供实际 CLG400 板卡自行综合的 bit 和同名 hwh')
            registers = json.loads(bitfile.with_suffix('.registers.json').read_text(encoding='utf-8'))
            required_bytes = validate_registers(registers, require_identity=True)
            self.overlay = Overlay(str(bitfile), download=False)
            if ip_name not in self.overlay.ip_dict:
                raise ValueError('overlay 中找不到 IP ' + ip_name + '；可用 IP：' + ', '.join(self.overlay.ip_dict))
            validate_ip(self.overlay.ip_dict[ip_name], required_bytes)
            self.overlay.download()
            mmio = getattr(self.overlay, ip_name).mmio
        self.mmio = mmio
        self.registers = registers
        required_bytes = validate_registers(registers)
        array = getattr(mmio, 'array', None)
        self.array = array if (isinstance(array, np.ndarray) and array.ndim == 1 and
                               array.dtype == np.dtype('uint32') and array.flags.c_contiguous and
                               array.flags.writeable and array.size*4 >= required_bytes) else None
        self.calls = 0
        self.total_s = 0.

    # ---- 低层读写（对齐 pl_backend.PynqStep 风格） ----
    def write_word(self, field, value):
        offset = self.registers[field]
        if self.array is not None:
            self.array[offset // 4] = int(value)
        else:
            self.mmio.write(offset, int(value))

    def read_word(self, field):
        offset = self.registers[field]
        if self.array is not None:
            return int(self.array[offset // 4])
        return self.mmio.read(offset)

    def metrics(self):
        return dict(calls=self.calls, total_s=self.total_s,
                    transport='mapped_array' if self.array is not None else 'register_calls')

    # ---- 配置 ----
    def configure(self, width, height, mode=2, sobel_thr=48):
        if not (1 <= int(width) <= 1280 and 1 <= int(height) <= 960):
            raise ValueError('图像尺寸超限：宽<=1280 高<=960')
        if mode not in (0, 1, 2):
            raise ValueError('mode 只能为 0(透传)/1(灰度)/2(Sobel+二值)')
        if not (0 <= int(sobel_thr) <= 255):
            raise ValueError('sobel_thr 需在 0..255')
        self.width, self.height = int(width), int(height)
        self.mode, self.sobel_thr = int(mode), int(sobel_thr)
        return dict(configured=True, width=self.width, height=self.height,
                    mode=self.mode, sobel_thr=self.sobel_thr, abi=ABI)

    # ---- 单帧处理：pixel_fn 提供一帧 YUV422 像素（每元素 Y 在低8位） ----
    def process_frame(self, pixel_fn, width=None, height=None, mode=None, sobel_thr=None):
        if width is not None or height is not None or mode is not None or sobel_thr is not None:
            w = width if width is not None else (self.width if hasattr(self, 'width') else 0)
            h = height if height is not None else (self.height if hasattr(self, 'height') else 0)
            m = mode if mode is not None else (self.mode if hasattr(self, 'mode') else 2)
            t = sobel_thr if sobel_thr is not None else (self.sobel_thr if hasattr(self, 'sobel_thr') else 48)
            self.configure(w, h, m, t)
        w = self.width
        h = self.height
        total = w * h

        started = time.monotonic()
        # 写控制寄存器（先命令后数据，ap_ctrl 自动握手）
        self.write_word('width', w)
        self.write_word('height', h)
        self.write_word('mode', self.mode)
        self.write_word('sobel_thr', self.sobel_thr)

        # 写像素流：实际使用中由 DMA/自定义采集模块把 OV7725 数据导入
        # pixels_in。这里 pixel_fn 以回调形式提供 NumPy uint32 数组，
        # 通过 ps→pl 的 AXI-Stream（含 axis 驱动）送入核。
        from stream_sink import push_pixels_resync
        push_pixels_resync(self, pixel_fn, total)

        # 等待完成：轮询 edge_count 不再变化或 ap_done
        deadline = time.monotonic() + self.timeout_s
        last = None
        while True:
            try:
                edge = self.read_word('edge_count')
            except Exception:
                edge = None
            if edge is not None and edge == last and edge is not None:
                # 连续两次读数一致 → 帧完成（ap_done 也可轮询 0x00 & 0x2）
                break
            last = edge
            if time.monotonic() >= deadline:
                raise RuntimeError('PL image timeout：帧未在 %gs 内完成' % self.timeout_s)
            time.sleep(.0005)

        self.calls += 1
        self.total_s += time.monotonic() - started
        return dict(width=w, height=h, edge_count=int(last or 0), mode=self.mode)

    # ---- 从 pixels_out 读回一帧二值轮廓（配合 stream_sink 读取器） ----
    def read_out_frame(self, width=None, height=None):
        w = width if width is not None else self.width
        h = height if height is not None else self.height
        from stream_sink import pull_pixels_resync
        return pull_pixels_resync(self, w * h, w, h)