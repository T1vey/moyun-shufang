"""SO-101 板端屏幕孪生 + 手机上传通道（仅依赖 Python 标准库）。

PC 浏览器打开 http://127.0.0.1:8090/ 作为“虚拟板端屏幕”；
手机扫码打开 http://<局域网IP>:8090/upload 上传图片，PC 端通过 SSE 实时显示。
默认只允许局域网地址访问；加 --pair-token 则额外要求配对码（URL 带 ?t=）。

本模块只负责前端与上传通道，不涉及板卡硬件驱动。
"""
import argparse
import ipaddress
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import re
import secrets
import signal
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid

try:
    from . import netinfo
    from .workflow import Workflow, BoardPipeline, validate_image
except ImportError:
    import netinfo
    from workflow import Workflow, BoardPipeline, validate_image

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
VERSION = "2.0"
MAX_UPLOAD = 20 * 1024 * 1024
CLIENT_TIMEOUT = 12.0
ALLOWED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                ".ico": "image/x-icon"}
FORMATS = ("rgb565", "rgb888", "gray8", "mono1")
FITS = ("contain", "cover", "stretch")
DEFAULT_DISPLAY = dict(width=800, height=480, format="rgb565", fit="contain", rotation=0, dither=True,
                       panel="ATK 7.0″ RGB LCD")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def device_name(ua):
    ua = ua or ""
    for pat, name in ((r"iPhone", "iPhone"), (r"iPad", "iPad"), (r"HarmonyOS", "鸿蒙手机"),
                      (r"HUAWEI|HONOR", "华为 / 荣耀"), (r"MI |Redmi|Xiaomi", "小米 / Redmi"),
                      (r"OPPO|OnePlus", "OPPO / 一加"), (r"vivo", "vivo"), (r"Android", "Android 手机"),
                      (r"Windows", "Windows 电脑"), (r"Macintosh", "Mac")):
        if re.search(pat, ua):
            return name
    return "未知设备"


def validate_display(data, current):
    if not isinstance(data, dict):
        raise ValueError("显示参数必须是 JSON 对象")
    out = dict(current)
    for key in ("width", "height"):
        if key in data:
            v = data[key]
            if type(v) is not int or not 16 <= v <= 4096:
                raise ValueError(f"{key} 需在 16..4096 之间")
            out[key] = v
    if "format" in data:
        if data["format"] not in FORMATS:
            raise ValueError("不支持的像素格式")
        out["format"] = data["format"]
    if "fit" in data:
        if data["fit"] not in FITS:
            raise ValueError("不支持的缩放方式")
        out["fit"] = data["fit"]
    if "rotation" in data:
        if data["rotation"] not in (0, 90, 180, 270):
            raise ValueError("旋转只能是 0/90/180/270")
        out["rotation"] = data["rotation"]
    if "dither" in data:
        out["dither"] = bool(data["dither"])
    if "panel" in data:
        out["panel"] = str(data["panel"])[:48]
    return out


class Hub:
    """共享状态：显示参数、帧历史、在线手机、SSE 订阅者。"""

    def __init__(self, upload_dir, token=None, keep=24):
        self.token = token  # None = 局域网开放模式，不需要配对码
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.keep = keep
        self.lock = threading.Lock()
        self.display = dict(DEFAULT_DISPLAY)
        self.frames = []
        self.clients = {}
        self.subscribers = []
        self.seq = 0
        self.control_token = secrets.token_urlsafe(32)
        self.view = 'user'
        self.workflow = None
        self.upload_lock = threading.Lock()

    # --- 推送 ---
    def subscribe(self):
        q = queue.Queue(maxsize=256)
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def publish(self, event, data):
        payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")
        with self.lock:
            subs = list(self.subscribers)
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass

    # --- 手机在线状态 ---
    def client_list(self):
        now = time.time()
        return [dict(id=c["id"], short=c["id"][-6:].upper(), name=c["name"], online=now - c["seen"] < CLIENT_TIMEOUT,
                     state=c.get("state", "idle"), since=c["since"], rtt=c.get("rtt"), ip=c.get("ip"),
                     seen=int((now - c["seen"]) * 1000)) for c in self.clients.values()]

    def touch_client(self, cid, ua, state=None, rtt=None, ip=None):
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,40}", cid or ""):
            raise ValueError("无效的客户端 ID")
        with self.lock:
            c = self.clients.get(cid)
            changed = c is None or time.time() - c["seen"] >= CLIENT_TIMEOUT or (state and c.get("state") != state)
            if c is None:
                c = self.clients[cid] = dict(id=cid, name=device_name(ua), since=utc_now(), seen=0)
            c["seen"] = time.time()
            if ip and c.get("ip") != ip:
                c["ip"] = ip
                changed = True
            if type(rtt) is int and 0 <= rtt < 60000 and rtt != c.get("rtt"):
                c["rtt"] = rtt
                changed = True
            if state:
                c["state"] = state
        if changed:
            self.publish("clients", self.client_list())

    def reap(self):
        changed = False
        now = time.time()
        with self.lock:
            for cid in list(self.clients):
                c = self.clients[cid]
                if now - c["seen"] > CLIENT_TIMEOUT and not c.get("offline_sent"):
                    c["offline_sent"] = True
                    changed = True
                elif now - c["seen"] <= CLIENT_TIMEOUT:
                    c.pop("offline_sent", None)
                if now - c["seen"] > 120:
                    del self.clients[cid]
                    changed = True
        if changed:
            self.publish("clients", self.client_list())

    # --- 帧 ---
    def add_frame(self, raw, kind, cid, meta):
        with self.lock:
            self.seq += 1
            seq = self.seq
        name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{seq:04d}{ALLOWED_TYPES[kind]}"
        (self.upload_dir / name).write_bytes(raw)
        client = self.clients.get(cid, {})
        frame = dict(id=seq, url=f"/frames/{name}", name=name, bytes=len(raw), type=kind, time=utc_now(),
                     source=client.get("name", "手机"), src_width=meta.get("w"), src_height=meta.get("h"))
        with self.lock:
            self.frames.append(frame)
            old = self.frames[:-self.keep]
            self.frames = self.frames[-self.keep:]
        for f in old:
            try:
                (self.upload_dir / f["name"]).unlink()
            except OSError:
                pass
        self.publish("frame", frame)
        return frame


class Handler(BaseHTTPRequestHandler):
    server_version = "SO101Display/" + VERSION
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, fmt, *args):
        if self.server.verbose:
            super().log_message(fmt, *args)

    @property
    def hub(self):
        return self.server.hub

    def send(self, code, body, kind="application/json; charset=utf-8", cache=False):
        if not getattr(self, "body_read", True):
            self.drain_body()
        if isinstance(body, (dict, list)):
            body = (json.dumps(body, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' http:; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def fail(self, code, message):
        self.send(code, dict(error=message))

    def is_local(self):
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def is_screen(self):
        """屏幕页接口：本机，或 --screen-host 指定的设备（如驱动 7 寸屏的板卡）。"""
        ip = self.client_address[0]
        if self.hub.workflow is not None:
            return self.is_local()
        return self.is_local() or (ip[7:] if ip.startswith("::ffff:") else ip) in self.server.screen_hosts

    def trusted_origin(self):
        """Reject DNS rebinding and cross-site requests before revealing tokens."""
        host = self.headers.get('Host', '')
        allowed = {'127.0.0.1', 'localhost', '[::1]'}
        allowed.update(i['ip'] for i in self.server.interfaces)
        if self.server.bind_host not in ('0.0.0.0', '::'):
            allowed.add(self.server.bind_host)
        allowed = {value + ':' + str(self.server.server_port) for value in allowed}
        if self.server.server_port == 80:
            allowed.update(value.rsplit(':', 1)[0] for value in list(allowed))
        if host not in allowed:
            return False
        origin = self.headers.get('Origin')
        return origin is None or origin == 'http://' + host

    def screen_control(self):
        return (self.is_local() and self.trusted_origin() and
                secrets.compare_digest(self.headers.get('X-Screen-Token', ''), self.hub.control_token))

    def has_token(self, query):
        t = self.headers.get("X-Pair-Token") or (query.get("t") or [""])[0]
        return bool(self.hub.token) and secrets.compare_digest(t, self.hub.token)

    def client_ok(self, query):
        """手机侧接口：配对码模式校验 ?t=；开放模式只放行局域网（含本机）来源。"""
        if self.hub.token:
            return self.has_token(query)
        return netinfo.is_lan_client(self.client_address[0])

    def deny_reason(self):
        if self.hub.token:
            return "配对码无效，请重新扫描屏幕上的二维码"
        return "只接受局域网内的设备，请连接与电脑相同的 Wi-Fi"

    def drain_body(self):
        """提前拒绝 POST 时先读完请求体再回复；否则 Windows 会重置连接，手机只看到“网络中断”而拿不到错误原因。"""
        self.body_read = True
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > MAX_UPLOAD or self.headers.get('Transfer-Encoding'):
            self.close_connection = True
            return
        while n > 0:
            chunk = self.rfile.read(min(65536, n))
            if not chunk:
                break
            n -= len(chunk)

    def read_json(self, limit=8192):
        self.body_read = True
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0 or n > limit or self.headers.get('Transfer-Encoding'):
            raise ValueError("请求体过大")
        try:
            raw = self.rfile.read(n)
            if len(raw) != n:
                raise ValueError('请求传输不完整')
            data = json.loads(raw or b"{}")
            if not isinstance(data, dict):
                raise ValueError('请求必须是 JSON 对象')
            return data
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("JSON 格式错误")

    def static(self, name):
        target = (STATIC / name).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            return self.fail(404, "Not found")
        self.send(200, target.read_bytes(), STATIC_TYPES.get(target.suffix, "application/octet-stream"))

    def pair_info(self):
        srv = self.server
        if self.hub.workflow is not None:
            srv.refresh_interfaces()
        return dict(port=srv.server_address[1], bind=srv.bind_host, path="/upload", token=self.hub.token,
                    access="token" if self.hub.token else "lan", interfaces=srv.interfaces,
                    public_url=srv.public_url, instance=srv.instance, wifi_ssid='ESP8200')

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.trusted_origin():
            return self.fail(403, '请通过板子实际地址访问')
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        if path in ('/api/audio/status', '/api/audio/list'):
            if not self.is_screen():return self.fail(403,'仅限板端朗读界面')
            return self.send(200,self.server.audio.status() if path.endswith('/status') else self.server.audio.listing())
        if path=='/vision':return self.static('vision.html')
        if path in ('/api/vision/status','/api/vision/preview','/api/vision/result'):
            if not self.is_screen() or not self.hub.workflow:return self.fail(403,'仅限板端字迹识别界面')
            try:return self.send(200,self.hub.workflow.pipeline.client._request(path))
            except Exception as exc:return self.fail(409,str(exc))
        if path=='/api/handwriting/status':
            if not self.is_screen() or not self.hub.workflow:return self.fail(403,'仅限板端手写界面')
            try:return self.send(200,self.hub.workflow.pipeline.client._request(path))
            except Exception as exc:return self.fail(400,str(exc))
        if path=='/handwriting':return self.static('handwriting.html')
        if path.startswith('/api/text/'):
            if not self.client_ok(query):return self.fail(403,self.deny_reason())
            if not self.hub.workflow:return self.fail(409,'未启用板端工作流')
            try:
                if path=='/api/text/license':
                    from calligraphy.glyph_store import DATABASE
                    return self.send(200,(DATABASE.parent/'APL-English.txt').read_bytes(),'text/plain; charset=utf-8')
                if path=='/api/text/capabilities':return self.send(200,self.hub.workflow.text_capabilities())
                if path=='/api/text/hardpen-capabilities':return self.send(200,self.hub.workflow.hardpen_capabilities())
                if path=='/api/text/status':return self.send(200,self.hub.workflow.text_status(
                    (query.get('cid') or [''])[0],(query.get('job_id') or [''])[0]))
                return self.fail(404,'Not found')
            except (ValueError,RuntimeError,OSError) as exc:return self.fail(400,str(exc))
        if path.startswith('/api/lineart-library'):
            if not self.is_local():
                return self.fail(403, '仅限本机线稿图库')
            try:
                if path == '/api/lineart-library':
                    items = self.server.lineart_library.records()
                    return self.send(200, dict(items=items, total=len(items)))
                prefix = '/api/lineart-library/image/'
                if path.startswith(prefix):
                    raw, kind = self.server.lineart_library.read(path[len(prefix):], bool(query.get('thumbnail')))
                    return self.send(200, raw, kind)
            except (ValueError, OSError) as exc:
                return self.fail(404, str(exc))
            return self.fail(404, 'Not found')
        if path.startswith('/api/tcb/'):
            if not self.is_screen() or not self.hub.workflow:return self.fail(403,'仅限板端设置界面')
            try:
                suffix=path[len('/api/tcb/'):]
                if suffix not in ('status','config','jobs','plans','calligraphy','masterpiece_store','hardpen'):
                    bits=suffix.split('/')
                    if len(bits)!=3 or bits[0]!='plans' or bits[2]!='preview.svg' or not bits[1].isalnum():return self.fail(404,'Not found')
                value=self.hub.workflow.pipeline.client._request('/api/'+suffix)
                if isinstance(value,dict):value.pop('token',None)
                return self.send(200,value,'image/svg+xml' if suffix.endswith('.svg') else 'application/json; charset=utf-8')
            except Exception as exc:return self.fail(400,str(exc))
        if path in ("/", "/index.html"):
            return self.static("desktop.html")
        if path in ("/debug", "/debug/"):
            return self.static("tcb-debug.html")
        if path in ("/upload", "/upload/", "/m", "/m/"):
            if not self.client_ok(query):
                page = (STATIC / "expired.html").read_text("utf-8").replace("{{reason}}", self.deny_reason())
                return self.send(403, page.encode("utf-8"), STATIC_TYPES[".html"])
            return self.static("mobile.html")
        if path == "/api/ping":  # 屏幕页用来自测某个网卡地址是否可达（跨源）
            body = (json.dumps(dict(ok=True, instance=self.server.instance)) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        if path == "/api/network":
            if not self.is_screen():
                return self.fail(403, "仅限本机屏幕页访问（其他设备需启动时加 --screen-host）")
            if query.get("refresh"):
                self.server.refresh_interfaces()
            return self.send(200, self.pair_info())
        if path.startswith("/static/"):
            return self.static(path[len("/static/"):])
        if path.startswith("/frames/"):
            name = path[len("/frames/"):]
            if not re.fullmatch(r"[0-9_]+\.(jpg|png|webp)", name) or not (self.is_screen() or self.client_ok(query)):
                return self.fail(404, "Not found")
            f = self.hub.upload_dir / name
            if not f.is_file():
                return self.fail(404, "帧已过期")
            kind = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}[f.suffix]
            return self.send(200, f.read_bytes(), kind, cache=True)
        if path == "/api/state":
            if not self.is_screen():
                return self.fail(403, "仅限本机屏幕页访问（其他设备需启动时加 --screen-host）")
            return self.send(200, dict(version=VERSION, display=self.hub.display, frames=self.hub.frames,
                                       clients=self.hub.client_list(), pair=self.pair_info(),
                                       control_token=self.hub.control_token,
                                       workflow=self.hub.workflow.snapshot() if self.hub.workflow else None,
                                       view=self.hub.workflow.view if self.hub.workflow else self.hub.view))
        if path == '/api/view':
            if not self.is_local():
                return self.fail(403, '仅限板端屏幕')
            return self.send(200, {'view': self.hub.workflow.view if self.hub.workflow else self.hub.view})
        if path == '/api/upload-status':
            if not self.client_ok(query):
                return self.fail(403, self.deny_reason())
            if not self.hub.workflow:
                return self.send(200, dict(phase='idle', progress=0, message='当前为显示演示模式'))
            try:
                return self.send(200, self.hub.workflow.status_for(
                    (query.get('cid') or [''])[0], (query.get('job_id') or [''])[0]))
            except ValueError as exc:
                return self.fail(404, str(exc))
        if path == '/api/masterpieces':
            if not self.is_screen():
                return self.fail(403, '仅限板端屏幕')
            from calligraphy import glyph_store
            works = []
            for style in glyph_store.masterpieces():
                m = glyph_store.manifest(style)
                # Keyframes only (50-unit cell): enough for the picker, never used for motion.
                glyphs = [[[[round(p[0], 2), round(p[1], 2), round(p[2], 2)] for p in s['points']]
                           for s in glyph_store.glyph_at(style, i)['strokes']] for i in range(m['count'])]
                works.append(dict(style=style, label=m['label'], title=m['title'], author=m['author'],
                                  dynasty=m['dynasty'], script=m['script'], note=m.get('note', ''),
                                  sentence=m['characters'], glyphs=glyphs))
            return self.send(200, dict(works=works, size_mm=70, rows=3, speed_pct=100))
        if path in ('/api/encyclopedia', '/api/encyclopedia/glyphs', '/api/encyclopedia/strokes'):
            if not self.is_screen():
                return self.fail(403, '仅限板端屏幕')
            from user_gui import encyclopedia
            try:
                if path == '/api/encyclopedia':
                    return self.send(200, encyclopedia.content())
                if path == '/api/encyclopedia/strokes':
                    return self.send(200, encyclopedia.strokes((query.get('modules') or [''])[0]))
                style = (query.get('style') or [''])[0]; chars = (query.get('chars') or [''])[0]
                if style == 'styles':      # one character in every style that has it
                    return self.send(200, dict(char=chars, figures=[encyclopedia.glyphs(s, chars)
                                                                    for s in encyclopedia.styles_of(chars)]))
                return self.send(200, encyclopedia.glyphs(style, chars))
            except ValueError as exc:
                return self.fail(400, str(exc))
        if path == '/api/quiz/round':
            if not self.is_screen():
                return self.fail(403, '仅限板端屏幕')
            from user_gui import quiz
            return self.send(200, quiz.round_())
        if path == '/api/hardpen/preview':
            if not self.is_screen() or not self.hub.workflow:
                return self.fail(403, '仅限板端屏幕')
            from calligraphy import hardpen
            try:
                size = int((query.get('size') or ['0'])[0] or 0)
                layout = (query.get('layout') or [''])[0]
                if layout:   # a saved phone piece (2026-10-29): its first page
                    return self.send(200, hardpen.doc_preview_svg((query.get('text') or [''])[0], size, layout,
                                                                  self.hub.workflow.pipeline.text_config()), 'image/svg+xml')
                return self.send(200, hardpen.preview_svg((query.get('text') or [''])[0], size, self.hub.workflow.pipeline.text_config()),
                                 'image/svg+xml')
            except ValueError as exc:
                return self.fail(400, str(exc))
        if path == '/api/hardpen':
            # 硬笔书法 window: pieces the library can write, sizes, speeds and the saved works.
            if not self.is_screen() or not self.hub.workflow:
                return self.fail(403, '仅限板端屏幕')
            from calligraphy import hardpen
            try:
                works = self.hub.workflow.pipeline.hardpen_works() if hasattr(self.hub.workflow.pipeline, 'hardpen_works') else []
                return self.send(200, dict(presets=hardpen.presets(), sizes=list(hardpen.SIZES), speeds=list(hardpen.SPEEDS),
                                           works=works, count=hardpen.manifest()['count']))
            except ValueError as exc:
                return self.fail(400, str(exc))
        if path in ('/api/poems', '/api/poems/preview'):
            if not self.is_screen() or not self.hub.workflow:
                return self.fail(403, '仅限板端屏幕')
            from calligraphy import poems
            try:
                config = self.hub.workflow.pipeline.text_config()
                if path == '/api/poems':
                    return self.send(200, dict(items=poems.catalog(config['paper']), sizes=[poems.POEM_SIZE_MM],
                                               default_size=poems.POEM_SIZE_MM, speed_pct=poems.SPEED_PCT))
                size = int((query.get('size') or ['0'])[0] or 0)
                return self.send(200, poems.preview_svg((query.get('id') or [''])[0], size, config,
                                                        int((query.get('page') or ['0'])[0] or 0)), 'image/svg+xml', cache=True)
            except (ValueError, IndexError) as exc:
                return self.fail(400, str(exc))
        if path == '/api/couplets':
            if not self.is_screen():
                return self.fail(403, '仅限板端屏幕')
            from calligraphy import couplets
            table = None
            try:   # 2026-10-29: couplets are written on the 名帖 paper calibration
                paper = self.hub.workflow.pipeline.text_config().get('paper') if self.hub.workflow else None
                table = {k: paper[k] for k in ('width_mm', 'height_mm')} if paper else None
            except Exception:
                pass   # the picker still lists the couplets; submitting reports a missing calibration
            items = couplets.catalog()
            needed = {}
            for c in items:
                needed.setdefault(str(c['chars']), couplets.needed_mm(c['id']))
            return self.send(200, dict(items=items, size_mm=couplets.SIZE_MM, table=table, needed=needed))
        if path == '/api/workflow/preview':
            if not self.is_screen() or not self.hub.workflow:
                return self.fail(403, '仅限板端屏幕')
            try:
                return self.send(200, self.hub.workflow.preview((query.get('job_id') or [''])[0]), 'image/svg+xml')
            except ValueError as exc:
                return self.fail(404, str(exc))
        if path == "/api/display":
            if not self.client_ok(query):
                return self.fail(403, self.deny_reason())
            return self.send(200, self.hub.display)
        if path == "/api/events":
            if not self.is_screen():
                return self.fail(403, "仅限本机屏幕页访问（其他设备需启动时加 --screen-host）")
            return self.events()
        return self.fail(404, "Not found")

    def events(self):
        q = self.hub.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(b"retry: 1500\n\n")
            self.wfile.flush()
            while not self.server.stopping.is_set():
                try:
                    payload = q.get(timeout=15)
                except queue.Empty:
                    payload = b": keepalive\n\n"
                self.wfile.write(payload)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.hub.unsubscribe(q)

    def do_POST(self):
        self.body_read = False
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        try:
            if not self.trusted_origin():
                return self.fail(403, '跨站请求已拒绝，请重新扫码')
            if path.startswith('/api/audio/'):
                if not self.screen_control():return self.fail(403,'仅限板端朗读操作')
                data=self.read_json(limit=8192)
                return self.send(202,self.server.audio.submit(path.rsplit('/',1)[-1],data))
            if path=='/api/hwr/recognize':
                # 手写识字 (2026-10-28): recognition only, no robot and no network; the screen only.
                if not self.is_screen():return self.fail(403,'仅限板端屏幕')
                data=self.read_json(limit=262144)
                try:return self.send(200,self.server.hwr.recognize(data.get('strokes') if isinstance(data,dict) else None))
                except ValueError as exc:return self.fail(400,str(exc))
            if path in ('/api/vision/recognise','/api/vision/configure'):
                if not self.screen_control() or not self.hub.workflow:return self.fail(403,'仅限板端字迹识别操作')
                data=self.read_json(limit=8192)
                try:return self.send(200,self.hub.workflow.pipeline.client._request(path,method='POST',data=data))
                except Exception as exc:return self.fail(409,str(exc))
            if path.startswith('/api/handwriting/'):
                if not self.screen_control() or not self.hub.workflow:return self.fail(403,'仅限板端手写操作')
                if path.rsplit('/',1)[-1] not in ('open','stroke','heartbeat','size','next','stop','close'):
                    return self.fail(404,'Not found')
                data=self.read_json(limit=131072 if path.endswith('/stroke') else 8192)
                return self.send(200,self.hub.workflow.pipeline.client._request(path,method='POST',data=data))
            if path.startswith('/api/text/'):
                if not self.client_ok(query):return self.fail(403,self.deny_reason())
                if not self.hub.workflow:return self.fail(409,'未启用板端工作流')
                data=self.read_json(limit=16384);cid=data.get('cid','')
                if not isinstance(cid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{6,40}',cid):raise ValueError('无效手机编号')
                workflow=self.hub.workflow
                if path=='/api/text/preview':result=workflow.text_preview(cid,data.get('text'),data.get('font_size_mm'),data.get('style','kai'))
                elif path=='/api/text/submit':result=workflow.submit_text(cid,data)
                elif path=='/api/text/hardpen-preview':result=workflow.hardpen_preview(cid,data.get('text'),data.get('font_size_mm'),data.get('layout'))
                elif path=='/api/text/hardpen-submit':result=workflow.submit_hardpen_text(cid,data)
                elif path=='/api/text/cancel':result=workflow.cancel_text(cid,data.get('job_id'))
                elif path=='/api/text/next-page':
                    if data.get('paper_ready') is not True:raise ValueError('请先确认已经换纸')
                    result=workflow.next_text_page(cid,data.get('job_id'),data.get('page_index'))
                else:return self.fail(404,'Not found')
                return self.send(200,result)
            if path in ('/api/lineart-library/import', '/api/lineart-library/prepare'):
                if not self.screen_control():
                    return self.fail(403, '仅限本机线稿图库操作')
                if path.endswith('/import'):
                    total = int(self.headers.get('Content-Length') or 0)
                    if total <= 0 or total > MAX_UPLOAD or self.headers.get('Transfer-Encoding'):
                        raise ValueError('图片不能为空，且需小于 20 MB')
                    self.body_read = True
                    raw = self.rfile.read(total)
                    if len(raw) != total:
                        raise ValueError('图片传输不完整')
                    kind = (self.headers.get('Content-Type') or '').split(';')[0].strip().lower()
                    item = self.server.lineart_library.save(raw, kind, (query.get('name') or ['导入线稿'])[0])
                    return self.send(200, dict(item=item))
                if not self.hub.workflow:
                    return self.fail(409, '未启用绘画工作流')
                data = self.read_json()
                raw, kind = self.server.lineart_library.read(data.get('id'))
                cid, rid = data.get('cid', ''), data.get('rid', '')
                if not re.fullmatch(r'[A-Za-z0-9_-]{6,40}', cid) or not re.fullmatch(r'[A-Za-z0-9_-]{6,80}', rid):
                    raise ValueError('无效的任务编号')
                if not self.hub.upload_lock.acquire(blocking=False):
                    raise RuntimeError('正在接收另一张图片，请稍后再试')
                reservation = None
                try:
                    reservation = self.hub.workflow.reserve(cid, rid)
                    frame = self.hub.add_frame(raw, kind, cid, validate_image(raw, kind))
                    workflow = self.hub.workflow.submit(reservation, raw, frame, input_mode='lineart')
                    return self.send(200, dict(workflow=workflow, job_id=workflow['job_id']))
                except Exception:
                    if reservation:
                        self.hub.workflow.abandon(reservation)
                    raise
                finally:
                    self.hub.upload_lock.release()
            if path == '/api/local-lineart':
                if not self.screen_control():
                    return self.fail(403, '请在板端屏幕或本机连接的用户界面选择线条图')
                if not self.hub.workflow:
                    return self.fail(409, '当前为显示演示模式，未启用板端处理')
                return self.upload(query, input_mode='lineart')
            if path.startswith('/api/tcb/'):
                if not self.screen_control() or not self.hub.workflow:return self.fail(403,'仅限板端设置界面')
                suffix=path[len('/api/tcb/'):]
                if suffix not in ('config','speed','brush-profile','hardpen-profile','tool','preset','calligraphy','plan','execute','read_pen_pose','stop','masterpiece_all'):return self.fail(404,'Not found')
                data=self.read_json()
                return self.send(200,self.hub.workflow.pipeline.client._request('/api/'+suffix,method='POST',data=data))
            if path.startswith('/api/workflow/') or path.startswith('/api/settings/'):
                if not self.screen_control():
                    return self.fail(403, '仅限板端屏幕确认，请刷新界面')
                data = self.read_json()
                workflow = self.hub.workflow
                if path in ('/api/settings/open', '/api/settings/close'):
                    view = 'settings' if path.endswith('/open') else 'user'
                    if workflow:
                        return self.send(200, workflow.set_view(view))
                    self.hub.view = view
                    return self.send(200, {'view': view})
                if not workflow:
                    return self.fail(409, '当前为显示演示模式，未启用板端处理')
                if path == '/api/workflow/calligraphy':
                    result=workflow.submit_calligraphy(data.get('module'),data.get('size_mm',40),data.get('request_id'))
                elif path == '/api/workflow/home':
                    result=workflow.home_arm(data.get('request_id'),data.get('confirmed'))
                elif path == '/api/workflow/hardpen':
                    result=workflow.submit_hardpen(data.get('text'),data.get('size_mm'),data.get('speed_pct'),data.get('request_id'),data.get('confirmed'))
                elif path == '/api/workflow/hardpen-doc':
                    result=workflow.submit_hardpen_doc(data.get('text'),data.get('size_mm'),data.get('layout'),data.get('speed_pct'),data.get('request_id'),data.get('confirmed'))
                elif path == '/api/workflow/poem':
                    result=workflow.submit_poem(data.get('poem_id'),data.get('request_id'),data.get('confirmed'),read_along=data.get('read_along') is True)
                elif path == '/api/workflow/couplet':
                    result=workflow.submit_couplet(data.get('couplet_id'),data.get('request_id'),data.get('confirmed') is True)
                elif path == '/api/workflow/masterpiece':
                    result=workflow.submit_masterpiece(data.get('style'),data.get('request_id'),data.get('confirmed'),read_along=data.get('read_along') is True)
                elif path == '/api/workflow/text-next-page':
                    if data.get('paper_ready') is not True:raise ValueError('请先确认已经换纸')
                    workflow.next_text_page(workflow._owner,data.get('job_id'),data.get('page_index'))
                    result=workflow.snapshot()
                elif path == '/api/workflow/start':
                    result = workflow.start(data.get('job_id'), data.get('revision'), data.get('confirmed'))
                elif path == '/api/workflow/cancel':
                    result = workflow.cancel(data.get('job_id'))
                elif path == '/api/workflow/reset':
                    result = workflow.reset(data.get('job_id'))
                elif path == '/api/workflow/preview-shown':
                    result = workflow.preview_shown(data.get('job_id'))
                else:
                    return self.fail(404, 'Not found')
                return self.send(200, result)
            if path == "/api/hello":
                if not self.client_ok(query):
                    return self.fail(403, self.deny_reason())
                data = self.read_json()
                self.hub.touch_client(data.get("cid"), self.headers.get("User-Agent"), data.get("state"),
                                      data.get("rtt"), self.client_address[0])
                return self.send(200, dict(ok=True, display=self.hub.display))
            if path == "/api/upload":
                if not self.client_ok(query):
                    return self.fail(403, self.deny_reason())
                return self.upload(query)
            if path == "/api/display":
                if not self.screen_control():
                    return self.fail(403, "仅限本机屏幕页修改（其他设备需启动时加 --screen-host）")
                with self.hub.lock:
                    self.hub.display = validate_display(self.read_json(), self.hub.display)
                self.hub.publish("display", self.hub.display)
                return self.send(200, self.hub.display)
            if path == "/api/token":
                if not self.screen_control():
                    return self.fail(403, "仅限本机屏幕页修改（其他设备需启动时加 --screen-host）")
                if not self.hub.token:
                    raise ValueError("当前为局域网开放模式，没有配对码；启动时加 --pair-token 启用")
                self.hub.token = secrets.token_urlsafe(9)
                with self.hub.lock:
                    self.hub.clients.clear()
                self.hub.publish("clients", [])
                return self.send(200, self.pair_info())
            return self.fail(404, "Not found")
        except ValueError as exc:
            return self.fail(400, str(exc))
        except RuntimeError as exc:
            return self.fail(409, str(exc))
        except (OSError, TimeoutError):
            self.close_connection = True
            return self.fail(500, '图片传输或存储失败，请检查连接后重试')

    def upload(self, query, input_mode='photo'):
        if not self.hub.upload_lock.acquire(blocking=False):
            raise RuntimeError('另一台设备正在上传，请稍后重试')
        reservation = None
        try:
            cid = (query.get('cid') or [''])[0]
            if not re.fullmatch(r'[A-Za-z0-9_-]{6,40}', cid):
                raise ValueError('无效的客户端 ID')
            if self.hub.workflow:
                request_id = (query.get('rid') or [''])[0]
                if request_id and not re.fullmatch(r'[A-Za-z0-9_-]{6,80}', request_id):
                    raise ValueError('无效的上传编号')
                reservation = self.hub.workflow.reserve(cid, request_id or None)
            return self._upload(query, reservation, input_mode)
        except Exception:
            if reservation:
                self.hub.workflow.abandon(reservation)
            raise
        finally:
            self.hub.upload_lock.release()

    def _upload(self, query, reservation, input_mode='photo'):
        cid = (query.get("cid") or [""])[0]
        cloud_options = None
        if input_mode == 'photo':
            # Phone choice: portrait / object / landscape, or its own text ('custom').
            # Checked before the body is read so a bad choice never costs an upload.
            import cloud
            subject = (query.get("subject") or ["portrait"])[0]
            custom = cloud.clean_custom((query.get("prompt") or [""])[0]) if subject == 'custom' else ''
            detail = (query.get("detail") or ["simple"])[0]
            cloud.build_prompt(subject, custom, detail)
            cloud_options = dict(subject=subject, custom=custom, detail=detail)
        kind = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if kind not in ALLOWED_TYPES:
            raise ValueError("只接受 JPEG / PNG / WebP 图片")
        total = int(self.headers.get("Content-Length") or 0)
        if total <= 0 or self.headers.get('Transfer-Encoding'):
            raise ValueError("空文件")
        if total > MAX_UPLOAD:
            self.close_connection = True
            raise ValueError("图片需小于 20 MB")
        self.hub.touch_client(cid, self.headers.get("User-Agent"), "uploading", None, self.client_address[0])
        upload_id = uuid.uuid4().hex[:8]
        name = self.hub.clients.get(cid, {}).get("name", "手机")
        self.hub.publish("progress", dict(upload=upload_id, cid=cid, source=name, received=0, total=total))
        self.body_read = True  # 从这里开始自己读请求体；之前的拒绝由 send() 统一读完再回复
        buf = bytearray()
        last = 0.0
        while len(buf) < total:
            chunk = self.rfile.read(min(65536, total - len(buf)))
            if not chunk:
                break
            buf += chunk
            now = time.monotonic()
            if now - last > 0.08:
                last = now
                self.hub.publish("progress", dict(upload=upload_id, cid=cid, source=name,
                                                  received=len(buf), total=total))
        if len(buf) != total:
            self.hub.publish("progress", dict(upload=upload_id, cid=cid, source=name, received=len(buf),
                                              total=total, failed=True))
            self.hub.touch_client(cid, None, "idle")
            raise ValueError("上传中断")
        raw = bytes(buf)
        if self.hub.workflow:
            self.hub.workflow.mark(reservation, 'upload_received')
        if not self.sniff(raw, kind):
            self.hub.touch_client(cid, None, "idle")
            raise ValueError("文件内容与图片格式不符")
        meta = validate_image(raw, kind)
        if self.hub.workflow:
            self.hub.workflow.mark(reservation, 'validated')
        frame = self.hub.add_frame(raw, kind, cid, meta)
        workflow = (self.hub.workflow.submit(reservation, raw, frame, input_mode=input_mode, cloud_options=cloud_options)
                    if self.hub.workflow else None)
        self.hub.publish("progress", dict(upload=upload_id, cid=cid, source=name, received=total, total=total,
                                          done=True, frame=frame["id"]))
        self.hub.touch_client(cid, None, "idle")
        return self.send(200, dict(ok=True, frame=frame, workflow=workflow,
                                   job_id=workflow['job_id'] if workflow else None))

    @staticmethod
    def sniff(raw, kind):
        if kind == "image/jpeg":
            return raw[:3] == b"\xff\xd8\xff"
        if kind == "image/png":
            return raw[:8] == b"\x89PNG\r\n\x1a\n"
        return raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"


def parse_screen_host(value):
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        raise ValueError(f"--screen-host 需要 IP 地址：{value!r}")


class DisplayServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, hub, host_ips=None, public_url=None, verbose=False, interfaces=None,
                 screen_hosts=None, workflow=None, lineart_library=None, audio_service=None):
        super().__init__(address, Handler)
        self.hub = hub
        self.hub.workflow = workflow
        if audio_service is None:
            from audio_player.service import AudioService
            audio_service = AudioService()
        self.audio = audio_service
        if workflow and hasattr(workflow, 'set_audio_service'):
            workflow.set_audio_service(audio_service)
        if lineart_library is None:
            from user_gui.lineart_library import LineartLibrary
            from cloud_gallery import default_gallery_dir
            data_dir = workflow.directory.parent if workflow else Path(hub.upload_dir).parent
            lineart_library = LineartLibrary(data_dir / 'lineart_library',
                                            [data_dir / 'cloud_images', default_gallery_dir()])
        self.lineart_library = lineart_library
        from user_gui.hwr import Recognizer
        self.hwr = Recognizer()          # 手写识字: loaded on first use, or warmed by main()
        if workflow:
            workflow.publish = self.hub.publish
        self.screen_hosts = {parse_screen_host(h) for h in (screen_hosts or [])}
        self.bind_host = address[0]
        self.host_ips = list(host_ips or [])
        self.public_url = public_url
        self.verbose = verbose
        self.instance = secrets.token_hex(4)
        self._fixed = interfaces
        self.refresh_interfaces()
        self.stopping = threading.Event()
        threading.Thread(target=self._reaper, daemon=True).start()

    def refresh_interfaces(self):
        found = list(self._fixed) if self._fixed is not None else netinfo.interfaces()
        manual = []
        for ip in self.host_ips:
            try:
                manual.append(netinfo.manual_interface(ip))
            except ValueError:
                pass
        manual_ips = {m["ip"] for m in manual}
        for m in manual:  # 手动地址若与真实网卡相同，沿用真实子网信息
            real = next((f for f in found if f["ip"] == m["ip"]), None)
            if real:
                m.update({k: real[k] for k in ("prefix", "cidr", "guessed", "adapter", "kind", "gateway")})
        self.interfaces = manual + [f for f in found if f["ip"] not in manual_ips]
        return self.interfaces

    def urls(self):
        port = self.server_address[1]
        q = f"?t={self.hub.token}" if self.hub.token else ""
        out = [self.public_url] if self.public_url else []
        return out + [f"http://{i['ip']}:{port}/upload{q}" for i in self.interfaces]

    def _reaper(self):
        while not self.stopping.wait(3):
            self.hub.reap()

    def shutdown(self):
        self.stopping.set()
        if self.hub.workflow:
            self.hub.workflow.close()
        self.audio.close()
        super().shutdown()


def main():
    env_ips = [x.strip() for x in os.environ.get("SO101_HOST_IP", "").split(",") if x.strip()]
    env_screens = [x.strip() for x in os.environ.get("SO101_SCREEN_HOST", "").split(",") if x.strip()]
    ap = argparse.ArgumentParser(description="SO-101 板端屏幕孪生 + 手机上传")
    ap.add_argument("--port", type=int, default=int(os.environ.get("SO101_PORT", 8090)))
    ap.add_argument("--bind", "--host", default="0.0.0.0", help="监听地址（默认所有网卡，手机才能访问）")
    ap.add_argument("--host-ip", action="append", default=env_ips,
                    help="手动指定二维码里的 IP，可重复；也可用环境变量 SO101_HOST_IP=ip1,ip2")
    ap.add_argument("--public-url", default=os.environ.get("SO101_PUBLIC_URL"),
                    help="完整的手机访问地址（如端口转发 / 隧道），优先用于二维码")
    ap.add_argument("--pair-token", nargs="?", const="", default=None, metavar="CODE",
                    help="要求配对码；不给值则随机生成")
    ap.add_argument("--screen-host", action="append", default=env_screens, metavar="IP",
                    help="允许这台设备打开屏幕页（如驱动 7 寸屏的板卡），可重复；也可用环境变量 SO101_SCREEN_HOST")
    ap.add_argument("--uploads", default=str(ROOT / "uploads"))
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument('--workflow', action='store_true', help='启用板端云端生成、笔画提取和真实轨迹规划')
    ap.add_argument('--backend-url', default='http://127.0.0.1:8765')
    ap.add_argument('--data-dir', type=Path, default=Path('/home/xilinx/so101_data_work107'))
    ap.add_argument('--secrets-file', type=Path, default=Path('/home/xilinx/.config/so101/secrets.local.json'))
    ap.add_argument('--servo-port', default='/dev/ttyACM0')
    ap.add_argument('--stroke-profile', choices=('sugar', 'faithful'), default='sugar',
                    help='糖画模式过滤碎线；faithful 保留原始中心线')
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    token = None if args.pair_token is None else (args.pair_token or secrets.token_urlsafe(18))
    if args.workflow and token is None:
        token = secrets.token_urlsafe(18)
    upload_dir = args.data_dir / 'user_gui_uploads' if args.workflow and args.uploads == str(ROOT / 'uploads') else args.uploads
    hub = Hub(upload_dir, token=token)
    workflow = None
    if args.workflow:
        workflow = Workflow(BoardPipeline(args.backend_url, args.data_dir, args.secrets_file,
                                          port=args.servo_port, stroke_profile=args.stroke_profile), args.data_dir, hub.publish)
        hub.display.update(width=1024, height=600)
    try:
        server = DisplayServer((args.bind, args.port), hub, host_ips=args.host_ip, public_url=args.public_url,
                               verbose=args.verbose, screen_hosts=args.screen_host, workflow=workflow)
    except ValueError as exc:
        print(exc)
        sys.exit(2)
    except OSError as exc:
        print(f"端口 {args.port} 无法监听：{exc}\n换一个端口试试：python display_server.py --port 8091")
        sys.exit(1)
    local = f"http://127.0.0.1:{args.port}/"
    print("=" * 60)
    print("  SO-101 板端屏幕孪生")
    print(f"  屏幕页（在本机打开）: {local}")
    for h in sorted(server.screen_hosts):
        print(f"  屏幕页（{h} 上打开）: http://<本机局域网IP>:{args.port}/")
    print(f"  访问控制: {'配对码' if token else '仅局域网，无需配对码'}")
    for i, url in enumerate(server.urls()):
        iface = server.interfaces[i - (1 if args.public_url else 0)] if (i or not args.public_url) else None
        tag = f"  [{iface['adapter'] or '未知网卡'} · {iface['cidr']} · {iface['kind']}]" if iface else "  [手动 URL]"
        print(f"  手机上传: {url}{tag}")
    print("  Ctrl+C 退出")
    print("=" * 60)
    if not args.no_browser:
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(local)).start()
    def request_shutdown(*_):
        # shutdown must run outside serve_forever's thread.
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, request_shutdown)
    server.hwr.warm()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stopping.set()
        if workflow:
            workflow.close()
        server.audio.close()
        server.server_close()


if __name__ == "__main__":
    main()
