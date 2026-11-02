"""Sealed local recordings; no network requests or arbitrary file paths."""
import hashlib
import json
from pathlib import Path
from .player import load_wav

DEFAULT = Path(__file__).resolve().parents[1] / 'data/audio/manifest.json'


class Catalog:
    def __init__(self, path=DEFAULT):
        self.path = Path(path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if data.get('schema') != 'tcb705-readings-v1':
            raise ValueError('朗读目录版本不正确')
        self.items = {}
        for item in data['items']:
            key = item['id']
            name = item['wav']
            if key in self.items or Path(name).name != name or '/' in name or '\\' in name:
                raise ValueError('朗读目录包含重复编号或非法文件路径')
            last = 0.0
            for seg in item['timeline']:
                if not (last <= seg['start'] < seg['end'] <= item['duration_s']):
                    raise ValueError('朗读时间轴不正确：' + key)
                last = seg['end']
            self.items[key] = item

    def public(self):
        return [dict((k, v) for k, v in item.items() if k not in ('wav', 'sha256'))
                for item in self.items.values()]

    def load(self, key):
        if key not in self.items:
            raise ValueError('未找到所选诗文')
        item = self.items[key]
        path = self.path.parent / item['wav']
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('朗读音频校验失败，请重新安装：' + item.get('title', key))
        samples = load_wav(path)
        if abs(len(samples) / 48000.0 - item['duration_s']) > 1 / 48000.0:
            raise ValueError('朗读时长与目录不一致')
        return item, samples
