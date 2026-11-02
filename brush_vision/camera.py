"""USB (UVC) camera reader: keeps the newest 640x480 frame as YUYV bytes.

The PL preprocessing reads YUYV and uses only the Y bytes, so cameras that only
offer MJPEG are decoded on the ARM and repacked with neutral chroma.
The capture thread starts on demand and stops after IDLE_S without requests.
"""
import threading
import time
import numpy as np
from . import model as m

IDLE_S = 60.0


class UsbCamera:
    def __init__(self, device=0, idle_s=IDLE_S):
        self.device = device
        self.idle_s = idle_s
        self.lock = threading.Lock()
        self.frame = None
        self.frame_time = 0.0
        self.frames = 0
        self.format = None
        self.error = None
        self.last_use = 0.0
        self.thread = None
        self.stop_flag = False

    def _open(self):
        import cv2
        cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise RuntimeError('打不开 USB 摄像头 /dev/video%s：检查是否插好' % self.device)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, m.W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, m.H)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YUYV'))
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        ok, f = cap.read()
        if ok and f is not None and f.size == m.W * m.H * 2:
            self.format = 'YUYV'
            return cap
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 1)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        ok, f = cap.read()
        if not ok or f is None:
            cap.release()
            raise RuntimeError('USB 摄像头没有输出画面')
        self.format = 'BGR%dx%d' % (f.shape[1], f.shape[0])
        return cap

    @staticmethod
    def _to_yuyv(f):
        import cv2
        if f.ndim == 3 and f.shape[2] == 2 and f.shape[:2] == (m.H, m.W):
            return np.ascontiguousarray(f).reshape(-1)
        if f.ndim == 2 and f.size == m.W * m.H * 2:
            return np.ascontiguousarray(f).reshape(-1)
        gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) if f.ndim == 3 else f
        if gray.shape != (m.H, m.W):
            gray = cv2.resize(gray, (m.W, m.H), interpolation=cv2.INTER_AREA)
        return m.gray_to_yuyv(gray)

    def _loop(self):
        cap = None
        try:
            cap = self._open()
            self.error = None
            while not self.stop_flag and time.monotonic() - self.last_use < self.idle_s:
                ok, f = cap.read()
                if not ok or f is None:
                    self.error = 'USB 摄像头读帧失败'
                    time.sleep(0.05)
                    continue
                yuyv = self._to_yuyv(f)
                with self.lock:
                    self.frame, self.frame_time = yuyv, time.monotonic()
                    self.frames += 1
        except Exception as exc:
            self.error = str(exc)
        finally:
            if cap is not None:
                cap.release()
            with self.lock:
                self.thread = None

    def _ensure(self):
        self.last_use = time.monotonic()
        with self.lock:
            if self.thread is None:
                self.stop_flag = False
                self.frame = None
                self.thread = threading.Thread(target=self._loop, name='usb-camera', daemon=True)
                self.thread.start()

    def latest(self, max_age=1.0, timeout=4.0):
        """Newest YUYV frame (614400 bytes) not older than max_age seconds."""
        self._ensure()
        deadline = time.monotonic() + timeout
        while True:
            with self.lock:
                if self.frame is not None and time.monotonic() - self.frame_time <= max_age:
                    return self.frame.copy()
                running = self.thread is not None
            if not running and self.error:
                raise RuntimeError(self.error)
            if time.monotonic() > deadline:
                raise RuntimeError(self.error or 'USB 摄像头超时没有新画面')
            time.sleep(0.02)

    def status(self):
        with self.lock:
            return dict(running=self.thread is not None, frames=self.frames, format=self.format,
                        error=self.error, age_s=None if self.frame is None else round(time.monotonic() - self.frame_time, 2))

    def close(self):
        self.stop_flag = True


class ImageCamera:
    """PC demo stand-in: serves one image file as the camera (BRUSH_VISION_IMAGE)."""

    def __init__(self, path):
        import cv2
        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise RuntimeError('读不到演示图片：%s' % path)
        self.frame = UsbCamera._to_yuyv(gray)
        self.frames = 0

    def latest(self, max_age=1.0, timeout=4.0):
        self.frames += 1
        return self.frame.copy()

    def status(self):
        return dict(running=True, frames=self.frames, format='IMAGE', error=None, age_s=0)

    def close(self):
        pass
