"""Persistence boundaries: one execution artifact, verified history, fail closed."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import plan_storage
from plan_storage import publish_execution_plan, get_execution_artifact, load_history_plan
from workbench import Workbench, StoredPlan


def plan_result():
    return StoredPlan(dict(status='OK', metrics={'completed_targets': 2},
                           commands=[dict(q_rad=[i / 1000] * 5, t_s=i / 100,
                                          pen_down=bool(i % 2), physical_authorized=False)
                                     for i in range(80)],
                           trajectory_segments=[{'coefficients': [[0, 1, 2]] * 5}],
                           execution_contract={'version': 1, 'duration_s': .79}))


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = SimpleNamespace(directory=self.root / 'session', record=Mock(), lock=threading.Lock())
        self.state.directory.mkdir()
        self.workbench = Workbench(self.state)

    def stored(self, result=None):
        return dict(result=result or plan_result(), q0=[0] * 5, mode='demo', digest='frozen-digest',
                    machine={'model': 'frozen-machine'}, paths={'height_mm': 100, 'paths': [[[0, 0], [1, 1]]]},
                    drawing={'q0': [0] * 5}, port='COM-test', baudrate=1000000)

    def test_streamed_save_matches_sync_bytes_and_checksum(self):
        a, b = self.root/'sync.json', self.root/'stream.json'
        result = plan_result()
        expected = publish_execution_plan(a,result)
        actual = plan_storage.publish_execution_plan_streamed(b,result)
        self.assertEqual(a.read_bytes(),b.read_bytes())
        self.assertEqual(expected['sha256'],actual['sha256'])
        self.assertEqual(expected['bytes'],actual['bytes'])

    def test_background_save_pauses_for_motion_and_does_not_mutate_plan(self):
        stored = self.stored(); before = copy.deepcopy(vars(stored['result']))
        folder=self.state.directory/'job_background';folder.mkdir()
        self.workbench.plans['background']=stored
        self.workbench._save_pause.set()
        self.workbench._queue_plan_save('background',stored,folder)
        self.assertEqual(self.workbench._save_states['background']['status'],'pending')
        self.assertFalse((folder/'plan.json').exists())
        # Cancelling a different motion/plan does not cancel a completed plan's save.
        self.workbench.cancel.set()
        self.workbench._save_pause.clear()
        for t in self.workbench._save_threads:t.join(3)
        self.assertEqual(self.workbench._save_states['background']['status'],'saved')
        self.assertEqual(vars(stored['result']),before)
        self.assertEqual(load_history_plan(self.workbench._plan_path('background'),self.root)['commands'],before['commands'])

    def test_disk_failure_retains_complete_memory_plan_but_not_history(self):
        stored=self.stored();folder=self.state.directory/'job_failed';folder.mkdir()
        self.workbench.plans['failed']=stored
        with patch('plan_storage.publish_execution_plan_streamed',side_effect=OSError('full disk')):
            self.workbench._queue_plan_save('failed',stored,folder)
            for t in self.workbench._save_threads:t.join(3)
        self.assertEqual(self.workbench._save_states['failed']['status'],'failed')
        self.assertIs(self.workbench.plans['failed'],stored)
        self.assertFalse(self.workbench._plan_path('failed').exists())

    def test_shutdown_cancels_pending_save_and_leaves_no_history(self):
        stored=self.stored();folder=self.state.directory/'job_pending';folder.mkdir()
        self.workbench._save_pause.set()
        self.workbench._queue_plan_save('pending',stored,folder)
        self.workbench.close_persistence()
        self.assertFalse(any(t.is_alive() for t in self.workbench._save_threads))
        self.assertEqual(self.workbench._save_states['pending']['status'],'failed')
        self.assertFalse(self.workbench._plan_path('pending').exists())

    def test_streamed_cancellation_removes_partial_file(self):
        cancelled=threading.Event()
        with self.assertRaises(ValueError):
            plan_storage.publish_execution_plan_streamed(self.root/'abort.json',plan_result(),
                cancelled.is_set, lambda:cancelled.set())
        self.assertFalse((self.root/'abort.json').exists())
        self.assertEqual(list(self.root.glob('.*.tmp')),[])

    def publish(self, key='new', stored=None):
        stored = stored or self.stored()
        source = self.state.directory / ('job_' + key) / 'plan.json'
        publish_execution_plan(source, stored['result'])
        self.assertTrue(self.workbench._save_plan(key, stored))
        return stored, source, self.workbench._plan_path(key)

    def test_manifest_reuses_exact_execution_file_and_restores_curve_and_context(self):
        stored = self.stored()
        original_keys = set(vars(stored['result']))
        with patch('plan_storage._json_bytes', wraps=plan_storage._json_bytes) as encode:
            stored, source, history = self.publish(stored=stored)
        full_encodes = [call for call in encode.call_args_list if 'commands' in call.args[0]]
        self.assertEqual(len(full_encodes), 1)
        self.assertEqual(set(vars(stored['result'])), original_keys)
        receipt = get_execution_artifact(stored['result'])
        manifest = json.loads(history.read_text(encoding='utf-8'))
        self.assertEqual(manifest['schema'], plan_storage.HISTORY_SCHEMA)
        self.assertFalse({'commands', 'trajectory_segments', 'execution_contract'} & manifest.keys())
        self.assertEqual((self.root / manifest['artifact']['path']).resolve(), source.resolve())
        self.assertEqual(manifest['artifact']['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(manifest['artifact']['sha256'], receipt['sha256'])
        self.assertLess(history.stat().st_size, source.stat().st_size / 3)
        self.assertFalse((self.workbench.plans_dir / 'artifacts').exists())
        self.workbench.machine = {'model': 'changed-machine'}
        restored = Workbench(self.state).plans['new']
        for field in ('commands', 'trajectory_segments', 'execution_contract'):
            self.assertEqual(getattr(restored['result'], field), getattr(stored['result'], field))
        for field in ('machine', 'paths', 'drawing', 'q0', 'mode', 'digest', 'port', 'baudrate'):
            self.assertEqual(restored[field], stored[field])

    def test_execution_artifact_is_immutable_and_failed_publish_cleans_temp(self):
        path = self.root / 'plan.json'
        first = plan_result()
        publish_execution_plan(path, first)
        raw = path.read_bytes()
        changed = plan_result(); changed.commands[0]['q_rad'][0] = 1
        with self.assertRaises(FileExistsError):
            publish_execution_plan(path, changed)
        self.assertEqual(path.read_bytes(), raw)
        self.assertIsNone(get_execution_artifact(changed))
        self.assertEqual(list(self.root.glob('.*.tmp')), [])
        with patch('plan_storage.os.fsync', side_effect=OSError('sync failed')):
            with self.assertRaises(OSError):
                publish_execution_plan(self.root / 'failed.json', plan_result())
        self.assertFalse((self.root / 'failed.json').exists())
        self.assertEqual(list(self.root.glob('.*.tmp')), [])

    def test_cancelled_partial_write_is_not_published(self):
        result = plan_result()
        calls = 0
        def cancelled():
            nonlocal calls
            calls += 1
            return calls >= 5  # After temp file creation, before commit.
        with self.assertRaisesRegex(ValueError, 'ABORT'):
            publish_execution_plan(self.root / 'plan.json', result, cancelled)
        self.assertFalse((self.root / 'plan.json').exists())
        self.assertIsNone(get_execution_artifact(result))
        self.assertEqual(list(self.root.glob('.*.tmp')), [])

    def test_fallback_for_legacy_or_outside_root_result_is_local_and_reused(self):
        outside = self.root.parent / (self.root.name + '-outside.json')
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        stored = self.stored()
        publish_execution_plan(outside, stored['result'])
        self.assertTrue(self.workbench._save_plan('local', stored))
        self.assertTrue(self.workbench._save_plan('second-reference', stored))
        first = json.loads(self.workbench._plan_path('local').read_text())
        second = json.loads(self.workbench._plan_path('second-reference').read_text())
        self.assertEqual(first['artifact'], second['artifact'])
        self.assertEqual(len(list((self.workbench.plans_dir / 'artifacts').glob('*.json'))), 1)
        self.assertEqual(len(Workbench(self.state).plans), 2)

    def test_changed_source_or_metadata_missing_source_unknown_version_are_refused(self):
        _, source, history = self.publish()
        good_source = source.read_bytes(); good_history = history.read_text()
        changed = good_source.replace(b'0.001', b'0.002', 1)
        self.assertEqual(len(changed), len(good_source)); self.assertNotEqual(changed, good_source)
        source.write_bytes(changed)
        self.assertEqual(Workbench(self.state).plans, {})
        source.write_bytes(good_source)
        doc = json.loads(good_history); doc['q0'][0] = 1
        history.write_text(json.dumps(doc))
        self.assertEqual(Workbench(self.state).plans, {})
        doc = json.loads(good_history); doc['schema'] = 'so101-plan-reference-v99'
        history.write_text(json.dumps(doc))
        self.assertEqual(Workbench(self.state).plans, {})
        history.write_text(good_history); source.unlink()
        self.assertEqual(Workbench(self.state).plans, {})

    def test_reference_cannot_escape_data_root_even_with_recomputed_metadata_hash(self):
        _, source, history = self.publish()
        doc = json.loads(history.read_text())
        doc['artifact']['path'] = '../outside.json'
        del doc['manifest_sha256']
        doc['manifest_sha256'] = hashlib.sha256(plan_storage._json_bytes(doc, canonical=True)).hexdigest()
        history.write_text(json.dumps(doc))
        with self.assertRaisesRegex(ValueError, 'invalid execution artifact reference'):
            load_history_plan(history, self.root)
        self.assertTrue(source.exists())

    def test_source_mutation_between_publish_and_history_is_refused(self):
        stored = self.stored(); source = self.root / 'plan.json'
        publish_execution_plan(source, stored['result'])
        source.write_bytes(source.read_bytes() + b' ')
        self.assertFalse(self.workbench._save_plan('mutated', stored))
        self.assertFalse(self.workbench._plan_path('mutated').exists())

    def test_failed_manifest_publish_retains_orphan_execution_artifact(self):
        stored = self.stored(); source = self.root / 'plan.json'
        publish_execution_plan(source, stored['result'])
        with patch.object(Path, 'replace', side_effect=OSError('full disk')):
            self.assertFalse(self.workbench._save_plan('failed', stored))
        self.assertTrue(source.is_file())
        self.assertFalse(self.workbench._plan_path('failed').exists())
        self.assertNotIn('saved_utc', stored)
        self.assertEqual(list(self.workbench.plans_dir.glob('.*.tmp')), [])
        self.assertEqual(Workbench(self.state).plans, {})

    def test_failed_manifest_directory_sync_does_not_leave_ready_history(self):
        stored = self.stored(); source = self.root / 'plan.json'
        publish_execution_plan(source, stored['result'])
        with patch('plan_storage._sync_directory', side_effect=OSError('directory sync failed')):
            self.assertFalse(self.workbench._save_plan('failed', stored))
        self.assertTrue(source.is_file())
        self.assertFalse(self.workbench._plan_path('failed').exists())
        self.assertEqual(Workbench(self.state).plans, {})

    def test_cancellation_at_manifest_commit_revokes_reference(self):
        stored = self.stored(); source = self.root / 'plan.json'
        publish_execution_plan(source, stored['result'])
        with patch('plan_storage._sync_directory', side_effect=lambda path: self.workbench.cancel.set()):
            self.assertFalse(self.workbench._save_plan('cancelled', stored))
        self.assertTrue(source.is_file())
        self.assertFalse(self.workbench._plan_path('cancelled').exists())
        self.assertEqual(Workbench(self.state).plans, {})

    def test_failed_and_cancelled_results_do_not_become_history(self):
        for status in ('ABORT', 'FAILED'):
            stored = self.stored(); stored['result'].status = status
            self.assertFalse(self.workbench._save_plan(status, stored))
        stored = self.stored(); self.workbench.cancel.set()
        self.assertFalse(self.workbench._save_plan('cancelled', stored))
        self.assertEqual(list(self.workbench.plans_dir.glob('plan_*.json')), [])

    def test_pruning_only_deletes_history_and_preserves_all_execution_artifacts(self):
        self.workbench.MAX_PLANS = 1
        stored, first_source, first_history = self.publish('first')
        self.workbench.plans['first'] = stored
        import os
        os.utime(first_history, (1, 1))
        orphan = self.root / 'orphan' / 'plan.json'
        publish_execution_plan(orphan, plan_result())
        _, second_source, second_history = self.publish('second')
        self.assertFalse(first_history.exists()); self.assertTrue(second_history.exists())
        self.assertNotIn('first', self.workbench.plans)
        self.assertTrue(first_source.exists()); self.assertTrue(second_source.exists()); self.assertTrue(orphan.exists())
        self.assertEqual(set(Workbench(self.state).plans), {'second'})

    def test_legacy_full_history_still_loads_without_rewrite(self):
        stored = self.stored(); doc = copy.deepcopy(vars(stored['result']))
        doc.update({k: v for k, v in stored.items() if k != 'result'}, job_id='legacy', saved_utc='old')
        path = self.workbench._plan_path('legacy'); path.write_text(json.dumps(doc))
        raw = path.read_bytes()
        restored = Workbench(self.state).plans['legacy']
        self.assertEqual(restored['result'].commands, stored['result'].commands)
        self.assertEqual(restored['machine'], stored['machine'])
        self.assertEqual(path.read_bytes(), raw)

    def run_worker(self, after_publish=None, background=False):
        source = self.state.directory / 'job_input'; source.mkdir()
        (source / 'paths.json').write_text(json.dumps({'paths': [[[0, 0], [1, 1]]]}))
        self.workbench.jobs['input'] = dict(kind='strokes', status='DONE')
        job = dict(id='worker', kind='plan', status='RUNNING', detail='')
        folder = self.state.directory / 'job_worker'; folder.mkdir()
        result = plan_result()
        def build(*args, **kwargs):
            if kwargs.get('persist', True):
                publish_execution_plan(folder / 'plan.json', result)
            if after_publish:
                after_publish()
            return result, {'q0': [0] * 5}, {}
        self.state.lock.acquire()
        with patch('planning.build', side_effect=build):
            self.workbench._run(job, folder, {'image_job': 'input', 'mode': 'demo', 'background_save':background})
        self.assertFalse(self.state.lock.locked())
        return job, folder

    def test_background_worker_publishes_memory_ready_before_disk_finishes(self):
        gate=threading.Event();entered=threading.Event()
        real=plan_storage.publish_execution_plan_streamed
        def blocked(*args,**kwargs):
            entered.set();gate.wait(3)
            return real(*args,**kwargs)
        with patch('plan_storage.publish_execution_plan_streamed',side_effect=blocked):
            try:
                job,folder=self.run_worker(background=True)
                self.assertTrue(entered.wait(1))
                self.assertEqual(job['status'],'DONE')
                self.assertIn('worker',self.workbench.plans)
                self.assertTrue(job['result']['metrics']['memory_ready'])
                self.assertFalse(job['result']['metrics']['history_saved'])
                self.assertFalse((folder/'plan.json').exists())
            finally:
                gate.set()
                for t in self.workbench._save_threads:t.join(3)
        self.assertEqual(self.workbench._save_states['worker']['status'],'saved')

    def assert_worker_not_available(self, job, folder):
        self.assertEqual(job['status'], 'FAILED')
        self.assertNotIn('worker', self.workbench.plans)
        self.assertFalse(self.workbench._plan_path('worker').exists())
        self.assertTrue((folder / 'plan.json').exists())
        self.assertNotIn('worker', Workbench(self.state).plans)

    def test_worker_cannot_be_ready_when_history_save_fails(self):
        with patch.object(self.workbench, '_save_plan', return_value=False):
            job, folder = self.run_worker()
        self.assert_worker_not_available(job, folder)

    def test_worker_cannot_be_ready_when_cancelled_after_build(self):
        job, folder = self.run_worker(self.workbench.cancel.set)
        self.assert_worker_not_available(job, folder)

    def test_worker_revokes_history_if_late_timing_or_result_write_fails(self):
        original = Path.write_text
        def fail_timing(path, *args, **kwargs):
            if path.name == 'timing.json':
                raise OSError('late timing write failed')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'write_text', fail_timing):
            job, folder = self.run_worker()
        self.assert_worker_not_available(job, folder)

    def test_worker_revokes_history_if_final_result_write_fails(self):
        original = Path.write_text
        def fail_result(path, *args, **kwargs):
            if path.name == 'result.json':
                raise OSError('late result write failed')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'write_text', fail_result):
            job, folder = self.run_worker()
        self.assert_worker_not_available(job, folder)

    def test_worker_is_available_only_after_successful_finalize(self):
        original = self.state.record
        def record(kind, detail):
            if kind == 'JOB_END':
                self.assertNotIn('worker', self.workbench.plans)
            original(kind, detail)
        self.state.record = record
        job, folder = self.run_worker()
        self.assertEqual(job['status'], 'DONE')
        self.assertIn('worker', self.workbench.plans)
        self.assertIn('worker', Workbench(self.state).plans)


if __name__ == '__main__':
    unittest.main()
