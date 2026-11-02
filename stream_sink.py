"""AXI-Stream 像素推拉适配层（z20_pl_image 配套）。

设计目的：把 z20_pl_image 的 AXI-Stream 像素进出接口与具体硬件接线解耦。

- 默认实现（'loopback'）：软件回环，用预生成/回读的 numpy 帧模拟 OV7725
  像素流。目的是让 pl_image_backend、workbench 集成和测试在没有板载
  摄像头/DMA 时也能跑通数值与协议，验证逻辑正确。
- 真实接 OV7725 时，只需把 push_pixels_resync/pull_pixels_resync 替换为
  连接 PL 侧捕获模块的实现（见 docs/PL_IMAGE_OV7725.md 的替换说明）：
    * 输入方向：OV7725 → PL 捕获 RTL(YUV422 8bit) → AXI-Stream → z20_pl_image
                通常由捕获模块直接送流或经 DMA 从 DDR 发
    * 输出方向：z20_pl_image → AXI-Stream →（VDMA 写 DDR 或 PL 直接回读）
                默认为软件回环，直接返回 numpy 帧，交给调用方转 paths.json
"""
import numpy as np

_LOOPBACK = True
_LAST_PUSHED = None


def set_loopback(enabled: bool):
    """切换硬件对接模式。False 表示未来接入真实 DMA/捕获模块。"""
    global _LOOPBACK
    _LOOPBACK = bool(enabled)


def loopback_frame(width, height, fill=20):
    """构造一帧供软件回环使用：背景灰度 fill（默认暗），可选 fill=200 模拟亮块。"""
    return np.full((height, width), int(fill), dtype=np.uint32)


def push_pixels_resync(backend, pixel_fn, total):
    """把一帧像素送入 z20_pl_image 的 pixels_in。

    backend:  PlImageBackend 实例（用于记录指标/超时）
    pixel_fn: 返回 np.ndarray[uint32]（形状任意，total 个元素）的回调
    total:    像素总数
    """
    global _LAST_PUSHED
    if _LOOPBACK:
        frame = pixel_fn() if callable(pixel_fn) else np.asarray(pixel_fn)
        frame = np.asarray(frame, dtype=np.uint32).reshape(-1)
        if frame.size != total:
            raise ValueError('输入帧像素数不符: %d != %d' % (frame.size, total))
        _LAST_PUSHED = frame
        return
    raise NotImplementedError(
        '真实 AXI-Stream 推流未实现；接入 OV7725 捕获后替换此处。 '
        'docs/PL_IMAGE_OV7725.md 见替换说明')


def pull_pixels_resync(backend, total, width, height):
    """从 z20_pl_image 的 pixels_out 读回一帧（二值轮廓）。

    返回 np.ndarray[uint32], shape (height,width), 白=0x00FFFFFF 黑=0xFF000000
    """
    global _LAST_PUSHED
    if _LOOPBACK:
        if _LAST_PUSHED is None:
            raise RuntimeError('回环模式需要先 push 一帧')
        g = _LAST_PUSHED.astype(np.int64).reshape(-1)
        # 模拟 Sobel 的简化近似：一阶差分幅度 > 阈值 记为边缘
        mag = np.abs(np.diff(g))
        frame = np.full(g.size, 0xFF000000, dtype=np.uint32)
        frame[1:][mag > 48] = 0x00FFFFFF
        return frame[:total].reshape(height, width)
    raise NotImplementedError(
        '真实 AXI-Stream 回读未实现；接入 VDMA/DMA 后替换此处。 '
        'docs/PL_IMAGE_OV7725.md 见替换说明')