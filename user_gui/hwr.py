"""手写识字 (2026-10-28): a character written on the touchscreen -> one of the 3755 GB2312
level-1 characters, on the board's ARM CPU (OpenCV dnn; no FPGA, no network, no robot).

Model: Ismantic/Handwritten v0.1.1 MobileNetV2 (Apache-2.0, CASIA-HWDB1.1, top-1 95.47 % on
pen-on-paper samples), exported from best.pt to ONNX opset 9 for OpenCV 4.2. On the board it
matched PyTorch on 300/300 samples at about 0.18 s per character.

The strokes are drawn as a pen line on white paper and normalized exactly as in training
(normalize.py of the model: bounding box, long side 56, centred on 64 x 64, inverted / 255).
"""
import hashlib
import json
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

MODEL_DIR = Path(__file__).resolve().parents[1] / 'data/hwr'
MODEL_SHA256 = '338aff9cf3125a9c9f7a81cd5a9ede3a9dc7be3772f3597ffb4e7398b4e3071f'
CHARSET_SHA256 = '31f5700027c8692122cec5281d12c6382506b36d56075331cd73718f624d4ed2'
CANVAS = 256            # strokes are drawn at this size, then normalized to 64 x 64
LINE = 0.045            # pen width, as a fraction of the written character's long side
MAX_STROKES, MAX_POINTS = 64, 4000
THREADS = 2             # 2 of the 2 A9 cores: 0.18 s; the arm executor runs in another process
TOP_K = 6

# Training preprocessing (normalize.py of the model release), kept identical.
_SIZE, _CONTENT, _FG = 64, 56, 220


def normalize(bitmap):
    """White-background uint8 bitmap -> 64 x 64 uint8, character centred, long side 56."""
    fg = bitmap < _FG
    if not fg.any():
        return np.full((_SIZE, _SIZE), 255, dtype=np.uint8)
    ys, xs = np.where(fg)
    cropped = bitmap[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = cropped.shape
    scale = _CONTENT / max(h, w)
    nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
    resized = np.asarray(Image.fromarray(cropped, mode='L').resize((nw, nh), Image.BILINEAR), dtype=np.uint8)
    canvas = np.full((_SIZE, _SIZE), 255, dtype=np.uint8)
    oy, ox = (_SIZE - nh) // 2, (_SIZE - nw) // 2
    canvas[oy:oy + nh, ox:ox + nw] = resized
    return canvas


def check_strokes(strokes):
    """[[x, y], ...] per stroke, coordinates 0..1 of the writing box."""
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= MAX_STROKES:
        raise ValueError('请先写一个字（最多 %d 笔）' % MAX_STROKES)
    out, total = [], 0
    for s in strokes:
        if not isinstance(s, list) or not s:
            raise ValueError('笔画数据无效')
        pts = []
        for p in s:
            if (not isinstance(p, (list, tuple)) or len(p) != 2 or
                    not all(type(v) in (int, float) and 0 <= v <= 1 for v in p)):
                raise ValueError('笔画数据无效')
            pts.append((float(p[0]), float(p[1])))
        total += len(pts)
        out.append(pts)
    if total > MAX_POINTS:
        raise ValueError('笔画点太多')
    return out


def _smooth(pts):
    """Light 3-point moving average against finger jitter; ends stay where they were."""
    if len(pts) < 3:
        return pts
    a = np.asarray(pts)
    mid = (a[:-2] + a[1:-1] + a[2:]) / 3
    return [tuple(a[0])] + [tuple(p) for p in mid] + [tuple(a[-1])]


def render(strokes):
    """Strokes as a pen line on white paper (uint8, 255 = paper)."""
    pts = np.asarray([p for s in strokes for p in s])
    lo, hi = pts.min(0), pts.max(0)
    side = float(max(hi - lo)) or 1.0
    # Fit the character (not the box) into the canvas, so small writing gets the same line.
    scale = (CANVAS * 0.8) / side
    off = (CANVAS - (hi - lo) * scale) / 2 - lo * scale
    width = max(2, int(round(LINE * CANVAS * 0.8)))
    img = Image.new('L', (CANVAS, CANVAS), 255)
    draw = ImageDraw.Draw(img)
    for s in strokes:
        xy = [tuple(np.asarray(p) * scale + off) for p in _smooth(s)]
        if len(xy) == 1:
            x, y = xy[0]; r = width / 2
            draw.ellipse([x - r, y - r, x + r, y + r], fill=0)
            continue
        draw.line(xy, fill=0, width=width)
        for x, y in (xy[0], xy[-1]) + tuple(xy[1:-1]):     # round joins and caps
            r = width / 2
            draw.ellipse([x - r, y - r, x + r, y + r], fill=0)
    return np.asarray(img, dtype=np.uint8)


def to_input(strokes):
    return ((255 - normalize(render(strokes))).astype(np.float32) / 255.0)[None, None, :, :]


class Recognizer:
    """Loads the model once (about 0.4 s, 50 MB) and recognizes one character at a time."""

    def __init__(self, model_dir=MODEL_DIR):
        self.dir = Path(model_dir); self.lock = threading.Lock(); self.net = None; self.chars = None

    def _load(self):
        import cv2
        model, charset = self.dir / 'hccr_mbv2.onnx', self.dir / 'charset.json'
        if not model.is_file() or not charset.is_file():
            raise ValueError('未安装手写识字模型')
        for path, want in ((model, MODEL_SHA256), (charset, CHARSET_SHA256)):
            if hashlib.sha256(path.read_bytes()).hexdigest() != want:
                raise ValueError('手写识字模型文件校验失败：%s' % path.name)
        data = json.loads(charset.read_text(encoding='utf-8'))
        chars = [''] * data['num_classes']
        for ch, i in data['char_to_idx'].items():
            chars[int(i)] = ch
        cv2.setNumThreads(THREADS)
        # OpenCV's Windows filename loader can reject non-ASCII project paths.
        # Loading verified bytes also works with the board's OpenCV 4.2 API.
        net = cv2.dnn.readNetFromONNX(np.frombuffer(model.read_bytes(), dtype=np.uint8))
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self.net, self.chars = net, chars

    def warm(self):
        """Load in the background at server start, so the first character is not slower."""
        def run():
            try:
                with self.lock:
                    if self.net is None:
                        self._load()
            except Exception:  # noqa: BLE001 - reported again on the first request
                pass
        threading.Thread(target=run, name='hwr-warm', daemon=True).start()

    def recognize(self, strokes, k=TOP_K):
        return self._run(to_input(check_strokes(strokes)), k)

    def recognize_image(self, bitmap, k=TOP_K):
        """A character image (uint8, 255 = paper), e.g. one camera box of 字迹识别 (2026-10-28)."""
        bitmap = np.asarray(bitmap, dtype=np.uint8)
        if bitmap.ndim != 2 or not (bitmap < _FG).any():
            raise ValueError('没有找到笔画')
        return self._run(((255 - normalize(bitmap)).astype(np.float32) / 255.0)[None, None, :, :], k)

    def _run(self, x, k):
        with self.lock:
            if self.net is None:
                self._load()
            t = time.perf_counter()
            self.net.setInput(x)
            logits = self.net.forward().reshape(-1).astype(np.float64)
            ms = (time.perf_counter() - t) * 1000
            chars = self.chars
        p = np.exp(logits - logits.max()); p /= p.sum()
        order = np.argsort(-p)[:k]
        return dict(candidates=[dict(char=chars[int(i)], p=round(float(p[i]), 4)) for i in order],
                    ms=round(ms, 1), classes=len(chars))
