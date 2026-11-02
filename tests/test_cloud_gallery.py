"""Cloud image persistence and GUI selection, with no cloud or board traffic."""
from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from cloud_gallery import CloudImageLibrary
from scripts.arm_studio import ArmStudio, process_image_local
from test_studio_jobs import DeferredThreads, Widget, studio_fixture, plan_info


def image_bytes(format='PNG', color='black'):
    data = io.BytesIO()
    Image.new('RGB', (32, 24), color).save(data, format=format)
    return data.getvalue()


class Entry(Widget):
    def delete(self, *args): self.value = ''
    def insert(self, index, value): self.value = str(value)


def gallery_studio(directory):
    studio = studio_fixture()
    studio.cloud_library = CloudImageLibrary(directory)
    studio.cloud_image_path = None
    studio.original_image_path = None
    studio._cloud_active = False
    studio._extraction_active = False
    studio.ent_image = Entry()
    studio.var_style = Widget('photo')
    studio.var_cloud_model = Widget('seedream')
    studio.var_subject = Widget('object')
    studio.var_w = Widget('100')
    studio.var_h = Widget('100')
    studio.var_segs = Widget('4000')
    for name in ('lbl_image_job', 'lbl_cloud', 'btn_cloud', 'btn_cloud_history', 'btn_extract'):
        setattr(studio, name, Widget())
    studio._show_image_preview = Mock()
    studio._show_path_preview = Mock()
    studio._push_paths = Mock()
    return studio


class CloudLibraryTests(unittest.TestCase):
    def test_bytes_metadata_and_both_generations_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            library = CloudImageLibrary(Path(directory) / '中文图片库')
            raw = image_bytes()
            created = datetime(2026, 10, 4, 12, 0, tzinfo=timezone(timedelta(hours=8)))
            first = library.save(raw, profile='seedream', model='test-model', subject='object',
                                 source_name='鸭子.png', created_at=created)
            second = library.save(raw, profile='seedream', created_at=created)
            self.assertNotEqual(first['path'], second['path'])
            restarted = CloudImageLibrary(library.directory)
            records = restarted.records()
            self.assertEqual(len(records), 2)
            self.assertTrue(all(record['path'].read_bytes() == raw for record in records))
            metadata = json.loads(first['path'].with_suffix('.json').read_text(encoding='utf-8'))
            self.assertEqual(metadata['model'], 'test-model')
            self.assertEqual(metadata['source_name'], '鸭子.png')
            self.assertEqual(metadata['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual((metadata['width'], metadata['height']), (32, 24))
            self.assertFalse(list(library.directory.glob('*.tmp')))

    def test_extension_matches_actual_cloud_format_and_export_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            library = CloudImageLibrary(Path(directory) / 'library')
            raw = image_bytes('JPEG')
            record = library.save(raw)
            self.assertEqual(record['path'].suffix, '.jpg')
            exported = library.export(record['path'], Path(directory) / 'export.jpeg')
            self.assertEqual(exported.read_bytes(), raw)
            with self.assertRaises(ValueError): library.export(record['path'], Path(directory) / 'bad.png')

    def test_recent_first_and_no_global_index_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            library = CloudImageLibrary(directory)
            created = datetime.now().astimezone()
            older = library.save(image_bytes(), created_at=created - timedelta(days=1))
            newer = library.save(image_bytes(color='white'), created_at=created)
            newer['path'].with_suffix('.json').write_text('{broken', encoding='utf-8')
            (library.directory / 'broken.png').write_bytes(b'not an image')
            records = CloudImageLibrary(directory).records()
            self.assertEqual([r['path'] for r in records], [newer['path'], older['path']])

    def test_bad_cloud_response_does_not_add_library_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            library = CloudImageLibrary(directory)
            with self.assertRaises(OSError): library.save(b'not an image')
            self.assertEqual(list(library.directory.iterdir()), [])

    def test_import_recovers_originals_once_and_ignores_extraction_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            library = CloudImageLibrary(Path(directory) / 'permanent')
            temporary = Path(directory) / 'temporary'
            for name, raw in (('so101_cloud_a', image_bytes()), ('so101_cloud_b', image_bytes()),
                              ('so101_cloud_invalid', b'broken'),
                              ('so101_img_x', image_bytes(color='red'))):
                folder = temporary / name; folder.mkdir(parents=True)
                (folder / 'lineart.png').write_bytes(raw)
            self.assertEqual(library.import_legacy(temporary), dict(imported=1, already_present=1, invalid=1))
            self.assertEqual(library.import_legacy(temporary), dict(imported=0, already_present=2, invalid=1))
            record, = library.records()
            self.assertTrue(record['imported'])
            self.assertEqual(record['path'].read_bytes(), image_bytes())


class CloudStudioTests(unittest.TestCase):
    def test_generation_saves_to_library_and_updates_selection_only_on_tk_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = gallery_studio(Path(directory) / 'permanent')
            source = Path(directory) / 'source.png'; source.write_bytes(image_bytes(color='white'))
            studio.ent_image.insert(0, source)
            studio.plan_job_id = 'old-plan'
            raw = image_bytes()
            cloud = SimpleNamespace(load_secrets=Mock(), profile_path=Mock(return_value='unused'),
                                    load_config=Mock(return_value={'model': 'fake-model'}),
                                    generate=Mock(return_value=(raw, {'api_key': 'must-not-persist'})))
            threads = DeferredThreads()
            with patch.dict(sys.modules, {'cloud': cloud}), \
                    patch('scripts.arm_studio.threading.Thread', threads.thread):
                studio._cloud_generate()
                self.assertIsNone(studio.plan_job_id)
                self.assertTrue(studio._cloud_active)
                self.assertEqual(studio.btn_extract.options['state'], 'disabled')
                threads.run_next()
                self.assertEqual(studio.ent_image.get(), str(source))
                studio.root.drain()
            path = Path(studio.ent_image.get())
            self.assertEqual(path.parent, studio.cloud_library.directory)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(studio.cloud_image_path, str(path))
            self.assertEqual(studio.var_style.get(), 'lineart')
            self.assertFalse(studio._cloud_active)
            self.assertEqual(studio.btn_cloud.options['state'], 'normal')
            studio._show_image_preview.assert_called_once_with(path)
            self.assertNotIn('must-not-persist', path.with_suffix('.json').read_text(encoding='utf-8'))
            studio.client.strokes.assert_not_called()
            studio.client.execute.assert_not_called()

    def test_history_selection_then_upload_uses_saved_image_without_cloud_call(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = gallery_studio(Path(directory) / 'permanent')
            record = studio.cloud_library.save((ROOT / 'tests/fixtures/duck_lineart.png').read_bytes(),
                                               profile='seedream')
            # A later process reads the same library from disk.
            record, = CloudImageLibrary(studio.cloud_library.directory).records()
            studio.plan_job_id = 'old-plan'
            studio.client.strokes.return_value = {'id': 'new-image'}
            studio.client.get_jobs.return_value = {'jobs': [{'id': 'new-image', 'status': 'DONE'}]}
            threads = DeferredThreads()

            with patch('scripts.arm_studio.threading.Thread', threads.thread), \
                    patch('scripts.arm_studio.process_image_local', wraps=process_image_local) as extraction, \
                    patch('cloud.generate') as cloud:
                self.assertTrue(studio._use_cloud_image(record, upload=True))
                self.assertIsNone(studio.plan_job_id)
                self.assertTrue(studio._extraction_active)
                threads.run_next(); studio.root.drain()
                cloud.assert_not_called()
                self.assertEqual(Path(extraction.call_args.args[0]), record['path'])
                self.assertEqual(extraction.call_args.kwargs['style'], 'lineart')
            self.assertEqual(studio.image_job_id, 'new-image')
            payload = studio.client.strokes.call_args.args[0]
            self.assertEqual(payload['style'], 'lineart')
            self.assertEqual(payload['algorithm_version'], 'centerline-graph-v1+path-quality-sg-v1')
            self.assertEqual(payload['extraction']['graph']['edge_revisits'], 0)
            studio.client.plan.assert_not_called()
            studio.client.execute.assert_not_called()

    def test_late_old_plan_history_does_not_replace_new_image(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = gallery_studio(directory)
            record = studio.cloud_library.save(image_bytes())
            studio.plan_job_id = 'old-plan'
            self.assertTrue(studio._use_cloud_image(record))
            studio._apply_plan_history([plan_info('other-old-plan')], ['other'])
            self.assertIsNone(studio.image_job_id)
            self.assertIsNone(studio.plan_job_id)
            self.assertEqual(studio.btn_exec_arm.options['state'], 'disabled')

    def test_pending_generation_blocks_old_plan_selection_and_image_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = gallery_studio(directory)
            record = studio.cloud_library.save(image_bytes())
            studio._cloud_active = True
            studio._apply_plan_history([plan_info('old-plan')], ['old'])
            studio.cmb_plans.current(0); studio._on_pick_plan()
            self.assertIsNone(studio.plan_job_id)
            self.assertFalse(studio._use_cloud_image(record, upload=True))
            studio.client.strokes.assert_not_called()

    def test_save_failure_clears_busy_state_and_shows_error(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = gallery_studio(directory)
            source = Path(directory) / 'source.png'; source.write_bytes(image_bytes())
            studio.ent_image.insert(0, source)
            cloud = SimpleNamespace(load_secrets=Mock(), profile_path=Mock(return_value='unused'),
                                    load_config=Mock(return_value={'model': 'fake'}),
                                    generate=Mock(return_value=(image_bytes(), {})))
            threads = DeferredThreads()
            with patch.dict(sys.modules, {'cloud': cloud}), \
                    patch('scripts.arm_studio.threading.Thread', threads.thread), \
                    patch.object(studio.cloud_library, 'save', side_effect=OSError('disk full')), \
                    patch('scripts.arm_studio.messagebox.showerror') as error:
                studio._cloud_generate(); threads.run_next(); studio.root.drain()
                error.assert_called_once_with('云端生成或保存失败', 'disk full')
            self.assertFalse(studio._cloud_active)
            self.assertEqual(studio.ent_image.get(), str(source))
            studio._show_image_preview.assert_not_called()


if __name__ == '__main__':
    unittest.main()
