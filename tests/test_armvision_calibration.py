"""ArmVision compatibility: original values, Cartesian mapping and read protocol.

No controller or mechanical motion. Native IK uses an explicit synthetic fixture.
"""
import copy
import hashlib
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import numpy as np
from tcb705.config import load,demo_config,validate,digest
from tcb705.calibration import apply_armvision,fields,paper_frame,capture,map_canvas,assert_model_ready
from tcb705.armvision_import import import_settings
from tcb705.armvision_feedback import read_world

FIXTURE='''table:
  x_min: -509.605
  x_max: -359.390
  y_min: -67.854
  y_max: 80.666
  z_table: 206.31
pen:
  lift_mm: 8
  final_lift_mm: 60
motion:
  swap_xy: true
  draw_speed: 100
  tool: 0
  coord: 0
  extool: 0
tianlian:
  robot_id: 1
  axis_count: 4
  pose_u: 180
  pose_v: 0
  pose_w: 0
ai:
  api_key: do-not-import
'''

class CalibrationTests(unittest.TestCase):
    def setUp(self):self.cfg=load();self.a=copy.deepcopy(self.cfg['armvision'])

    def test_import_exact_values_without_unrelated_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'settings.yaml';p.write_bytes(FIXTURE.encode('utf-8'));a,source=import_settings(p)
        self.assertEqual(a,self.a)
        self.assertEqual(source['sha256'],hashlib.sha256(FIXTURE.encode()).hexdigest())
        self.assertNotIn('api_key',json.dumps(a));self.assertNotIn('axis_count',a)
        self.assertEqual(a['image'],{'target_width_mm':148.5,'target_height_mm':150.2})

    def test_import_rejects_missing_or_duplicate_values(self):
        for text in (FIXTURE.replace('  z_table: 206.31\n',''),FIXTURE.replace('  z_table: 206.31','  z_table: 206.31\n  z_table: 0')):
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/'settings.yaml';p.write_text(text,encoding='utf-8')
                with self.assertRaises(ValueError):import_settings(p)

    def test_ab_reverse_order_preserves_same_bounds(self):
        a=copy.deepcopy(self.a);a['a_mm'],a['b_mm']=a['b_mm'],a['a_mm']
        self.assertEqual(paper_frame(a),paper_frame(self.a))
        self.assertEqual(fields(a)['a_mm'],[-359.39,80.666])
        a['b_mm'][0]=a['a_mm'][0]
        with self.assertRaises(ValueError):fields(a)

    def test_capture_points_and_landing_are_independent(self):
        p=[-480.1234,20.1236,206.7894,179.9,.1,.2]
        a=capture(self.a,'a',p);self.assertEqual(a['a_mm'],[-480.123,20.124]);self.assertEqual(a['z_table_mm'],206.31)
        b=capture(self.a,'b',p);self.assertEqual(b['a_mm'],self.a['a_mm'])
        c=capture(self.a,'landing',p)
        self.assertEqual(c['a_mm'],self.a['a_mm']);self.assertEqual(c['b_mm'],self.a['b_mm'])
        self.assertEqual(c['z_table_mm'],206.789);self.assertEqual(c['pose_uvw_deg'],[179.9,.1,.2])

    def test_capture_rejects_partial_nonfinite_feedback(self):
        for p in ([0]*5,[0,0,float('nan'),180,0,0]):
            with self.assertRaises(ValueError):capture(self.a,'landing',p)

    def test_canvas_corners_match_original_armvision_formula(self):
        # Original converter: X=x_max-y/150.2*150.215; Y=y_min+x/148.5*148.520.
        data={'units':'mm','coordinate_system':'full_canvas_xy_up','width_mm':148.5,'height_mm':150.2,
              'paths':[[[0,0],[148.5,0],[148.5,150.2],[0,150.2],[74.25,75.1]]]}
        mapped=map_canvas(data,self.cfg);paper=self.cfg['paper'];p=np.array(mapped['paths'][0])
        xyz=np.array(paper['origin_m'])+(p[:,0,None]*paper['x_axis']+p[:,1,None]*paper['y_axis'])/1000
        expected=[[-359.39,-67.854,206.31],[-359.39,80.666,206.31],[-509.605,80.666,206.31],[-509.605,-67.854,206.31],[-434.4975,6.406,206.31]]
        np.testing.assert_allclose(xyz*1000,expected,atol=1e-10)

    def test_no_swap_uses_original_positive_xy_mapping(self):
        a=copy.deepcopy(self.a);a['swap_xy']=False;p=paper_frame(a)
        np.testing.assert_allclose(p['origin_m'],[-.509605,-.067854,.20631]);self.assertEqual(p['x_axis'],[1,0,0])
        self.assertAlmostEqual(p['width_mm'],150.215);self.assertAlmostEqual(p['height_mm'],148.520)

    def test_units_and_verification_not_promoted(self):
        original=demo_config();original['calibration_verified']=True
        c=apply_armvision(original,self.a);validate(c)
        self.assertEqual(c['planning']['lift_m'],.008);self.assertEqual(c['planning']['final_lift_m'],.060)
        self.assertEqual(c['planning']['draw_speed_m_s'],original['planning']['draw_speed_m_s'])
        self.assertFalse(c['calibration_verified'])
        with self.assertRaisesRegex(ValueError,'TCP'):assert_model_ready(c)

    def test_derived_fields_cannot_silently_disagree(self):
        for kind in ('height','paper','robot'):
            c=copy.deepcopy(self.cfg)
            if kind=='height':c['planning']['lift_m']=.03
            if kind=='paper':c['paper']['origin_m'][0]+=.01
            if kind=='robot':c['robot_id']=2
            with self.assertRaises(ValueError):validate(c)
        with self.assertRaises(ValueError):fields({})

    def test_unsupported_orientation_is_preserved_and_not_used_as_default(self):
        self.a['pose_uvw_deg']=[10,20,30];c=apply_armvision(self.cfg,self.a)
        self.assertEqual(c['armvision']['pose_uvw_deg'],[10,20,30])
        c['calibration_verified']=c['sdk_mapping_verified']=True
        with self.assertRaisesRegex(ValueError,'UVW'):assert_model_ready(c)

    def test_workbench_defaults_persistence_and_invalid_update(self):
        from app import State
        from tcb705.workbench import TCBWorkbench
        with tempfile.TemporaryDirectory() as tmp:
            w=TCBWorkbench(State(tmp),simulation=True)
            self.assertEqual(w.machine['armvision'],self.a)
            c=copy.deepcopy(w.machine);c['armvision']['a_mm'][0]-=1
            w.configure(c);saved=digest(w.machine)
            restored=TCBWorkbench(State(tmp),simulation=True)
            self.assertEqual(digest(restored.machine),saved)
            self.assertAlmostEqual(restored.machine['paper']['height_mm'],151.215)
            c['armvision']['a_mm']=c['armvision']['b_mm']
            with self.assertRaises(ValueError):w.configure(c)
            self.assertEqual(digest(w.machine),saved)

    def test_native_plan_uses_8mm_between_strokes_and_60mm_at_end(self):
        from tcb705.planner import plan,PHASE
        from tcb705.model import Model
        # Synthetic URDF-space fixture, NOT the imported physical table.
        a=copy.deepcopy(self.a);a.update(a_mm=[350,-50],b_mm=[450,50],z_table_mm=170,swap_xy=False)
        c=apply_armvision(demo_config(),a);c['calibration_verified']=c['sdk_mapping_verified']=True
        paths={'units':'mm','width_mm':100,'height_mm':100,'coordinate_system':'full_canvas_xy_up',
               'paths':[[[40,45],[60,45]],[[40,55],[60,55]]]}
        result=plan(paths,c);ph=result['interval_phase'];pos=result['geometric_positions']
        edges=np.r_[0,np.flatnonzero(ph[1:]!=ph[:-1])+1,len(ph)];heights=[]
        for s,e in zip(edges[:-1],edges[1:]):
            if ph[s]==PHASE['LIFT'] and s>0 and ph[s-1]==PHASE['DRAW']:
                np.testing.assert_allclose(pos[e,:2],pos[s,:2],atol=1e-12);heights.append(pos[e,2]-pos[s,2])
        np.testing.assert_allclose(heights,[.008,.06],atol=1e-12)
        poses=Model(c).fk_batch(result['q_rad'])
        np.testing.assert_allclose(poses[:,:3,2],np.tile([0,0,-1],(len(poses),1)),atol=2e-5)

class WebFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.calls=[];self.bad=None;owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                owner.calls.append((self.command,self.path));self.rfile.read(int(self.headers['Content-Length']))
                self.reply({'code':0,'data':{'token':'test-token'}})
            def do_GET(self):
                owner.calls.append((self.command,self.path))
                if self.headers.get('Authorization')!='Bearer test-token':return self.reply({'code':1})
                i=int(self.path.split('_')[-2]);v=[-509.605,-67.854,206.31,180,0,0][i]
                self.reply({'code':0,'data':{} if owner.bad=='missing' and i==2 else {'value':'NaN' if owner.bad=='nan' and i==2 else str(v)}})
            def reply(self,data):
                raw=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.controller={'remote_ip':'127.0.0.1','web_port':self.server.server_port}

    def test_only_login_and_same_six_world_variables_are_read(self):
        r=read_world(self.controller,1)
        self.assertEqual(r['world_mm_deg'],[-509.605,-67.854,206.31,180,0,0]);self.assertFalse(r['physical_motion'])
        self.assertEqual(self.calls,[('POST','/api/user/login')]+[('GET','/api/var/byname?name=r_world_fb_pos_1_%d_'%i) for i in range(6)])
        self.assertNotIn('test-token',json.dumps(r));self.assertFalse(r['controller_timestamp_available'])

    def test_missing_values_are_errors_not_zero(self):
        self.bad='missing'
        with self.assertRaises(ValueError):read_world(self.controller,1)

    def test_nan_feedback_is_rejected(self):
        self.bad='nan'
        with self.assertRaises(ValueError):read_world(self.controller,1)

    def test_invalid_connection_cannot_issue_requests(self):
        with self.assertRaises(ValueError):read_world({'remote_ip':'bad','web_port':8010},1)
        with self.assertRaises(ValueError):read_world(self.controller,0)
        self.assertEqual(self.calls,[])

    def test_workbench_job_reads_world_without_sdk_or_motion(self):
        from app import State
        from tcb705.workbench import TCBWorkbench
        with tempfile.TemporaryDirectory() as tmp:
            w=TCBWorkbench(State(tmp,allow_real=True),simulation=True)
            before=digest(w.machine)
            with patch('tcb705.bridge.feedback',side_effect=AssertionError('must not use model FK')):
                job=w.start('read_pen_pose',{'coordinate_source':'armvision','connection':self.controller,'robot_id':1})
                w.worker.join(5);self.assertFalse(w.worker.is_alive())
            result=w.jobs[job['id']];self.assertEqual(result['status'],'DONE',result)
            self.assertEqual(result['result']['world_mm_deg'],[-509.605,-67.854,206.31,180,0,0])
            self.assertEqual(before,digest(w.machine))

    def test_unconfigured_read_is_rejected_before_network(self):
        from app import State
        from tcb705.workbench import TCBWorkbench
        with tempfile.TemporaryDirectory() as tmp:
            w=TCBWorkbench(State(tmp),simulation=True)
            with self.assertRaisesRegex(ValueError,'allow-real'):
                w.start('read_pen_pose',{'coordinate_source':'armvision','connection':self.controller})
            self.assertEqual(self.calls,[])

if __name__=='__main__':unittest.main(verbosity=2)
