"""python -m unittest discover -s tests"""
import io
from PIL import Image
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import display_server as ds  # noqa: E402
import netinfo  # noqa: E402

FAKE_IFACES = netinfo.rank([dict(ip="10.0.0.23", prefix=16, adapter="Wi-Fi", gateway=True),
                            dict(ip="172.25.160.1", prefix=20, adapter="vEthernet (WSL)", gateway=False)])
_image = io.BytesIO()
Image.new("RGB", (800, 480), "white").save(_image, "JPEG")
JPEG = _image.getvalue()


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hub = ds.Hub(self.tmp.name, token="testtoken")
        self.srv = ds.DisplayServer(("127.0.0.1", 0), self.hub, host_ips=["192.168.9.9"], interfaces=FAKE_IFACES)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close(); self.tmp.cleanup()

    def req(self, path, body=None, kind="application/json"):
        data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
        r = urllib.request.Request(self.base + path, data=data, headers={"Content-Type": kind, "X-Screen-Token": self.hub.control_token} if data is not None else {})
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_pages(self):
        self.assertEqual(self.req("/")[0], 200)
        self.assertEqual(self.req("/upload?t=testtoken")[0], 200)
        self.assertEqual(self.req("/debug")[0], 200)
        self.assertEqual(self.req("/m?t=testtoken")[0], 200)
        self.assertEqual(self.req("/upload")[0], 403)
        self.assertEqual(self.req("/static/../display_server.py")[0], 404)
        self.assertEqual(self.req('/handwriting')[0],200)

    def test_handwriting_requires_screen_token_and_forwards_once(self):
        calls=[]
        def forward(path,**kwargs):calls.append((path,kwargs));return {'phase':'PREPARING'}
        self.hub.workflow=types.SimpleNamespace(close=lambda:None,pipeline=types.SimpleNamespace(client=types.SimpleNamespace(_request=forward)))
        raw=json.dumps({'size_mm':60}).encode()
        req=urllib.request.Request(self.base+'/api/handwriting/open',data=raw,headers={'Content-Type':'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(req,timeout=5)
        self.assertEqual(e.exception.code,403);self.assertEqual(calls,[])
        code,body=self.req('/api/handwriting/open',{'size_mm':60})
        self.assertEqual(code,200);self.assertEqual(json.loads(body)['phase'],'PREPARING')
        self.assertEqual(len(calls),1);self.assertEqual(calls[0][1]['method'],'POST')
        self.assertEqual(self.req('/api/handwriting/stroke',b'[]')[0],400)
        self.assertEqual(self.req('/api/handwriting/stroke',b' '*131073)[0],400)
        self.assertEqual(len(calls),1)

    def test_network_info(self):
        d = json.loads(self.req("/api/state")[1])["pair"]
        self.assertEqual(d["access"], "token")
        self.assertEqual([i["ip"] for i in d["interfaces"]], ["192.168.9.9", "10.0.0.23", "172.25.160.1"])
        self.assertTrue(d["interfaces"][0]["manual"])
        self.assertEqual(d["interfaces"][1]["cidr"], "10.0.0.0/16")
        self.assertEqual(d["interfaces"][2]["kind"], "virtual")
        port = self.srv.server_address[1]
        self.assertEqual(self.srv.urls()[0], f"http://192.168.9.9:{port}/upload?t=testtoken")
        code, raw = self.req("/api/ping")
        self.assertEqual(json.loads(raw)["instance"], self.srv.instance)

    def test_hello_and_upload(self):
        code, raw = self.req("/api/hello?t=testtoken", {"cid": "abc12345", "state": "editing"})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)["display"]["width"], 800)
        q = self.hub.subscribe()
        code, raw = self.req("/api/upload?t=testtoken&cid=abc12345&w=800&h=480", JPEG, "image/jpeg")
        self.assertEqual(code, 200, raw)
        frame = json.loads(raw)["frame"]
        self.assertEqual(frame["src_width"], 800)
        events = []
        while not q.empty():
            events.append(q.get_nowait().decode().split("\n")[0])
        self.assertIn("event: frame", events)
        self.assertIn("event: progress", events)
        code, raw = self.req(frame["url"])
        self.assertEqual((code, raw), (200, JPEG))

    def test_upload_rejects(self):
        self.assertEqual(self.req("/api/upload?t=bad&cid=abc12345", JPEG, "image/jpeg")[0], 403)
        self.assertEqual(self.req("/api/upload?t=testtoken&cid=abc12345", b"GIF89a....", "image/gif")[0], 400)
        self.assertEqual(self.req("/api/upload?t=testtoken&cid=abc12345", b"notajpeg", "image/jpeg")[0], 400)

    def test_display_validation(self):
        code, raw = self.req("/api/display", {"width": 1024, "height": 600, "format": "gray8"})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)["format"], "gray8")
        self.assertEqual(self.req("/api/display", {"rotation": 45})[0], 400)
        self.assertEqual(self.req("/api/display", {"format": "yuv"})[0], 400)

    def test_token_rotation(self):
        code, raw = self.req("/api/token", {})
        new = json.loads(raw)["token"]
        self.assertNotEqual(new, "testtoken")
        self.assertEqual(self.req("/api/hello?t=testtoken", {"cid": "abc12345"})[0], 403)

    def test_history_trimmed(self):
        self.hub.keep = 3
        for _ in range(5):
            self.req("/api/upload?t=testtoken&cid=abc12345", JPEG, "image/jpeg")
        self.assertEqual(len(self.hub.frames), 3)
        self.assertEqual(len(list(Path(self.tmp.name).iterdir())), 3)


class OpenModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.srv = ds.DisplayServer(("127.0.0.1", 0), ds.Hub(self.tmp.name), interfaces=FAKE_IFACES)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close(); self.tmp.cleanup()

    def test_plain_upload_url(self):
        port = self.srv.server_address[1]
        self.assertEqual(self.srv.urls()[0], f"http://10.0.0.23:{port}/upload")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/upload", timeout=5) as r:
            self.assertEqual(r.status, 200)

    def test_screen_hosts(self):
        # 屏幕页默认只给本机；--screen-host 列出的设备（如驱动 7 寸屏的板卡）也放行
        srv = types.SimpleNamespace(hub=types.SimpleNamespace(workflow=None), screen_hosts={ds.parse_screen_host(" 192.168.1.50 ")})
        def screen(ip):
            h = types.SimpleNamespace(client_address=(ip, 0), server=srv, hub=srv.hub)
            h.is_local = lambda: ds.Handler.is_local(h)
            return ds.Handler.is_screen(h)
        for ip, ok in (("127.0.0.1", True), ("192.168.1.50", True), ("::ffff:192.168.1.50", True),
                       ("192.168.1.51", False), ("10.0.0.23", False)):
            self.assertEqual(screen(ip), ok, ip)
        with self.assertRaises(ValueError):
            ds.parse_screen_host("board.local")
        code = urllib.request.urlopen(f"http://127.0.0.1:{self.srv.server_address[1]}/api/state", timeout=5).status
        self.assertEqual(code, 200)

    def test_lan_filter(self):
        for ip, ok in (("192.168.1.5", True), ("10.1.2.3", True), ("172.20.0.9", True), ("127.0.0.1", True),
                       ("fe80::1", True), ("::ffff:192.168.1.5", True), ("8.8.8.8", False), ("2606:4700::1111", False)):
            self.assertEqual(netinfo.is_lan_client(ip), ok, ip)


class NetinfoTest(unittest.TestCase):
    CN = """
以太网适配器 以太网:

   IPv4 地址 . . . . . . . . . . . . : 192.168.2.10
   子网掩码  . . . . . . . . . . . . : 255.255.255.0
   默认网关. . . . . . . . . . . . . :

无线局域网适配器 WLAN:

   IPv4 地址 . . . . . . . . . . . . : 192.168.1.105
   子网掩码  . . . . . . . . . . . . : 255.255.255.0
   默认网关. . . . . . . . . . . . . : fe80::1%7
                                       192.168.1.1
"""

    def test_ipconfig_cn(self):
        rows = netinfo.rank(netinfo.parse_ipconfig(self.CN))
        self.assertEqual(rows[0]["ip"], "192.168.1.105")
        self.assertTrue(rows[0]["gateway"])
        self.assertEqual(rows[1]["cidr"], "192.168.2.0/24")

    def test_same_subnet(self):
        iface = netinfo.rank([dict(ip="192.168.1.105", prefix=24, adapter="WLAN")])[0]
        self.assertTrue(netinfo.same_subnet("192.168.1.77", iface))
        self.assertFalse(netinfo.same_subnet("192.168.2.77", iface))


if __name__ == "__main__":
    unittest.main()
