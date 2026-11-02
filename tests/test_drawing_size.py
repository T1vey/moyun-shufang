"""Dimensions must change the actual registered geometry and invalidate old plans."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from stroke_paths import resize_paths,path_digest,validate_paths
from vision import preset
from scripts.arm_studio import ArmStudio
from test_studio_jobs import studio_fixture,Widget

class DrawingSizeTests(unittest.TestCase):
    def test_scale_preserves_order_identity_and_original_data(self):
        source=dict(units='mm',width_mm=100,height_mm=100,source_sha256='original',
            paths=[[[10,20],[50,80]],[[50,80],[90,90]]],ordering='outside_in')
        original=copy.deepcopy(source)
        for side in (100,200,300):
            enlarged=resize_paths(source,side,side)
            self.assertEqual(enlarged['paths'][0][0],[side*.1,side*.2])
            self.assertEqual(enlarged['paths'][1][-1],[side*.9,side*.9])
            self.assertEqual(enlarged['source_sha256'],'original')
            self.assertEqual(enlarged['path_sha256'],path_digest(enlarged))
            self.assertEqual(validate_paths(enlarged),(2,2))
        self.assertEqual(source,original)
    def test_preset_accepts_300_mm_without_clipping(self):
        with tempfile.TemporaryDirectory() as folder:
            data=preset('square',Path(folder),300,300)
            self.assertEqual(data['paths'][0][2],[300,300])
            self.assertEqual(validate_paths(data),(1,4))
    def test_gui_size_change_keeps_source_job_but_invalidates_plan(self):
        s=studio_fixture();s.image_job_id='original-upload';s.plan_job_id='old-plan'
        s.var_w=Widget('100');s.var_h=Widget('100');s.var_size_preset=Widget('300×300 mm')
        s._pick_drawing_size()
        self.assertEqual((s.var_w.get(),s.var_h.get()),('300','300'))
        self.assertEqual(s.image_job_id,'original-upload');self.assertIsNone(s.plan_job_id)
        self.assertTrue(s._image_requires_plan)
    def test_worker_scales_registered_paths_and_saves_actual_dimensions(self):
        from app import State
        from workbench import Workbench
        with tempfile.TemporaryDirectory() as folder:
            state=State(Path(folder));w=Workbench(state)
            # Small centred source remains reachable at all three canvas sizes.
            raw=dict(units='mm',width_mm=100,height_mm=100,paths=[[[49,50],[51,50]]])
            image=w.start('strokes',dict(paths=raw));w.worker.join(3)
            for side in (100,200,300):
                job=w.start('plan',dict(mode='demo',image_job=image['id'],drawing_size_mm=[side,side],motion_mode='speed_priority'))
                w.worker.join(5);done=w.jobs[job['id']]
                self.assertEqual(done['status'],'DONE',done.get('detail'))
                saved=w.plans[job['id']]
                self.assertEqual(saved['paths']['width_mm'],side)
                self.assertAlmostEqual(saved['paths']['paths'][0][1][0]-saved['paths']['paths'][0][0][0],side*.02)
                self.assertEqual(saved['result'].metrics['path_source']['width_mm'],side)
                disk=json.loads(w._plan_path(job['id']).read_text(encoding='utf-8'))
                self.assertEqual(disk['paths']['height_mm'],side)
            original=json.loads((state.directory/('job_'+image['id'])/'paths.json').read_text(encoding='utf-8'))
            self.assertEqual(original['width_mm'],100)

if __name__=='__main__':unittest.main()
