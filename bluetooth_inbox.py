"""Validated, persistent Bluetooth image inbox; receiving never starts a job."""
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import uuid
import warnings

from PIL import Image

MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_PIXELS = 16000000
MAX_LIBRARY_BYTES = 512 * 1024 * 1024
MAX_LIBRARY_IMAGES = 200
FORMATS = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp',
           'BMP': '.bmp', 'GIF': '.gif'}
SCHEMA = 'so101-bluetooth-image-v1'
_ID = re.compile(r'^[0-9a-f]{32}$')


def _label(value, limit=200):
    return ''.join(c for c in str(value) if c.isprintable())[:limit]


def _image_details(raw):
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError('图片大小须在 1 字节到 32 MiB 之间')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in FORMATS:
                    raise ValueError('仅接收 PNG、JPEG、WebP、BMP、GIF 图片')
                if not 0 < image.width * image.height <= MAX_IMAGE_PIXELS:
                    raise ValueError('图片超过 1600 万像素，请先缩小图片')
                if getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('请发送静态图片，暂不接收动画')
                details = dict(format=image.format, width=image.width, height=image.height)
                image.verify()
            # verify() alone does not decode JPEG pixel data or catch every truncation.
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ValueError('图片像素过大，请先缩小图片') from exc
    return details


def _atomic_write(path, raw):
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_regular(path, limit):
    """Read a bounded regular file, refusing symlinks and device nodes."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError('不能接收符号链接')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(str(path), flags)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError('文件类型或大小无效')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('文件过大')
    return raw


class BluetoothInbox:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def import_file(self, path, *, source_name='', sender=''):
        path = Path(path)
        return self.import_bytes(_read_regular(path, MAX_IMAGE_BYTES),
                                 source_name=source_name or path.name, sender=sender)

    def import_bytes(self, raw, *, source_name='', sender=''):
        raw = bytes(raw)
        details = _image_details(raw)
        records = self.records()
        used = sum(p.stat().st_size for p in self.directory.iterdir()
                   if p.is_file() and not p.is_symlink())
        if len(records) >= MAX_LIBRARY_IMAGES or used + len(raw) > MAX_LIBRARY_BYTES:
            raise ValueError('蓝牙接收箱已满，请先备份并清理旧图片')
        if shutil.disk_usage(self.directory).free < len(raw) + 8 * 1024 * 1024:
            raise ValueError('存储空间不足，无法保存图片')
        identity = uuid.uuid4().hex
        filename = identity + FORMATS[details['format']]
        path = self.directory / filename
        metadata = dict(schema=SCHEMA, id=identity, filename=filename,
                        received_at=datetime.now().astimezone().isoformat(),
                        source_name=_label(str(source_name).replace('\\', '/').rsplit('/', 1)[-1]),
                        sender=_label(sender, 80), size=len(raw),
                        sha256=hashlib.sha256(raw).hexdigest(), **details)
        _atomic_write(path, raw)
        try:
            # The sidecar is the commit marker. Partial transfers never enter records().
            _atomic_write(path.with_suffix('.json'),
                          (json.dumps(metadata, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        except Exception:
            path.unlink()
            raise
        return dict(metadata, path=path)

    def _record(self, identity):
        if not isinstance(identity, str) or not _ID.fullmatch(identity):
            raise ValueError('图片编号无效')
        metadata = json.loads(_read_regular(self.directory / (identity + '.json'), 16384).decode('utf-8'))
        if not isinstance(metadata, dict) or metadata.get('schema') != SCHEMA or metadata.get('id') != identity:
            raise ValueError('图片记录无效')
        suffix = FORMATS.get(metadata.get('format'))
        if not suffix or metadata.get('filename') != identity + suffix:
            raise ValueError('图片路径无效')
        path = self.directory / metadata['filename']
        if path.is_symlink() or not path.is_file() or path.resolve().parent != self.directory:
            raise ValueError('图片文件无效')
        if not isinstance(metadata.get('size'), int) or not 0 < metadata['size'] <= MAX_IMAGE_BYTES:
            raise ValueError('图片大小无效')
        if path.stat().st_size != metadata['size']:
            raise ValueError('图片文件已改变')
        width, height = metadata.get('width'), metadata.get('height')
        if not isinstance(width, int) or not isinstance(height, int) or min(width, height) <= 0 or width * height > MAX_IMAGE_PIXELS:
            raise ValueError('图片尺寸无效')
        if not re.fullmatch(r'[0-9a-f]{64}', str(metadata.get('sha256', ''))):
            raise ValueError('图片校验记录无效')
        datetime.fromisoformat(metadata['received_at'])
        for key in ('source_name', 'sender'):
            metadata[key] = _label(metadata.get(key, ''))
        return dict(metadata, path=path)

    def records(self):
        records = []
        for sidecar in self.directory.glob('*.json'):
            try:
                records.append(self._record(sidecar.stem))
            except (OSError, ValueError, TypeError, KeyError):
                continue
        return sorted(records, key=lambda record: (record['received_at'], record['id']), reverse=True)

    def get(self, identity):
        """Revalidate original bytes at selection time, before changing an active job."""
        record = self._record(identity)
        raw = _read_regular(record['path'], MAX_IMAGE_BYTES)
        if hashlib.sha256(raw).hexdigest() != record['sha256']:
            raise ValueError('图片内容已改变，请重新传送')
        details = _image_details(raw)
        if any(record[key] != value for key, value in details.items()):
            raise ValueError('图片记录与内容不一致')
        return record
