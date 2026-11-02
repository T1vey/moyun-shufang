"""Independent topology/shape regressions; no board or motor connection."""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

import cv2
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from vision import convert
from scripts.arm_studio import process_image_local
from stroke_paths import graph_trails,thin,validate_paths,path_digest


class DrawingQualityTests(unittest.TestCase):
    def extract(self,image,**kw):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        source=Path(folder.name)/'source.png';Image.fromarray(image).save(source)
        result=convert(source,Path(folder.name)/'out',width_mm=20,height_mm=20,**kw)
        return result,Path(folder.name)

    def test_thick_line_is_one_open_stroke_without_retrace(self):
        image=np.full((200,200),255,np.uint8)
        cv2.line(image,(40,100),(160,100),0,7)
        r,_=self.extract(image)
        self.assertEqual(r['strokes'],1)
        self.assertAlmostEqual(r['draw_length_mm'],12,delta=.5)
        self.assertGreater(math.dist(r['paths'][0][0],r['paths'][0][-1]),11)

    def test_open_arc_is_one_open_stroke(self):
        image=np.full((200,200),255,np.uint8)
        cv2.ellipse(image,(100,100),(65,45),0,190,340,0,6)
        r,_=self.extract(image)
        self.assertEqual(r['strokes'],1)
        self.assertGreater(math.dist(r['paths'][0][0],r['paths'][0][-1]),8)
        self.assertLess(r['draw_length_mm'],20)

    def test_closed_circle_drawn_once_and_closed(self):
        image=np.full((200,200),255,np.uint8)
        cv2.circle(image,(100,100),65,0,7)
        r,_=self.extract(image)
        self.assertEqual(r['strokes'],1)
        self.assertEqual(r['paths'][0][0],r['paths'][0][-1])
        self.assertAlmostEqual(r['draw_length_mm'],2*math.pi*6.5,delta=1)

    def test_real_parallel_lines_are_not_deduplicated_or_bridged(self):
        image=np.full((200,200),255,np.uint8)
        for y in (90,102):cv2.line(image,(30,y),(170,y),0,5)
        r,_=self.extract(image)
        self.assertEqual(r['strokes'],2)
        self.assertAlmostEqual(r['draw_length_mm'],28,delta=1)
        ys=[np.mean(np.array(p)[:,1]) for p in r['paths']]
        self.assertAlmostEqual(abs(ys[0]-ys[1]),1.2,delta=.2)

    def test_t_junction_has_two_trails_and_no_repeated_edge(self):
        image=np.zeros((90,90),bool)
        image[20,10:81]=True;image[20:71,45]=True
        paths,graph=graph_trails(image)
        self.assertEqual(len(paths),2)
        length=sum(math.dist(a,b) for p in paths for a,b in zip(p,p[1:]))
        self.assertEqual(length,120)
        self.assertEqual(graph['pixel_edges'],graph['visited_pixel_edges'])
        self.assertEqual(graph['raw_chains'],graph['consumed_chains'])

    def test_crossing_keeps_straight_branches(self):
        image=np.zeros((90,90),bool)
        image[45,10:81]=True;image[10:81,45]=True
        paths,graph=graph_trails(image)
        self.assertEqual(len(paths),2)
        for p in paths:self.assertEqual(len({v[0] for v in p})==1 or len({v[1] for v in p})==1,True)
        self.assertEqual(graph['edge_revisits'],0)

    def test_nested_rings_are_ordered_outer_to_inner(self):
        image=np.full((200,200),255,np.uint8)
        for radius in (80,45,15):cv2.circle(image,(100,100),radius,0,4)
        r,_=self.extract(image)
        self.assertEqual(r['strokes'],3)
        self.assertEqual(r['stroke_layers'],[0,1,2])

    def test_blank_and_over_budget_reject_without_partial_paths(self):
        with self.assertRaises(ValueError):self.extract(np.full((100,100),255,np.uint8))
        image=np.full((200,200),255,np.uint8);cv2.circle(image,(100,100),70,0,5)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'in.png';Image.fromarray(image).save(p)
            with self.assertRaises(ValueError):convert(p,Path(folder)/'out',max_segments=10)
            self.assertFalse((Path(folder)/'out'/'paths.json').exists())

    def test_desktop_preserves_old_canvas_direction_and_common_engine(self):
        image=np.full((200,200),255,np.uint8);cv2.line(image,(30,40),(160,40),0,5)
        r,folder=self.extract(image)
        pc=process_image_local(folder/'source.png',folder/'pc',20,20)
        self.assertEqual(pc['engine'],r['engine'])
        self.assertEqual(pc['coordinate_system'],'full_canvas_xy_down')
        for up,down in zip(r['paths'][0],pc['paths'][0]):
            self.assertAlmostEqual(up[0],down[0]);self.assertAlmostEqual(up[1]+down[1],20)
        self.assertAlmostEqual(np.mean(np.array(pc['paths'][0])[:,1]),4,delta=.2)

    def test_bad_uploaded_coordinates_reject(self):
        base=dict(units='mm',width_mm=20,height_mm=20,paths=[[[0,0],[10,10]]])
        self.assertEqual(validate_paths(base),(1,1))
        for p in ([float('nan'),0],[21,0],[True,0],[0]):
            value=dict(base,paths=[[[0,0],p]])
            with self.assertRaises(ValueError):validate_paths(value)

    def test_user_duck_head_first_and_each_eye_single_open_stroke(self):
        source=ROOT/'tests'/'fixtures'/'duck_lineart.png'
        with tempfile.TemporaryDirectory() as folder:
            r=process_image_local(source,folder,100,100)
            self.assertLess(r['draw_length_mm'],600)
            self.assertLess(r['segments'],400)
            first=np.array(r['paths'][0])
            self.assertGreater(np.ptp(first[:,0]),60)
            self.assertGreater(np.ptp(first[:,1]),55)
            self.assertEqual(r['stroke_layers'],sorted(r['stroke_layers']))
            eyes=[]
            for p in r['paths']:
                a=np.array(p);lo=a.min(axis=0);hi=a.max(axis=0)
                if lo[1]>25 and hi[1]<35 and hi[0]-lo[0]<20:
                    eyes.append(p)
            self.assertEqual(len(eyes),2)
            for p in eyes:self.assertGreater(math.dist(p[0],p[-1]),10)
            self.assertEqual(r['path_sha256'],path_digest(r))
            self.assertEqual(json.loads((Path(folder)/'paths.json').read_text(encoding='utf-8'))['path_sha256'],r['path_sha256'])

    def test_geometry_gate_rejects_model_path_deviation(self):
        from planning import nominal,load,drawing_spec
        from r1b.planner import plan
        from vision import preset
        model,paper,q0=nominal(); original=model.pose_many
        def displaced(joints):
            poses=original(joints);poses[:,2,3]+=.01;return poses
        with tempfile.TemporaryDirectory() as folder:
            spec=drawing_spec(preset('line',folder,5,5),paper,q0)
            cfg=dict(load('trajectory.json'),motion_profile='continuous_quintic')
            with patch.object(model,'pose_many',side_effect=displaced):
                r=plan(model,spec,q0,load('contract.json'),cfg)
            self.assertEqual(r.status,'DRAW_GEOMETRY_ERROR')
            self.assertIsNone(r.commands)
            self.assertGreater(r.metrics['max_draw_path_error_m'],.009)

    def test_old_edge_extraction_cannot_be_replanned_as_new_centerline(self):
        from planning import build
        paths=dict(units='mm',width_mm=20,height_mm=20,engine='local_opencv_edge',paths=[[[0,0],[10,10]]])
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'重新提取'):build(paths,folder)


class BoardPathOwnershipTests(unittest.TestCase):
    def setUp(self):
        from app import State
        from workbench import Workbench
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.state=State(Path(self.folder.name)/'data')
        self.state.real_factory=Mock(side_effect=AssertionError('Unexpected physical connection'))
        self.w=Workbench(self.state,allow_motion=True)

    def test_uploaded_summary_is_computed_and_preview_matches_payload(self):
        raw=dict(units='mm',width_mm=20,height_mm=20,paths=[[[1,2],[3,4]]],strokes=99,segments=99)
        job=self.w.start('strokes',{'paths':raw});self.w.worker.join(5)
        current=self.w.jobs[job['id']]
        self.assertEqual(current['status'],'DONE')
        self.assertEqual(current['result']['strokes'],1)
        self.assertEqual(current['result']['segments'],1)
        folder=self.state.directory/('job_'+job['id'])
        self.assertTrue((folder/'paths.svg').is_file())
        stored=json.loads((folder/'paths.json').read_text())
        self.assertEqual(stored['path_sha256'],path_digest(stored))

    def test_uploaded_bad_digest_cannot_register_paths(self):
        raw=dict(units='mm',width_mm=20,height_mm=20,paths=[[[1,2],[3,4]]],path_sha256='bad')
        job=self.w.start('strokes',{'paths':raw});self.w.worker.join(5)
        self.assertEqual(self.w.jobs[job['id']]['status'],'FAILED')
        self.assertFalse((self.state.directory/('job_'+job['id'])/'paths.json').exists())

    def test_old_real_plan_is_retained_but_rejected_before_serial_open(self):
        from workbench import StoredPlan
        self.w.plans['old']=dict(mode='real',digest=self.w.digest(),
            result=StoredPlan(dict(status='OK',commands=[dict(t_s=1)],metrics={})))
        self.assertTrue(self.w.list_plans()['plans'][0]['needs_replan'])
        job=self.w.start('execute',dict(mode='real',plan_job='old',confirmed=True))
        self.w.worker.join(5)
        self.assertEqual(self.w.jobs[job['id']]['status'],'FAILED')
        self.assertIn('旧绘画流程',self.w.jobs[job['id']]['detail'])
        self.state.real_factory.assert_not_called()
        self.assertIn('old',self.w.plans)


if __name__=='__main__':unittest.main()
