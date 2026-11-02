"""Ordered ink, frozen command FK, PC-only preview and real Tk controls."""
import copy
import csv
import json
from pathlib import Path
import sys
import tempfile
import threading
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tests'))
from drawing_prediction import ordered_preview, command_preview, export_order_csv, export_preview_svg
from scripts.drawing_preview_ui import DrawingPreviewWindow
from scripts.arm_studio import BoardClient, process_image_local
from test_cloud_gallery import gallery_studio
from test_studio_jobs import DeferredThreads, plan_info


def paths_fixture():
    return dict(units='mm', width_mm=20, height_mm=10, coordinate_system='full_canvas_xy_down',
                paths=[[[1, 2], [5, 2], [5, 6]], [[10, 4], [12, 4]]])


def commands_fixture():
    from planning import Model, load, drawing_spec
    model_config = load('nominal_so101.json')
    model = Model(model_config)
    qs = [[0., 0., 0., 0., 0.], [.002, 0., 0., 0., 0.], [.004, 0., 0., 0., 0.]]
    targets = [model.pose(q)[:3, 3] for q in qs]
    origin = targets[0]
    chain = [[float((p[0]-origin[0])*1000+50), float((p[1]-origin[1])*1000+50)] for p in targets]
    paths = dict(units='mm', width_mm=100, height_mm=100, coordinate_system='full_canvas_xy_down', paths=[chain])
    paper = dict(origin_m=origin.tolist(), u=[1, 0, 0], v=[0, 1, 0], normal=[0, 0, 1], pen_axis=[0, 0, 1])
    spec = drawing_spec(paths, paper, qs[0])
    machine = dict(model=model_config, paper=paper,
                   joints=[dict(id=i+1, direction=1, zero_count=2048, min_count=100, max_count=3900) for i in range(5)])
    commands = [dict(t_s=(i+1)*.1, q_rad=q, tip_target_m=p.tolist(), stroke=0,
                     phase='LOWER' if i == 0 else 'DRAW', pen_down=i != 0) for i, (q, p) in enumerate(zip(qs, targets))]
    return dict(job_id='frozen-plan', status='OK', mode='real', commands=commands, metrics={'duration_s': .3},
                machine=machine, paths=paths, drawing=spec)


class PredictionDataTests(unittest.TestCase):
    def test_global_segment_order_is_exact_and_transfers_never_become_ink(self):
        data = ordered_preview(paths_fixture())
        self.assertEqual(data['segments'], 3)
        self.assertEqual([r['order'] for r in data['rows']], [1, 2, 3])
        self.assertEqual([(r['stroke'], r['stroke_segment']) for r in data['rows']], [(1, 1), (1, 2), (2, 1)])
        self.assertEqual(data['rows'][2]['start_mm'], [10, 4])
        self.assertEqual(data['draw_length_mm'], 10)

    def test_export_all_numbered_segments_without_extra_transfer(self):
        preview = ordered_preview(paths_fixture())
        with tempfile.TemporaryDirectory() as directory:
            csvfile = Path(directory) / 'order.csv'; svgfile = Path(directory) / 'preview.svg'
            export_order_csv(preview, csvfile); export_preview_svg(preview, svgfile, numbers=True)
            with csvfile.open(encoding='utf-8-sig', newline='') as file: rows = list(csv.reader(file))
            self.assertEqual(len(rows), 4)
            self.assertEqual([row[0] for row in rows[1:]], ['1', '2', '3'])
            svg = ET.parse(svgfile)
            self.assertEqual(len(svg.findall('.//{http://www.w3.org/2000/svg}polyline')), 3)
            self.assertEqual([t.text for t in svg.findall('.//{http://www.w3.org/2000/svg}text')], ['1', '2', '3'])

    def test_real_prediction_uses_integer_counts_and_independent_scalar_fk(self):
        from planning import Model
        from motion import counts_from_angles, angles_from_counts
        data = commands_fixture(); original = copy.deepcopy(data)
        preview = command_preview(data)
        self.assertEqual(data, original)
        self.assertEqual(preview['predicted_commands'], 2)
        self.assertEqual(preview['unrepresented_segments'], 0)
        self.assertGreater(preview['max_command_target_error_mm'], 0)
        model = Model(data['machine']['model'])
        origin = np.array(data['drawing']['plane_origin_m'])
        for row, command in zip(preview['rows'], data['commands'][1:]):
            q = angles_from_counts(data['machine'], counts_from_angles(data['machine'], command['q_rad']))
            expected = (model.pose(q)[:3, 3]-origin)[:2]*1000 + 50
            np.testing.assert_allclose(row['predicted_points_mm'][-1], expected, atol=1e-10)
        self.assertEqual([r['command_last'] for r in preview['rows']], [2, 3])

    def test_missing_snapshot_and_mismatched_paths_are_rejected(self):
        data = commands_fixture(); data['machine'] = None
        with self.assertRaisesRegex(ValueError, '冻结'): command_preview(data)
        data = commands_fixture(); data['paths']['paths'][0][1][0] += 1
        with self.assertRaisesRegex(ValueError, '不一致'): command_preview(data)

    def test_reversing_segment_keeps_its_own_order_and_commands(self):
        from planning import drawing_spec
        data = commands_fixture()
        data['commands'][2]['q_rad'] = data['commands'][0]['q_rad'][:]
        data['commands'][2]['tip_target_m'] = data['commands'][0]['tip_target_m'][:]
        data['paths']['paths'][0][-1] = data['paths']['paths'][0][0][:]
        data['drawing'] = drawing_spec(data['paths'], data['machine']['paper'], [0]*5)
        preview = command_preview(data)
        self.assertEqual([r['command_last'] for r in preview['rows']], [2, 3])


class PredictionControllerTests(unittest.TestCase):
    def test_offline_preview_then_upload_reuses_identical_numbered_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = gallery_studio(directory)
            studio._path_data = None
            studio.ent_image.insert(0, ROOT / 'tests/fixtures/duck_lineart.png')
            studio.cloud_image_path = studio.ent_image.get()
            threads = DeferredThreads()
            studio.client.strokes.return_value = {'id': 'uploaded-preview'}
            studio.client.get_jobs.return_value = {'jobs': [{'id': 'uploaded-preview', 'status': 'DONE'}]}
            with patch('scripts.arm_studio.threading.Thread', threads.thread), \
                    patch('scripts.arm_studio.process_image_local', wraps=process_image_local) as extraction:
                studio._predict_image(); threads.run_next(); studio.root.drain()
                studio.client.strokes.assert_not_called()
                studio.client.fetch_status.assert_not_called()
                original = copy.deepcopy(studio._path_data)
                studio._extract(); threads.run_next(); studio.root.drain()
                self.assertEqual(extraction.call_count, 1)
                self.assertEqual(studio.client.strokes.call_args.args[0]['paths'], original['paths'])
                self.assertEqual(studio.client.strokes.call_args.args[0]['path_sha256'], original['path_sha256'])
            self.assertEqual(studio.image_job_id, 'uploaded-preview')
            self.assertFalse(studio._prediction_active)
            studio.client.plan.assert_not_called(); studio.client.execute.assert_not_called()

    def test_resize_invalidates_preview_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = gallery_studio(directory); studio._path_data = None
            studio.ent_image.insert(0, ROOT / 'tests/fixtures/duck_lineart.png')
            studio.cloud_image_path = studio.ent_image.get()
            threads = DeferredThreads()
            with patch('scripts.arm_studio.threading.Thread', threads.thread), \
                    patch('scripts.arm_studio.process_image_local', wraps=process_image_local) as extraction:
                studio._predict_image(); threads.run_next(); studio.root.drain()
                old = studio._path_data['path_sha256']
                studio.var_w.set('80')
                studio._predict_image(); threads.run_next(); studio.root.drain()
                self.assertEqual(extraction.call_count, 2)
                self.assertEqual(studio._path_data['width_mm'], 80)
                self.assertNotEqual(studio._path_data['path_sha256'], old)

    def test_pending_preview_cannot_select_old_plan_or_recurse(self):
        with tempfile.TemporaryDirectory() as directory:
            studio = gallery_studio(directory)
            studio.plan_job_id = 'chosen-plan'; studio._prediction_active = True
            studio._apply_plan_history([plan_info('old-plan')], ['old'])
            studio.cmb_plans.current(0); studio._on_pick_plan()
            self.assertEqual(studio.plan_job_id, 'chosen-plan')
            self.assertIsNone(studio._begin_planning())


class FrozenPlanTests(unittest.TestCase):
    def test_saved_preview_survives_restart_and_changed_current_calibration(self):
        from app import State, Server
        from workbench import Workbench, StoredPlan
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / 'data')
            state.real_factory = Mock(side_effect=AssertionError('preview opened servos'))
            workbench = Workbench(state, allow_motion=True)
            data = commands_fixture()
            workbench.machine = copy.deepcopy(data['machine'])
            stored = dict(mode='real', result=StoredPlan(data), q0=[0]*5, digest=workbench.digest(),
                          machine=data['machine'], paths=data['paths'], drawing=data['drawing'])
            workbench.plans['frozen-plan'] = stored; workbench._save_plan('frozen-plan', stored)
            changed = copy.deepcopy(data['machine']); changed['joints'][0]['zero_count'] = 1000
            workbench.machine = changed
            workbench.config_file.write_text(json.dumps(changed), encoding='utf-8')
            restarted = Workbench(State(Path(directory) / 'data'), allow_motion=True)
            restored = restarted.prediction_data('frozen-plan')
            self.assertEqual(restored['machine']['joints'][0]['zero_count'], 2048)
            self.assertFalse(restarted.list_plans()['plans'][0]['matches_current_calibration'])
            before = command_preview(data); after = command_preview(restored)
            self.assertEqual(before['rows'], after['rows'])
            server = Server(('127.0.0.1', 0), state, allow_motion=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                client = BoardClient(port=server.server_port); client.token = state.token
                downloaded = client.prediction_data('frozen-plan')
                self.assertEqual(command_preview(downloaded)['rows'], before['rows'])
                self.assertEqual(server.workbench.demo.writes, [])
                state.real_factory.assert_not_called()
            finally:
                server.shutdown(); server.server_close()

    def test_legacy_plan_cannot_silently_use_current_calibration(self):
        from app import State
        from workbench import Workbench, StoredPlan
        with tempfile.TemporaryDirectory() as directory:
            workbench = Workbench(State(Path(directory) / 'data'))
            workbench.plans['legacy'] = dict(result=StoredPlan(commands_fixture()), mode='real')
            with self.assertRaisesRegex(ValueError, '重新规划'): workbench.prediction_data('legacy')


class PredictionTkTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def test_final_effect_single_steps_selection_slider_and_pause(self):
        window = DrawingPreviewWindow(self.root, ordered_preview(paths_fixture()))
        self.addCleanup(lambda: window.close() if window.win.winfo_exists() else None)
        window.win.withdraw(); self.root.update_idletasks()
        self.assertEqual(len(window.tree.get_children()), 3)
        self.assertEqual(window.position.get(), 3)
        self.assertEqual(len(window.canvas.find_withtag('ink')), 3)
        window.seek(0)
        self.assertTrue(all(window.canvas.itemcget(item, 'state') == 'hidden' for item in window._ink.values()))
        window.btn_next.invoke(); self.assertEqual(window.position.get(), 1)
        self.assertIn('第 1 笔内第 1 段', window.detail.cget('text'))
        self.assertEqual(len(window.canvas.find_withtag('active_segment')), 1)
        window._scale_seek('2'); self.assertEqual(window.position.get(), 2)
        window.tree.selection_set('3'); window._tree_selected(); self.assertEqual(window.position.get(), 3)
        self.assertIn('第 2 笔内第 1 段', window.detail.cget('text'))
        window.play(); self.assertEqual(window.position.get(), 1); self.assertIsNotNone(window._timer)
        window.btn_pause.invoke(); self.assertIsNone(window._timer)
        window.numbers.set(True); window.update_layers()
        self.assertEqual(len(window.canvas.find_withtag('numbers')), 3)
        self.assertTrue(all(window.canvas.itemcget(i, 'state') == 'normal' for i in window.canvas.find_withtag('numbers')))

    def test_up_down_paper_directions_and_no_ink_connecting_strokes(self):
        for direction in ('full_canvas_xy_down', 'full_canvas_xy_up'):
            data = paths_fixture(); data['coordinate_system'] = direction
            window = DrawingPreviewWindow(self.root, ordered_preview(data))
            window.win.withdraw(); self.root.update_idletasks()
            try:
                self.assertEqual(len(window.canvas.find_withtag('transfers')), 1)
                self.assertEqual(len(window.canvas.find_withtag('ink')), 3)
                a, b = window.point([0, 0]), window.point([0, 10])
                self.assertEqual(a[1] < b[1], direction == 'full_canvas_xy_down')
            finally: window.close()


if __name__ == '__main__': unittest.main()
