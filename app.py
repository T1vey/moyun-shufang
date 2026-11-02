"""Local ArmVision, trajectory planning and SO-101 hardware debug console."""
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import re
import secrets
import signal
import sys
import threading
from urllib.parse import urlsplit
import uuid
import zipfile

from protocol import DemoPort, probe

ROOT = Path(__file__).resolve().parent
VERSION = "1.10.5-sugar-fast"
SCENARIOS = ("normal", "missing", "checksum", "servo_error")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _frame_to_paths(frame, width_mm, height_mm, max_strokes=64):
    """把 z20_pl_image 输出的二值轮廓帧转成 vision.paths 风格的毫米路径。

    简化实现：按行游程提取连续白像素段作为笔画。正式接机械臂时可用
    vision.py 的 DXF/中心线流程替代；这里保证 /api/pl_image 的返回
    与规划器接受的 paths 结构一致（units/width_mm/height_mm/paths）。
    """
    import numpy as np
    frame = np.asarray(frame)
    h, w = frame.shape[:2]
    if frame.ndim == 3:
        white = frame[:, :, 0] == 0xFF
    else:
        white = frame == 0x00FFFFFF
    paths = []
    for y in range(h):
        row = white[y]
        x = 0
        while x < w:
            if row[x]:
                x0 = x
                while x < w and row[x]:
                    x += 1
                paths.append([[float(x0), float(y)], [float(x - 1), float(y)]])
            else:
                x += 1
        if len(paths) >= max_strokes:
            break
    return dict(units="mm", width_mm=float(width_mm), height_mm=float(height_mm),
                paths=paths[:max_strokes], strokes=len(paths[:max_strokes]),
                segments=len(paths[:max_strokes]), engine="pl_image")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_scan(data, allow_real):
    if not isinstance(data, dict) or set(data) - {"mode", "scenario", "port", "baudrate", "ids", "confirmed"}:
        raise ValueError("Invalid probe fields")
    mode = data.get("mode")
    if mode not in ("demo", "real"):
        raise ValueError("Select demo or real")
    ids = data.get("ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 6:
        raise ValueError("Provide 1..6 explicit servo IDs")
    if any(type(i) is not int or not 1 <= i <= 253 for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("IDs must be unique integers in 1..253")
    if data.get("scenario", "normal") not in SCENARIOS:
        raise ValueError("Invalid demo scenario")
    if mode == "real":
        if not allow_real or data.get("confirmed") is not True:
            raise ValueError("Real probing requires --allow-real and on-page confirmation")
        port = data.get("port", "")
        if not isinstance(port, str) or not re.fullmatch(r"COM[1-9][0-9]{0,3}|/dev/(?:ttyACM[0-9]+|ttyUSB[0-9]+|serial/by-id/[A-Za-z0-9_.:+-]+)", port):
            raise ValueError("Select a COM, ttyACM, ttyUSB or /dev/serial/by-id device")
        if type(data.get("baudrate")) is not int or data["baudrate"] not in (9600, 19200, 38400, 57600, 115200, 250000, 500000, 1000000):
            raise ValueError("Select the verified servo baud rate; this does not reconfigure servos")
    return ids


def open_real(port, baudrate):
    try:
        import serial
    except ImportError as exc:
        raise ValueError("Install pyserial in this Python environment (see requirements-pynq.txt)") from exc
    options = {"baudrate": baudrate, "timeout": 0.025, "write_timeout": 0.15,
               "xonxoff": False, "rtscts": False, "dsrdtr": False}
    if sys.platform != "win32":
        options["exclusive"] = True
    device = serial.Serial(port=None, **options)
    try:
        device.dtr = False
        device.rts = False
        device.port = port
        device.open()
        return device
    except Exception:
        device.close()
        raise


class State:
    def __init__(self, data_root, allow_real=False, real_factory=open_real):
        self.allow_real = allow_real
        self.real_factory = real_factory
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.record_lock = threading.RLock()
        self.started = utc_now()
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        self.directory = Path(data_root).resolve() / self.session_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.events = []
        self.scans = []
        self.record("START", {"allow_real": allow_real, "version": VERSION})

    def record(self, event, detail):
        item = {"time_utc": utc_now(), "event": event, "detail": detail}
        # Fail the operation if its audit entry cannot be written.
        with self.record_lock:
            with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")
            self.events.append(item)
            self.events = self.events[-100:]

    def scan(self, data):
        ids = validate_scan(data, self.allow_real)
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("BUSY: another probe or export is in progress")
        try:
            if len(self.scans) >= 100:
                raise ValueError("Session limit reached (100 probes); export and restart")
            self.record("PROBE_BEGIN", {k: data.get(k) for k in ("mode", "port", "baudrate", "ids", "scenario")})
            device = None
            result = {"scan_id": uuid.uuid4().hex, "time_utc": utc_now(), "mode": data["mode"],
                      "simulated": data["mode"] == "demo", "physical_authorized": False,
                      "motion_supported": False, "ids": ids, "rows": [], "error": None,
                      "port": data.get("port") if data["mode"] == "real" else None,
                      "baudrate": data.get("baudrate") if data["mode"] == "real" else None,
                      "scenario": data.get("scenario", "normal") if data["mode"] == "demo" else None}
            try:
                if result['simulated']:
                    device = (getattr(self, 'demo', None) or DemoPort()) if data.get('scenario', 'normal') == 'normal' else DemoPort(data['scenario'])
                else:
                    device = self.real_factory(data["port"], data["baudrate"])
                result["rows"] = probe(device, ids, 0.03 if result["simulated"] else 0.15)
            except (OSError, ValueError) as exc:
                result["error"] = str(exc)
            finally:
                if device is not None:
                    try:
                        device.close()
                    except OSError as exc:
                        result["error"] = "Port close failed: " + str(exc)
            good = len(result["rows"]) == len(ids) and all(r["read_ok"] for r in result["rows"]) and result["error"] is None
            result["status"] = ("DEMO_PASS" if result["simulated"] else "READONLY_PASS") if good else "FAIL"
            # Passing means only the explicitly listed IDs replied, not calibration.
            (self.directory / ("scan_" + result["scan_id"] + ".json")).write_bytes(json_bytes(result))
            self.record("PROBE_END", {"scan_id": result["scan_id"], "status": result["status"]})
            self.scans.append(result)
            return result
        finally:
            self.lock.release()

    def export(self):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("BUSY: wait for the probe to finish")
        try:
            content = {"session.json": json_bytes({"version": VERSION, "session_id": self.session_id,
                       "started_utc": self.started, "exported_utc": utc_now(), "scans": len(self.scans)}),
                       "events.jsonl": (self.directory / "events.jsonl").read_bytes()}
            for path in sorted(self.directory.rglob("*")):
                if path.is_file() and path.name != "upload.dat":
                    content[path.relative_to(self.directory).as_posix()] = path.read_bytes()
            manifest = {name: hashlib.sha256(value).hexdigest() for name, value in content.items()}
            content["SHA256.json"] = json_bytes(manifest)
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, value in content.items():
                    archive.writestr(name, value)
            return buffer.getvalue()
        finally:
            self.lock.release()


def vision_service(server):
    """Handwriting recognition (USB camera + PL); created on first use."""
    if getattr(server, '_vision', None) is None:
        from brush_vision.service import VisionService
        server._vision = VisionService(server.vision_data)
    return server._vision


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, state, allow_motion=False, board_url=None, cloud_config=None, backend=None, robot='so101', simulation=False, profile=None):
        self.state = state
        from workbench import Workbench
        if robot == 'tcb705':
            from tcb705.workbench import TCBWorkbench
            self.workbench = TCBWorkbench(state, simulation, profile)
        else:
            self.workbench = Workbench(state, allow_motion)
        self.robot = robot
        self.workbench.backend = backend
        from cloud import CloudJobs
        from remote import Board
        self.cloud = CloudJobs(state.directory, cloud_config)
        self.board = Board(board_url) if board_url else None
        super().__init__(address, Handler)
        if self.board and self.board.port == self.server_port:
            self.server_close()
            raise ValueError('电脑页面端口和板端 SSH 转发端口必须不同')
        self.origin = "http://127.0.0.1:%d" % self.server_port
        self.authority = "127.0.0.1:%d" % self.server_port


class Handler(BaseHTTPRequestHandler):
    server_version = "SO101Bringup/0.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, fmt, *args):
        pass  # Application audit is explicit; never log authentication headers.

    def send(self, code, content, kind="application/json; charset=utf-8", download=None):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; object-src 'none'; frame-ancestors 'none'")
        if download:
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % download)
        self.end_headers()
        self.wfile.write(content)

    def fail(self, code, message):
        self.send(code, json_bytes({"error": message}))

    def trusted(self, mutate=False):
        if self.headers.get("Host") != self.server.authority:
            self.fail(403, "Use " + self.server.origin)
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin != self.server.origin:
            self.fail(403, "Cross-origin request refused")
            return False
        if mutate and not secrets.compare_digest(self.headers.get("X-Console-Token", ""), self.server.state.token):
            self.fail(403, "Reload the console before probing")
            return False
        return True

    def do_GET(self):
        if not self.trusted():
            return
        path = urlsplit(self.path).path
        state = self.server.state
        if path == '/api/cloud':
            from cloud import load_config
            default_model = load_config(self.server.cloud.config_path)['model'] if self.server.cloud.config_path else None
            self.send(200, json_bytes(dict(configured=bool(self.server.cloud.config_path),
                      default_model=default_model, profiles=self.server.cloud.profiles(),
                      jobs=list(self.server.cloud.jobs.values())[-20:])))
            return
        if path.startswith('/cloud/'):
            parts = path.split('/')
            if len(parts) != 4 or parts[2] not in self.server.cloud.jobs or parts[3] not in ('input.png','lineart.png'):
                self.fail(404, 'Not found'); return
            target = self.server.cloud.root/parts[2]/parts[3]
            if not target.is_file():
                self.fail(404, 'Image not ready'); return
            self.send(200, target.read_bytes(), 'image/png'); return
        if path == '/api/pl_image':
            backend = getattr(self.server, 'pl_image', None)
            if backend is None:
                self.fail(404, '实时图像旁路未启用：板端启动时加 --pl-image <bit>')
                return
            self.send(200, json_bytes(dict(enabled=True, name=backend.name,
                      configured=getattr(backend, 'width', None) is not None,
                      metrics=backend.metrics())))
            return
        if self.server.board and (path.startswith('/api/') or path.startswith('/job/')):
            try:
                if path == '/api/status':
                    data = self.server.board.status()
                    data.update(token=state.token, gateway=True, cloud_configured=bool(self.server.cloud.config_path),
                                gateway_version=VERSION)
                    self.send(200, json_bytes(data))
                else:
                    code, raw, kind = self.server.board.request('GET', path)
                    self.send(code, raw, kind)
            except ValueError as exc:
                self.fail(502, str(exc))
            return
        if path in ('/api/vision/status', '/api/vision/preview', '/api/vision/result') and self.server.robot == 'tcb705':
            try:
                vision = vision_service(self.server)
                action = {'/api/vision/status': vision.status, '/api/vision/preview': vision.preview,
                          '/api/vision/result': vision.last_result}[path]
                self.send(200, json_bytes(action()))
            except (ValueError, RuntimeError, OSError) as exc:
                self.fail(409, str(exc))
            return
        if path == '/api/handwriting/status' and self.server.robot == 'tcb705':
            self.send(200,json_bytes(self.server.workbench.handwriting.snapshot()));return
        if path == "/api/status":
            if self.server.robot == 'tcb705':
                data=self.server.workbench.capabilities()
                data.update(token=state.token,session_id=state.session_id,events=state.events[-12:],cloud_configured=bool(self.server.cloud.config_path))
                self.send(200,json_bytes(data)); return
            from stroke_paths import PIPELINE_VERSION
            from pen_contact import VERSION as RELEASE_VERSION
            from cartesian_feedback import VERSION as NORMAL_FEEDBACK_VERSION
            from four_point_calibration import ready as four_point_ready
            from kinematic_calibration import assert_sugar_calibration
            sugar_ready, sugar_detail = False, ''
            sugar_mode = 'pending'
            try:
                calibration = assert_sugar_calibration(self.server.workbench.machine or {}, require_four_point=True)
                sugar_ready = True
                sugar_mode = calibration['status']
                if sugar_mode == 'EXISTING_COMPATIBILITY':
                    sugar_detail = '沿用当前标定，精度尚未重新验收；原四点拟合残差 %.2f mm' % calibration['max_fit_residual_mm']
            except (ValueError, KeyError, TypeError) as exc:
                sugar_detail = str(exc)
            self.send(200, json_bytes({"version": VERSION, "allow_real": state.allow_real, "token": state.token,
                      "drawing_pipeline_version": PIPELINE_VERSION,
                      "motion_algorithm_version": "motion-smooth-v1", "default_motion_mode": "sugar_fast",
                      "motion_modes": ["sugar_fast", "classic_fast", "speed_priority", "smooth_fast", "gentle", "standard"],
                      "production_motion_modes": ["sugar_fast"],
                      "execution_policy": "planned_vertical_v2", "pen_calibration_supported": True,
                      "kinematic_calibration_supported": True,
                      "sugar_calibration_ready": sugar_ready,
                      "sugar_calibration_detail": sugar_detail,
                      "sugar_calibration_mode": sugar_mode,
                      "pen_release_version": RELEASE_VERSION,
                      "normal_feedback_version": NORMAL_FEEDBACK_VERSION,
                      "external_start_counts_supported": True,
                      "background_plan_save_supported": True,
                      "drawing_size_supported": True,
                      "drawing_geometry_supported": True,
                      "four_point_calibration_supported": True,
                      "four_point_calibration_ready": four_point_ready((self.server.workbench.machine or {}).get('paper',{})),
                      "session_id": state.session_id, "motion_supported": self.server.workbench.allow_motion, "physical_authorized": False,
                      "python": sys.version.split()[0], "events": state.events[-12:],
                      "cloud_configured": bool(self.server.cloud.config_path),
                      "ik_backend": getattr(self.server.workbench.backend, 'name', 'PS_float32_inputs'),
                      "ik_metrics": self.server.workbench.backend.metrics() if self.server.workbench.backend is not None else {},
                      "execution_guard_policy": (self.server.workbench.machine or {}).get('execution', {}).get('guard_policy', 'audit')}))
        elif path == "/api/jobs":
            self.send(200, json_bytes(self.server.workbench.snapshot()))
        elif path == "/api/plans":
            # 历史规划列表: 服务重启后仍可用, 供 GUI 选择执行哪一份
            self.send(200, json_bytes(self.server.workbench.list_plans()))
        elif path == "/api/calligraphy" and hasattr(self.server.workbench,'calligraphy_catalog'):
            self.send(200,json_bytes(self.server.workbench.calligraphy_catalog()))
        elif path == "/api/hardpen_works" and hasattr(self.server.workbench,'hardpen_works'):
            self.send(200,json_bytes(self.server.workbench.hardpen_works()))
        elif path == "/api/hardpen" and hasattr(self.server.workbench,'hardpen_catalog'):
            self.send(200,json_bytes(self.server.workbench.hardpen_catalog()))
        elif path == "/api/masterpiece_store" and hasattr(self.server.workbench,'masterpiece_store'):
            self.send(200,json_bytes(self.server.workbench.masterpiece_store()))
        elif path == "/api/config":
            template = ROOT / "config/machine.example.json"
            self.send(200, json_bytes(self.server.workbench.machine or json.loads(template.read_text(encoding="utf-8"))))
        elif path.startswith('/api/plans/') and path.endswith('/preview.svg'):
            parts = path.split('/')
            if len(parts) != 5 or not parts[3]:
                self.fail(404, 'Not found'); return
            try:
                self.send(200, self.server.workbench.prediction_svg(parts[3]), 'image/svg+xml; charset=utf-8')
            except ValueError as exc:
                self.fail(404, str(exc))
        elif path.startswith('/api/plans/') and path.endswith('/preview'):
            parts = path.split('/')
            if len(parts) != 5 or not parts[3]:
                self.fail(404, 'Not found'); return
            try:
                self.send(200, json_bytes(self.server.workbench.prediction_data(parts[3])))
            except ValueError as exc:
                self.fail(404, str(exc))
        elif path.startswith("/job/"):
            parts = path.split('/')
            allowed = {'paths.svg':'image/svg+xml','preview.svg':'image/svg+xml','input.png':'image/png','lineart.png':'image/png',
                       'paths.json':'application/json','drawing.json':'application/json','plan.json':'application/json','result.json':'application/json','timing.json':'application/json','trajectory_config.json':'application/json','paths.dxf':'application/dxf','execution_trace.json':'application/json'}
            if len(parts) != 4 or parts[2] not in self.server.workbench.jobs or parts[3] not in allowed:
                self.fail(404, "Not found")
                return
            target = state.directory / ('job_' + parts[2]) / parts[3]
            if not target.is_file():
                self.fail(404, "File not ready")
                return
            self.send(200, target.read_bytes(), allowed[parts[3]])
        elif path == "/api/ports":
            try:
                from serial.tools import list_ports
                ports = [{"device": p.device, "description": p.description} for p in list_ports.comports()]
                self.send(200, json_bytes({"ports": ports, "error": None}))
            except ImportError:
                self.send(200, json_bytes({"ports": [], "error": "pyserial 未安装；模拟模式不需要。实物检查请安装 requirements-serial.txt。"}))
        else:
            files = {"/": ("web/index.html", "text/html; charset=utf-8"),
                     "/sample.png": ("examples/input.png", "image/png"),
                     "/app.js": ("web/app.js", "text/javascript; charset=utf-8"),
                     "/style.css": ("web/style.css", "text/css; charset=utf-8"),
                     "/guide": ("START_HERE.html", "text/html; charset=utf-8")}
            for demo in ("line", "circle", "two-strokes"):
                files["/examples/" + demo + ".json"] = ("examples/" + demo + "/summary.json", "application/json; charset=utf-8")
                files["/examples/" + demo + ".svg"] = ("examples/" + demo + "/preview.svg", "image/svg+xml")
            if path not in files:
                self.fail(404, "Not found")
                return
            name, kind = files[path]
            target = ROOT / name
            if not target.is_file():
                self.fail(404, "Example not built; see README")
                return
            self.send(200, target.read_bytes(), kind)

    def do_POST(self):
        if not self.trusted(mutate=True):
            return
        if self.path == '/api/cloud':
            try:
                count = int(self.headers.get('Content-Length', '-1'))
                if self.headers.get('Transfer-Encoding') or not 0 < count <= 8000000:
                    raise ValueError('图片需小于 8 MB')
                raw = self.rfile.read(count)
                if len(raw) != count:
                    raise ValueError('图片传输不完整')
                self.send(202, json_bytes(self.server.cloud.start(raw, self.headers.get('X-Subject','portrait'),
                          self.headers.get('X-Cloud-Profile') or None)))
            except (ValueError, OSError) as exc:
                self.fail(400, str(exc))
            except RuntimeError as exc:
                self.fail(409, str(exc))
            return
        if self.server.board:
            try:
                allowed = ('image','plan','enable','jog','execute','probe','export','heartbeat','stop','config','preset','strokes','home','calibrate_pen','read_pen_pose')
                if self.path not in tuple('/api/'+x for x in allowed):
                    raise ValueError('Unsupported board action')
                count = int(self.headers.get('Content-Length', '-1'))
                cap = 8000000 if self.path == '/api/image' else 32768
                if self.headers.get('Transfer-Encoding') or not 0 <= count <= cap:
                    raise ValueError('请求长度无效')
                raw = self.rfile.read(count)
                if len(raw) != count:
                    raise ValueError('请求传输不完整')
                headers = {k:self.headers[k] for k in ('Content-Type','X-Image-Style','X-Width-MM','X-Height-MM',
                           'X-Max-Segments','X-Trace-Detail') if k in self.headers}
                code, data, kind = self.server.board.request('POST', self.path, raw, headers)
                self.send(code, data, kind, 'so101_session.zip' if self.path == '/api/export' and code == 200 else None)
            except (ValueError, OSError) as exc:
                self.fail(502, str(exc))
            return
        if self.path == '/api/pl_image':
            backend = getattr(self.server, 'pl_image', None)
            if backend is None:
                self.fail(404, '实时图像旁路未启用')
                return
            try:
                count = int(self.headers.get('Content-Length', '-1'))
                if self.headers.get('Transfer-Encoding') or not 0 < count <= 8000000:
                    raise ValueError('图像需小于 8 MB')
                raw = self.rfile.read(count)
                if len(raw) != count:
                    raise ValueError('图像传输不完整')
                width = int(self.headers.get('X-Width-MM', '32'))
                height = int(self.headers.get('X-Height-MM', '24'))
                thr = int(self.headers.get('X-Sobel-Thr', '48'))
                mode = int(self.headers.get('X-Image-Mode', '2'))
                backend.configure(width, height, mode=mode, sobel_thr=thr)
                import numpy as np
                from stream_sink import loopback_frame
                # 有上传 raw 时按 raw 推断一帧；无 raw（或空）用回环帧做通路自检
                if raw:
                    arr = np.frombuffer(raw, dtype=np.uint8)
                    expected = width * height
                    if arr.size >= expected:
                        frame = np.zeros(expected, dtype=np.uint32)
                        frame[:arr.size] = arr[:arr.size]
                    elif arr.size == expected * 4:
                        frame = arr.view('uint32')
                    else:
                        frame = np.zeros(expected, dtype=np.uint32)
                        frame[:arr.size] = arr[:arr.size]
                else:
                    frame = loopback_frame(width, height, fill=200)
                result = backend.process_frame(lambda: frame)
                paths = _frame_to_paths(backend.read_out_frame(width, height), width, height)
                self.send(200, json_bytes(dict(pl=result, paths=paths,
                          hint='host-loopback: 无板卡也可验证通路；正式接 OV7725 见 docs/PL_IMAGE_OV7725.md')))
            except (ValueError, OSError) as exc:
                self.fail(400, str(exc))
            return
        if self.path == '/api/image':
            try:
                count = int(self.headers.get('Content-Length', '-1'))
                if self.headers.get('Transfer-Encoding') or not 0 < count <= 8000000:
                    raise ValueError('图片需小于 8 MB')
                raw = self.rfile.read(count)
                if len(raw) != count:
                    raise ValueError('图片传输不完整')
                data = dict(style=self.headers.get('X-Image-Style','lineart'), width_mm=self.headers.get('X-Width-MM','20'),
                            height_mm=self.headers.get('X-Height-MM','20'), max_segments=self.headers.get('X-Max-Segments','4000'),
                            detail=self.headers.get('X-Trace-Detail','fine'))
                self.send(202, json_bytes(self.server.workbench.start('image', data, raw)))
            except (ValueError, OSError) as exc:
                self.fail(400, str(exc))
            except RuntimeError as exc:
                self.fail(409, str(exc))
            return
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.fail(400, "Expected bounded JSON")
            return
        try:
            count = int(self.headers.get("Content-Length", "-1"))
            # /api/strokes 要上传完整笔画数据 (复杂图形可达数 MB),
            # 其余 POST 保持 32 KB 的小上限。
            limit = 16000000 if self.path == '/api/strokes' else (131072 if self.path=='/api/handwriting/stroke' else 32768)
            if not 0 <= count <= limit:
                raise ValueError("Request too large or length missing")
            raw = self.rfile.read(count)
            if len(raw) != count:
                raise ValueError("Truncated request")
            data = json.loads(raw)
            if self.path.startswith('/api/handwriting/') and self.server.robot=='tcb705':
                if not isinstance(data,dict):raise ValueError('Expected JSON object')
                session=self.server.workbench.handwriting
                actions={'open':session.open,'stroke':session.submit,'heartbeat':session.heartbeat,
                         'size':session.resize,'next':session.next_character,'stop':session.stop,
                         'close':lambda d:session.stop(d,close=True)}
                action=actions.get(self.path[len('/api/handwriting/'):])
                if action is None:raise ValueError('无效手写操作')
                self.send(200,json_bytes(action(data)))
            elif self.path in ('/api/vision/recognise', '/api/vision/configure') and self.server.robot=='tcb705':
                if not isinstance(data,dict):raise ValueError('Expected JSON object')
                vision=vision_service(self.server)
                self.send(200,json_bytes(vision.recognise(data) if self.path.endswith('/recognise') else vision.configure(data)))
            elif self.path == '/api/heartbeat':
                self.server.workbench.touch()
                self.send(200, b'{}')
            elif self.path == '/api/stop':
                self.send(200, json_bytes(self.server.workbench.stop()))
            elif self.path == '/api/config':
                self.send(200, json_bytes(self.server.workbench.configure(data)))
            elif self.path == '/api/brush-profile' and hasattr(self.server.workbench,'configure_brush'):
                self.send(200,json_bytes(self.server.workbench.configure_brush(data)))
            elif self.path == '/api/hardpen-profile' and hasattr(self.server.workbench,'configure_hardpen'):
                self.send(200,json_bytes(self.server.workbench.configure_hardpen(data)))
            elif self.path == '/api/tool' and hasattr(self.server.workbench,'set_tool'):
                self.send(200,json_bytes(self.server.workbench.set_tool(data)))
            elif self.path == '/api/calligraphy' and hasattr(self.server.workbench,'calligraphy_catalog'):
                self.send(202,json_bytes(self.server.workbench.start('calligraphy',data)))
            elif self.path in ('/api/masterpiece','/api/masterpiece_all','/api/poem_segment','/api/hardpen_line','/api/hardpen_doc','/api/couplet_page') and hasattr(self.server.workbench,'masterpiece_store'):
                self.send(202,json_bytes(self.server.workbench.start(self.path[5:],data)))
            elif self.path == '/api/speed' and hasattr(self.server.workbench, 'set_speed'):
                self.send(200, json_bytes(self.server.workbench.set_speed(data)))
            elif self.path in ('/api/plan','/api/enable','/api/jog','/api/execute','/api/preset','/api/strokes','/api/home','/api/calibrate_pen','/api/read_pen_pose'):
                self.send(202, json_bytes(self.server.workbench.start(self.path[5:], data)))
            elif self.path == "/api/probe":
                if self.server.robot == 'tcb705':
                    self.send(202,json_bytes(self.server.workbench.start('read_pen_pose',data)))
                else:
                    self.send(200, json_bytes(self.server.state.scan(data)))
            elif self.path == "/api/export":
                self.send(200, self.server.state.export(), "application/zip", "so101_session.zip")
            else:
                self.fail(404, "No such action")
        except (ValueError, TypeError) as exc:
            self.fail(400, str(exc))
        except RuntimeError as exc:
            self.fail(409, str(exc))
        except OSError as exc:
            self.fail(500, "I/O or audit failure: " + str(exc))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allow-real", action="store_true", help="Enable PING/READ")
    parser.add_argument("--allow-motion", action="store_true", help="Enable calibrated physical debugging")
    parser.add_argument('--robot',choices=('tcb705','so101'),default='tcb705')
    parser.add_argument('--simulation',action='store_true',help='TCB705 offline planning and simulated execution only')
    parser.add_argument('--tcb-profile',type=Path)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "logs")
    parser.add_argument('--board-url', help='电脑端：板端 SSH 转发地址，例如 http://127.0.0.1:8768')
    parser.add_argument('--cloud-config', type=Path, help='电脑端图生图 API 配置文件')
    parser.add_argument('--secrets-file', type=Path, help='电脑端私用包密钥文件，不记录到日志')
    parser.add_argument('--overlay', type=Path, help='板端自行综合的 Z20 bit 文件，同目录放 hwh')
    parser.add_argument('--pl-load-policy', choices=('download','attach'), default='download')
    parser.add_argument('--platform-manifest', type=Path)
    parser.add_argument('--platform-ready', type=Path)
    from engine import default_engine, make_backend
    parser.add_argument('--ik-engine', choices=('wls','upstream'), default=default_engine())
    parser.add_argument('--ip-name', help='默认由 ik-engine 选择匹配 IP')
    parser.add_argument('--pl-mode', choices=('wls', 'full', 'target', 'planner'), default='wls',
                        help='wls=单步核；full=任务步核；target=PL 完整目标求解；planner=显式 v2 批量核')
    parser.add_argument('--pl-image', type=Path, metavar='OVERLAY',
                        help='启用实时图像旁路：加载含 z20_pl_image 的 overlay 并开放 /api/pl_image（独立于云端主链路）')
    args = parser.parse_args()
    if args.secrets_file:
        from cloud import load_secrets
        load_secrets(args.secrets_file)
    if not 1024 <= args.port <= 65535:
        parser.error("port must be 1024..65535")
    state = State(args.data_dir, args.allow_real or args.allow_motion)
    backend = None
    pl_image = None
    if args.overlay and args.board_url:
        parser.error('--overlay 只在板端使用')
    if args.overlay and args.pl_image:
        parser.error('IK 与图像 overlay 会替换同一个 PL；请分别启动，或使用合并后的匹配硬件工程')
    if args.robot == 'tcb705' and (args.overlay or args.pl_image or args.allow_motion):
        parser.error('TCB705 uses its seven-axis platform; old PL IK and --allow-motion are unavailable')
    if not args.board_url and args.robot != 'tcb705':
        backend = make_backend(args.ik_engine, args.overlay, args.ip_name, args.pl_mode,
            args.pl_load_policy,args.platform_manifest,args.platform_ready)
    if args.pl_image and args.board_url:
        parser.error('--pl-image 只在板端使用：板端直接加载图像 overlay，不需要 SSH 转发到电脑')
    if args.pl_image:
        try:
            from pl_image_backend import PlImageBackend
            pl_image = PlImageBackend(args.pl_image, ip_name='z20_pl_image_0')
        except Exception as exc:
            parser.exit(2, '图像平行路加载失败：%s\n先在板端综合 z20_pl_image 并放入三件套（drawing_image.bit/.hwh/.registers.json）' % exc)
    try:
        server = Server(("127.0.0.1", args.port), state, args.allow_motion, args.board_url, args.cloud_config, backend,args.robot,args.simulation,args.tcb_profile)
        server.pl_image = pl_image
        server.vision_data = args.data_dir
    except OSError as exc:
        parser.exit(2, "Cannot start local server: %s\n" % exc)
    print("SO101 console " + server.origin, flush=True)
    print('IK: ' + (server.workbench.capabilities()['ik_backend'] if args.robot=='tcb705' else (getattr(backend, 'name', 'PS_float32_inputs') if not args.board_url else 'REMOTE_BOARD')), flush=True)
    print("MODE: " + ("TEAM DEBUG" if args.allow_motion else "REAL READ" if args.allow_real else "DEMO"), flush=True)
    print("Ctrl+C closes server. Logs: " + str(state.directory), flush=True)
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.workbench.stop()
        server.workbench.close_persistence()
        if server.workbench.worker:
            server.workbench.worker.join(timeout=None if args.robot=='tcb705' else 4)
        if args.robot=='tcb705':
            server.workbench.handwriting.shutdown()
            if getattr(server, '_vision', None) is not None:
                server._vision.camera.close()
            server.workbench.planning_session.close()
        server.server_close()


if __name__ == "__main__":
    main()
