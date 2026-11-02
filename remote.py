"""Loopback-only PC gateway to the board over an SSH local forward."""
import http.client
import json
from urllib.parse import urlsplit


class Board:
    def __init__(self, url):
        p = urlsplit(url)
        if p.scheme != 'http' or p.hostname != '127.0.0.1' or not p.port or p.path not in ('', '/') or p.query or p.fragment or p.username:
            raise ValueError('--board-url 使用 SSH 转发地址，例如 http://127.0.0.1:8768')
        self.port = p.port
        self.token = None; self.session = None

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        outgoing = dict(headers or {})
        if method == 'POST':
            if not self.token:
                raise ValueError('先刷新页面，连接板端会话')
            outgoing['X-Console-Token'] = self.token
        try:
            connection.request(method, path, body=body, headers=outgoing)
            response = connection.getresponse()
            raw = response.read(128000001)
            if len(raw) > 128000000:
                raise ValueError('板端响应超过 128 MB，请从板端复制日志')
            return response.status, raw, response.getheader('Content-Type', 'application/json')
        except (OSError, http.client.HTTPException):
            raise ValueError('未连接 Z20：检查网线、SSH 转发及板端服务') from None
        finally:
            connection.close()

    def status(self):
        code, raw, _ = self.request('GET', '/api/status')
        if code != 200:
            raise ValueError('板端状态读取失败')
        data = json.loads(raw)
        self.token, self.session = data['token'], data['session_id']
        return data
