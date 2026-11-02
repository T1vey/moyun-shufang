"""Bluetooth image validation and explicit selection, without radio or motion."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from bluetooth_inbox import BluetoothInbox
from test_cloud_gallery import gallery_studio


def image_bytes(format='PNG', color='black'):
    buffer = io.BytesIO()
    Image.new('RGB', (32, 24), color).save(buffer, format=format)
    return buffer.getvalue()


class BluetoothInboxTests(unittest.TestCase):
    def test_complete_original_survives_restart_with_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            library = BluetoothInbox(directory)
            raw = image_bytes('JPEG')
            record = library.import_bytes(raw, source_name='手机照片.jpg', sender='AA:BB:CC:DD:EE:FF')
            restarted = BluetoothInbox(directory)
            self.assertEqual(len(restarted.records()), 1)
            verified = restarted.get(record['id'])
            self.assertEqual(verified['source_name'], '手机照片.jpg')
            self.assertEqual(verified['path'].read_bytes(), raw)
            self.assertEqual(verified['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual((verified['width'], verified['height']), (32, 24))

    def test_same_name_never_overwrites_and_fake_extension_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as directory:
            library = BluetoothInbox(directory)
            first = library.import_bytes(image_bytes('JPEG'), source_name='../../bad.exe')
            second = library.import_bytes(image_bytes('JPEG'), source_name='../../bad.exe')
            self.assertNotEqual(first['id'], second['id'])
            self.assertEqual(first['source_name'], 'bad.exe')
            self.assertEqual(first['path'].suffix, '.jpg')
            self.assertEqual(first['path'].parent, Path(directory).resolve())
            self.assertEqual(len(library.records()), 2)

    def test_phone_exif_orientation_is_preserved_for_existing_image_pipeline(self):
        from PIL import ImageOps
        source = Image.new('RGB', (32, 24), 'red')
        exif = source.getexif(); exif[274] = 6
        data = io.BytesIO(); source.save(data, format='JPEG', exif=exif)
        with tempfile.TemporaryDirectory() as directory:
            record = BluetoothInbox(directory).import_bytes(data.getvalue())
            self.assertEqual(record['path'].read_bytes(), data.getvalue())
            with Image.open(record['path']) as image:
                self.assertEqual(ImageOps.exif_transpose(image).size, (24, 32))

    def test_partial_or_uncommitted_transfer_does_not_appear(self):
        with tempfile.TemporaryDirectory() as directory:
            library = BluetoothInbox(directory)
            (Path(directory) / ('a' * 32 + '.png')).write_bytes(image_bytes())
            (Path(directory) / 'transfer.tmp').write_bytes(image_bytes())
            self.assertEqual(library.records(), [])

    def test_rejects_invalid_and_truncated_jpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            library = BluetoothInbox(directory)
            for raw in (b'', b'#!/bin/sh\necho no', image_bytes('JPEG')[:-25]):
                with self.assertRaises((OSError, ValueError)):
                    library.import_bytes(raw, source_name='picture.png')
            self.assertEqual(library.records(), [])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_rejects_oversized_pixels_and_bytes_before_persisting(self):
        with tempfile.TemporaryDirectory() as directory:
            library = BluetoothInbox(directory)
            with patch('bluetooth_inbox.MAX_IMAGE_PIXELS', 100):
                with self.assertRaises(ValueError): library.import_bytes(image_bytes())
            with patch('bluetooth_inbox.MAX_IMAGE_BYTES', 4):
                with self.assertRaises(ValueError): library.import_bytes(image_bytes())
            self.assertEqual(library.records(), [])

    def test_rejects_animation(self):
        data = io.BytesIO()
        first = Image.new('RGB', (32, 24), 'red')
        first.save(data, format='GIF', save_all=True,
                   append_images=[Image.new('RGB', (32, 24), 'blue')])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, '静态'):
                BluetoothInbox(directory).import_bytes(data.getvalue())

    def test_storage_failure_never_exposes_image_and_cleans_uncommitted_bytes(self):
        import bluetooth_inbox
        with tempfile.TemporaryDirectory() as directory:
            library = BluetoothInbox(directory)
            write = bluetooth_inbox._atomic_write
            def fail_metadata(path, raw):
                if path.suffix == '.json': raise OSError('disk full')
                return write(path, raw)
            with patch('bluetooth_inbox._atomic_write', side_effect=fail_metadata):
                with self.assertRaises(OSError): library.import_bytes(image_bytes())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_path_traversal_sidecar_and_invalid_identity_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            library = BluetoothInbox(directory)
            record = library.import_bytes(image_bytes())
            sidecar = record['path'].with_suffix('.json')
            metadata = json.loads(sidecar.read_text(encoding='utf-8'))
            metadata['filename'] = '../escape.png'
            sidecar.write_text(json.dumps(metadata), encoding='utf-8')
            self.assertEqual(library.records(), [])
            with self.assertRaises(ValueError): library.get('../escape')
            with self.assertRaises(ValueError): library.get(record['id'])

    def test_same_size_modification_is_detected_at_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            library = BluetoothInbox(directory)
            record = library.import_bytes(image_bytes())
            raw = bytearray(record['path'].read_bytes()); raw[-1] ^= 1
            record['path'].write_bytes(raw)
            with self.assertRaisesRegex(ValueError, '内容已改变'):
                library.get(record['id'])

    def test_import_file_does_not_delete_staging_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'transfer.tmp'; source.write_bytes(image_bytes())
            library = BluetoothInbox(Path(directory) / 'inbox')
            record = library.import_file(source, source_name=r'folder\中文.png')
            self.assertTrue(source.exists())
            self.assertEqual(record['source_name'], '中文.png')
            self.assertEqual(record['path'].read_bytes(), source.read_bytes())

    def test_quota_rejects_without_removing_existing_images(self):
        with tempfile.TemporaryDirectory() as directory:
            library = BluetoothInbox(directory)
            record = library.import_bytes(image_bytes())
            with patch('bluetooth_inbox.MAX_LIBRARY_IMAGES', 1):
                with self.assertRaisesRegex(ValueError, '已满'): library.import_bytes(image_bytes())
            self.assertEqual(library.get(record['id'])['id'], record['id'])

    def test_symlink_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.png'; source.write_bytes(image_bytes())
            link = Path(directory) / 'linked.png'
            try: link.symlink_to(source)
            except (OSError, NotImplementedError): self.skipTest('symlinks unavailable')
            with self.assertRaises(ValueError):
                BluetoothInbox(Path(directory) / 'inbox').import_file(link)


class BluetoothSelectionTests(unittest.TestCase):
    def make_studio(self, directory):
        studio = gallery_studio(Path(directory) / 'cloud')
        studio.bluetooth_inbox = BluetoothInbox(Path(directory) / 'bluetooth')
        studio._predict_image = Mock()
        studio._extract = Mock()
        return studio

    def test_phone_selection_is_original_and_invalidates_old_plan_without_work(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = self.make_studio(directory)
            record = studio.bluetooth_inbox.import_bytes(image_bytes('JPEG'), source_name='phone.jpg')
            studio.plan_job_id = 'old-plan'
            studio._path_cache_key = 'old-image'
            studio.cloud_image_path = '/old/cloud.png'
            self.assertTrue(studio._use_bluetooth_image(record))
            self.assertEqual(studio.ent_image.get(), str(record['path']))
            self.assertEqual(studio.original_image_path, str(record['path']))
            self.assertIsNone(studio.cloud_image_path)
            self.assertEqual(studio.var_style.get(), 'photo')
            self.assertIsNone(studio.plan_job_id)
            self.assertIsNone(studio.image_job_id)
            self.assertIsNone(studio._path_cache_key)
            self.assertEqual(studio.btn_exec_arm.options['state'], 'disabled')
            studio.client.assert_not_called()
            self.assertEqual(studio.client.method_calls, [])
            studio._extract.assert_not_called(); studio._predict_image.assert_not_called()

    def test_every_busy_state_preserves_original_and_existing_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            for attribute in ('_execution_active', '_extraction_active', '_cloud_active',
                              '_prediction_active', '_calibration_active', '_planning_token'):
                studio = self.make_studio(directory)
                studio.plan_job_id = 'old-plan'; studio.ent_image.insert(0, '/selected.png')
                setattr(studio, attribute, True)
                with patch.object(studio.bluetooth_inbox, 'get') as read:
                    self.assertFalse(studio._use_bluetooth_image({'id': 'ignored'}))
                    read.assert_not_called()
                self.assertEqual(studio.plan_job_id, 'old-plan')
                self.assertEqual(studio.ent_image.get(), '/selected.png')

    def test_tampered_selection_cannot_override_old_job(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = self.make_studio(directory)
            studio.plan_job_id = 'old-plan'
            with patch('scripts.arm_studio.messagebox.showwarning') as warning:
                self.assertFalse(studio._use_bluetooth_image({'id': '../outside', 'path': '/etc/passwd'}))
                warning.assert_called_once()
            self.assertEqual(studio.plan_job_id, 'old-plan')


if __name__ == '__main__': unittest.main()
