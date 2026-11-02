"""Persistent PC library of cloud line art; preserve the returned image bytes."""
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from PIL import Image

FORMATS = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp',
           'BMP': '.bmp', 'GIF': '.gif'}


def default_gallery_dir():
    # This location survives temporary-file cleanup and runtime ZIP upgrades.
    return Path.home() / 'Pictures' / 'SO101' / 'CloudImages'


def _image_details(raw):
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in FORMATS:
            raise ValueError('不支持的云端图片格式')
        if image.width * image.height > 16000000:
            raise ValueError('云端图片超过 1600 万像素')
        details = dict(format=image.format, width=image.width, height=image.height)
        image.verify()
    return details


def _atomic_write(path, raw):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as file:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


class CloudImageLibrary:
    def __init__(self, directory=None):
        self.directory = Path(directory or default_gallery_dir()).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, raw, *, profile='', model='', subject='', source_name='',
             created_at=None, imported=False):
        details = _image_details(raw)
        created = created_at or datetime.now().astimezone()
        label = re.sub(r'[^a-zA-Z0-9_-]', '_', profile)[:24] or 'cloud'
        name = '%s_%s_%s%s' % (created.strftime('%Y%m%d_%H%M%S_%f'), label,
                               uuid.uuid4().hex[:8], FORMATS[details['format']])
        path = self.directory / name
        metadata = dict(schema='so101-cloud-image-v1', filename=name,
                        created_at=created.isoformat(), profile=str(profile), model=str(model),
                        subject=str(subject), source_name=Path(source_name).name,
                        imported=bool(imported), sha256=hashlib.sha256(raw).hexdigest(), **details)
        _atomic_write(path, raw)
        # No API keys, configuration, URLs or raw API responses enter the library.
        _atomic_write(path.with_suffix('.json'),
                      (json.dumps(metadata, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        return dict(metadata, path=path)

    def records(self):
        records = []
        for path in self.directory.iterdir():
            if not path.is_file() or path.suffix.lower() not in set(FORMATS.values()) | {'.jpeg'}:
                continue
            try:
                metadata = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
                if not isinstance(metadata, dict):
                    metadata = {}
            except (OSError, ValueError):
                metadata = {}
            try:
                # Also recover images whose sidecar was lost or interrupted.
                with Image.open(path) as image:
                    if image.format not in FORMATS:
                        continue
                    details = dict(format=image.format, width=image.width, height=image.height)
                    image.verify()
            except (OSError, ValueError, Image.DecompressionBombError):
                continue
            try:
                created = datetime.fromisoformat(metadata.get('created_at', ''))
                if created.tzinfo is None:
                    created = created.astimezone()
            except (TypeError, ValueError):
                created = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
            records.append(dict(filename=path.name, path=path, created_at=created.isoformat(),
                                profile=str(metadata.get('profile', '')),
                                model=str(metadata.get('model', '')),
                                subject=str(metadata.get('subject', '')),
                                source_name=str(metadata.get('source_name', '')),
                                imported=bool(metadata.get('imported', False)),
                                sha256=str(metadata.get('sha256', '')), **details))
        return sorted(records, key=lambda item: (datetime.fromisoformat(item['created_at']).timestamp(),
                                                item['filename']), reverse=True)

    def import_legacy(self, temporary_directory):
        """Recover previous ArmStudio cloud outputs, deduplicating their contents."""
        seen = {hashlib.sha256(item['path'].read_bytes()).hexdigest() for item in self.records()}
        result = dict(imported=0, already_present=0, invalid=0)
        for path in sorted(Path(temporary_directory).glob('so101_cloud_*/lineart.*')):
            if not path.is_file():
                continue
            try:
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                if digest in seen:
                    result['already_present'] += 1
                    continue
                self.save(raw, profile='legacy', source_name=path.name, imported=True,
                          created_at=datetime.fromtimestamp(path.stat().st_mtime).astimezone())
                seen.add(digest)
                result['imported'] += 1
            except (OSError, ValueError, Image.DecompressionBombError):
                result['invalid'] += 1
        return result

    @staticmethod
    def export(source, destination):
        source, destination = Path(source), Path(destination)
        suffixes = {source.suffix.lower()}
        if source.suffix.lower() in ('.jpg', '.jpeg'):
            suffixes.update(('.jpg', '.jpeg'))
        if destination.suffix.lower() not in suffixes:
            raise ValueError('请沿用原图片扩展名 %s，以保留原始画质' % source.suffix)
        if source.resolve() != destination.resolve():
            shutil.copyfile(source, destination)
        return destination
