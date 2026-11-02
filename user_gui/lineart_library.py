"""Local artwork catalogue. Only configured artwork folders are exposed."""
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import threading

from PIL import Image, ImageOps

from .workflow import validate_image

TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
MAX_BYTES = 20 * 1024 * 1024


class LineartLibrary:
    def __init__(self, directory, sources=()):
        self.directory = Path(directory).resolve()
        self.roots = list(dict.fromkeys([self.directory] + [Path(p).resolve() for p in sources]))
        self.lock = threading.RLock()
        self.cache = {}
        self.index = {}
        self.thumbnails = {}

    def records(self):
        with self.lock:
            found = {}
            live = set()
            for root in self.roots:
                if not root.is_dir():
                    continue
                for candidate in root.rglob('*'):
                    if candidate.suffix.lower() not in TYPES or not candidate.is_file():
                        continue
                    try:
                        path = candidate.resolve()
                        path.relative_to(root)
                        if candidate.is_symlink():
                            continue
                        stat = path.stat()
                        if not 0 < stat.st_size <= MAX_BYTES:
                            continue
                        key = (str(path), stat.st_mtime_ns, stat.st_size)
                        live.add(key)
                        if key not in self.cache:
                            raw = path.read_bytes()
                            kind = TYPES[path.suffix.lower()]
                            meta = validate_image(raw, kind)
                            digest = hashlib.sha256(raw).hexdigest()
                            label = path.stem
                            created = stat.st_mtime
                            try:
                                sidecar = json.loads(path.with_suffix('.json').read_text('utf-8'))
                                label = str(sidecar.get('display_name') or sidecar.get('source_name') or label)
                                if sidecar.get('created_at'):
                                    created = datetime.fromisoformat(sidecar['created_at']).timestamp()
                            except (OSError, ValueError, TypeError, AttributeError):
                                pass
                            if label.lower() in ('lineart.png', 'lineart.jpg', 'lineart.webp') or re.match(r'^(?:[0-9a-f]{20,}\.|20\d{6}_)', label):
                                label = '线稿 · ' + datetime.fromtimestamp(created, timezone(timedelta(hours=8))).strftime('%m-%d %H:%M')
                            self.cache[key] = dict(id=digest, name=label[:160], filename=path.name,
                                width=meta['w'], height=meta['h'], bytes=len(raw), modified=created,
                                kind=kind, path=path)
                        item = self.cache[key]
                        found.setdefault(item['id'], item)
                    except (OSError, ValueError, Image.DecompressionBombError):
                        continue
            self.cache = {k: v for k, v in self.cache.items() if k in live}
            self.index = found
            self.thumbnails = {k: v for k, v in self.thumbnails.items() if k in found}
            return [self.public(v) for v in sorted(found.values(), key=lambda x: (x['modified'], x['filename']), reverse=True)]

    @staticmethod
    def public(item):
        out = {k: v for k, v in item.items() if k != 'path'}
        out['thumbnail'] = '/api/lineart-library/image/' + item['id'] + '?thumbnail=1'
        out['url'] = '/api/lineart-library/image/' + item['id']
        return out

    def read(self, identity, thumbnail=False):
        if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{64}', identity):
            raise ValueError('无效的线稿编号')
        with self.lock:
            self.records()
            item = self.index.get(identity)
            if not item:
                raise ValueError('这张线稿已变更或移走，请刷新图库')
            if thumbnail and identity in self.thumbnails:
                return self.thumbnails[identity], 'image/png'
            path = item['path']
            if path.is_symlink() or not any(root == path.parent or root in path.resolve().parents for root in self.roots):
                raise ValueError('线稿不在图库目录中')
            with path.open('rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
            if hashlib.sha256(raw).hexdigest() != identity:
                raise ValueError('线稿已变更，请刷新图库后重新选择')
            validate_image(raw, item['kind'])
            if thumbnail:
                with Image.open(io.BytesIO(raw)) as original:
                    im = ImageOps.exif_transpose(original).convert('RGBA')
                    im.thumbnail((280, 200))
                    canvas = Image.new('RGB', im.size, '#fffaf0')
                    canvas.paste(im, mask=im.getchannel('A'))
                    result = io.BytesIO(); canvas.save(result, 'PNG')
                if len(self.thumbnails) >= 128:
                    self.thumbnails.pop(next(iter(self.thumbnails)))
                self.thumbnails[identity] = result.getvalue()
                return result.getvalue(), 'image/png'
            return raw, item['kind']

    def save(self, raw, kind, name):
        if len(raw) > MAX_BYTES:
            raise ValueError('图片需小于 20 MB')
        validate_image(raw, kind)
        digest = hashlib.sha256(raw).hexdigest()
        with self.lock:
            self.records()
            if digest in self.index:
                return self.public(self.index[digest])
            self.directory.mkdir(parents=True, exist_ok=True)
            suffix = {v: k for k, v in TYPES.items()}[kind]
            path = self.directory / (digest + suffix)
            from cloud_gallery import _atomic_write
            _atomic_write(path, raw)
            label = str(name).replace('\\', '/').rsplit('/', 1)[-1][:160] or '导入线稿'
            _atomic_write(path.with_suffix('.json'), json.dumps({'display_name': label}, ensure_ascii=False).encode('utf-8'))
            self.records()
            return self.public(self.index[digest])
