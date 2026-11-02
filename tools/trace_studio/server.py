"""名帖描红工作台: local server for hand-tracing masterpiece brush paths (build machine only).

Serves index.html, the high-resolution character images and manifest.json from
this folder, and saves every traced character to annotations/<work>/<NN>.json
as soon as a stroke is finished. Only listens on 127.0.0.1. Standard library only.

  python server.py [--port 8766]
"""
import argparse
import json
import mimetypes
import os
import re
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
ANN = HERE / 'annotations'
NAME = re.compile(r'^[a-z0-9_]{1,32}$')
LOCK = threading.Lock()


def ann_path(work, index):
    if not NAME.match(work) or not 0 <= index < 100:
        raise ValueError('bad character id')
    return ANN / work / ('%02d.json' % index)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        m = re.match(r'^/api/ann/([a-z0-9_]+)/(\d+)$', path)
        if m:
            try:
                p = ann_path(m.group(1), int(m.group(2)))
            except ValueError as exc:
                return self.send(400, {'error': str(exc)})
            return self.send(200, json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'strokes': []})
        if path == '/api/progress':
            done = {}
            for f in ANN.glob('*/*.json'):
                try:
                    done['%s/%s' % (f.parent.name, f.stem)] = len(json.loads(f.read_text(encoding='utf-8')).get('strokes', []))
                except (OSError, ValueError):
                    pass
            return self.send(200, done)
        rel = 'index.html' if path in ('/', '') else path.lstrip('/')
        f = (HERE / rel).resolve()
        if HERE not in f.parents or not f.is_file() or f.suffix not in ('.html', '.js', '.css', '.json', '.png', '.jpg'):
            return self.send(404, {'error': 'not found'})
        self.send(200, f.read_bytes(), (mimetypes.guess_type(f.name)[0] or 'application/octet-stream') +
                  ('; charset=utf-8' if f.suffix in ('.html', '.js', '.css', '.json') else ''))

    def do_POST(self):
        m = re.match(r'^/api/ann/([a-z0-9_]+)/(\d+)$', urlparse(self.path).path)
        if not m:
            return self.send(404, {'error': 'not found'})
        try:
            p = ann_path(m.group(1), int(m.group(2)))
            n = int(self.headers.get('Content-Length', 0))
            if not 0 < n <= 4_000_000:
                raise ValueError('bad size')
            data = json.loads(self.rfile.read(n).decode('utf-8'))
            strokes = data.get('strokes')
            if not isinstance(strokes, list) or len(strokes) > 80:
                raise ValueError('bad strokes')
            for s in strokes:
                pts = s.get('points')
                if not isinstance(pts, list) or not 1 <= len(pts) <= 20000:
                    raise ValueError('bad stroke')
                for q in pts:
                    if not (isinstance(q, list) and 3 <= len(q) <= 4 and all(isinstance(v, (int, float)) for v in q)):
                        raise ValueError('bad point')
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            return self.send(400, {'error': str(exc)})
        record = dict(work=m.group(1), index=int(m.group(2)), character=data.get('character', ''),
                      canvas_px=1024, units='px on the 1024 x 1024 image; [x, y, t_ms, pressure]',
                      saved=time.strftime('%Y-%m-%d %H:%M:%S'), strokes=strokes)
        with LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix('.tmp')
            tmp.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
            os.replace(tmp, p)
        self.send(200, {'saved': record['saved'], 'strokes': len(strokes)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8766)
    ap.add_argument('--no-browser', action='store_true')
    args = ap.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    url = 'http://127.0.0.1:%d/' % args.port
    print('名帖描红工作台已启动：%s （关闭此窗口即退出）' % url, flush=True)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == '__main__':
    main()
