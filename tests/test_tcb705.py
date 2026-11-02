"""TCB705 numerical, persistence and HTTP integration tests; no hardware calls."""
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zlib

import numpy as np
from PIL import Image,ImageDraw
from tcb705.config import demo_config,validate,readiness
from tcb705.model import Model,ROOT,pose_error
from tcb705.planner import plan,PHASE,extrema
from tcb705 import artifact,bridge
from tcb705.collision import check as collision_check

def strokes():
    return dict(units='mm',width_mm=100,height_mm=100,coordinate_system='full_canvas_xy_up',
                paths=[[[40,45],[60,45]],[[40,55],[60,55]]])

def reference_fk(model,q):
    """Independent Rodrigues/matrix-chain reference, not native FK wrappers."""
    t=np.eye(4)
    for row,angle in zip(model.data,q):
        axis=row[16:19];x,y,z=axis
        skew=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
        r=np.eye(4);r[:3,:3]=np.eye(3)+math.sin(angle)*skew+(1-math.cos(angle))*(skew@skew)
        t=t@row[:16].reshape(4,4)@r
    return t@model.tool

class NumericalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg=demo_config();cls.model=Model(cls.cfg)

    def test_fk_matches_independent_chain(self):
        rng=np.random.RandomState(14)
        qs=rng.uniform(self.model.lower,self.model.upper,size=(40,7))
        expected=np.array([reference_fk(self.model,q) for q in qs])
        np.testing.assert_allclose(self.model.fk_batch(qs),expected,atol=2e-14)

    def test_jacobian_finite_difference(self):
        q=np.asarray(self.cfg['q_start_rad']);t=self.model.fk(q);j=self.model.jacobian(q);h=1e-6
        for i in range(7):
            delta=np.zeros(7);delta[i]=h
            plus=self.model.fk(q+delta);minus=self.model.fk(q-delta)
            np.testing.assert_allclose(j[:3,i],(plus[:3,3]-minus[:3,3])/(2*h),atol=2e-9)
            skew=((plus[:3,:3]-minus[:3,:3])/(2*h))@t[:3,:3].T
            np.testing.assert_allclose(j[3:,i],[skew[2,1],skew[0,2],skew[1,0]],atol=2e-9)

    def test_ik_nearby_seed_pose_accuracy_and_branch_continuity(self):
        rng=np.random.RandomState(9);q=np.array(self.cfg['q_start_rad'])
        for _ in range(20):
            target=self.model.fk(q+rng.normal(0,.003,7));r=self.model.solve(target,q,q)
            self.assertTrue(r['ok'],r);self.assertTrue(self.model.legal(r['q']))
            self.assertLess(np.max(np.abs(r['q']-q)),.03)
            p,a=pose_error(target,self.model.fk(r['q']));self.assertLess(p,1.1e-7);self.assertLess(a,1.1e-6)
            q=r['q']

    def test_sdk_mapping_permutation_sign_and_offset(self):
        cfg=copy.deepcopy(self.cfg);cfg['sdk_mapping']={'sdk_to_model_index':[6,1,5,3,0,2,4],
            'sign':[-1,1,-1,1,-1,1,-1],'offset_rad':[.1,-.2,.3,0,0,.1,0]}
        model=Model(cfg);q=np.asarray(cfg['q_start_rad'])
        np.testing.assert_allclose(model.from_sdk(model.to_sdk(q)),q,atol=1e-14)

    def test_nonfinite_and_invalid_geometry_rejected(self):
        with self.assertRaises(ValueError):self.model.fk([float('nan')]*7)
        with self.assertRaises(ValueError):self.model.solve(np.zeros((4,4)),self.cfg['q_start_rad'])
        cfg=copy.deepcopy(self.cfg);cfg['tool_rotation']=np.eye(3).tolist()
        with self.assertRaises(ValueError):validate(cfg)
        with self.assertRaises(ValueError):validate({})

    def test_obstacle_at_tool_is_rejected(self):
        cfg=copy.deepcopy(self.cfg);p=self.model.fk(cfg['q_start_rad'])[:3,3]
        cfg['collision']['boxes']=[{'min_m':(p-.01).tolist(),'max_m':(p+.01).tolist()}]
        with self.assertRaises(ValueError):collision_check(Model(cfg),cfg['q_start_rad'])

    def test_armvision_is_default_and_demo_is_separate(self):
        from tcb705.config import load
        actual=load()
        self.assertEqual(actual['armvision']['method'],'armvision-ab-z-uvw-v1')
        self.assertNotIn('armvision',self.cfg)
        self.assertFalse(actual['calibration_verified'])
        self.assertAlmostEqual(actual['planning']['lift_m'],.008)

class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg=demo_config();cls.result=plan(strokes(),cls.cfg);cls.model=Model(cls.cfg)

    def test_all_samples_vertical_and_lift_exactly_30mm(self):
        p=self.result;poses=self.model.fk_batch(p['q_rad'])
        np.testing.assert_allclose(poses[:,:3,2],np.tile([0,0,-1],(len(poses),1)),atol=2e-5)
        ph=p['interval_phase'];positions=p['geometric_positions']
        edges=np.r_[0,np.flatnonzero(ph[1:]!=ph[:-1])+1,len(ph)]
        lifts=0
        for start,end in zip(edges[:-1],edges[1:]):
            if ph[start]==PHASE['LIFT'] and start>0 and ph[start-1]==PHASE['DRAW']:
                lifts+=1;np.testing.assert_allclose(positions[end]-positions[start],[0,0,.03],atol=1e-12)
                mask=p['phase']==PHASE['LIFT']
                self.assertTrue(np.all(np.isfinite(poses[mask])))
        self.assertEqual(lifts,2)
        self.assertIsNone(p['metrics']['max_path_error_m'])

    def test_draw_does_not_connect_separate_strokes(self):
        p=self.result;poses=self.model.fk_batch(p['q_rad']);origin=np.array(self.cfg['paper']['origin_m'])
        mask=p['phase']==PHASE['DRAW'];ys=(poses[mask,1,3]-origin[1])*1000
        self.assertTrue(np.all(np.minimum(abs(ys-45),abs(ys-55))<.01))
        self.assertEqual(p['preview']['paths'],[])
        self.assertEqual(p['preview']['source'],'cloud')

    def test_c2_and_analytic_dynamic_limits(self):
        p=self.result;c=p['coefficients'];dt=np.diff(p['interval_times'])
        for i in range(len(c)-1):
            for order in range(3):
                a=c[i].copy();b=c[i+1].copy()
                for _ in range(order):
                    a=a[1:]*np.arange(1,len(a))[:,None];b=b[1:]*np.arange(1,len(b))[:,None]
                np.testing.assert_allclose(a.sum(axis=0)/dt[i]**order,b[0]/dt[i+1]**order,atol=2e-9)
        for i,row in enumerate(c):
            for order,key in ((1,'velocity_rad_s'),(2,'acceleration_rad_s2'),(3,'jerk_rad_s3')):
                self.assertTrue(np.all(extrema(row,order)[0]/dt[i]**order<=np.array(self.cfg['limits'][key])*(1+1e-8)))

    def test_sharp_corners_do_not_slow_entire_stroke(self):
        data=strokes();data['paths']=[[[0,0],[100,0],[100,100],[0,100],[0,0]]]
        p=plan(data,self.cfg);self.assertEqual(p['metrics']['corner_stops'],3)
        self.assertLess(p['metrics']['duration_s'],70)
        self.assertIsNone(p['metrics']['max_path_error_m'])

    def test_bad_input_and_cancellation_and_budget(self):
        data=strokes();data['paths'][0][0]=[-2,0]
        with self.assertRaisesRegex(ValueError,'纸面'):plan(data,self.cfg)
        with self.assertRaisesRegex(ValueError,'CANCELLED'):plan(strokes(),self.cfg,cancel=lambda:True)
        cfg=copy.deepcopy(self.cfg);cfg['planning']['max_frames']=3
        with self.assertRaisesRegex(ValueError,'FRAME_BUDGET'):plan(strokes(),cfg)
        cfg=copy.deepcopy(self.cfg);cfg['planning']['lift_m']=.02
        with self.assertRaises(ValueError):plan(strokes(),cfg)

    def test_y_down_conversion(self):
        data=strokes();data['coordinate_system']='full_canvas_xy_down';data['paths']=[[[40,30],[60,30]]]
        p=plan(data,self.cfg);draw=p['interval_phase']==PHASE['DRAW']
        xy=(p['geometric_positions'][1:][draw]-self.cfg['paper']['origin_m'])@np.asarray(self.cfg['paper']['y_axis'])*1000
        self.assertAlmostEqual(float(np.mean(xy)),70,places=3)

    def test_frozen_plan_and_configuration_change(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);artifact.save(self.result,folder,'demo');doc,rows=artifact.load(folder,self.cfg)
            self.assertEqual(len(rows),self.result['metrics']['frames']);self.assertFalse(doc['physical_authorized'])
            cfg=copy.deepcopy(self.cfg);cfg['paper']['origin_m'][0]+=.001
            with self.assertRaisesRegex(ValueError,'重新规划'):artifact.load(folder,cfg)
            raw=bytearray((folder/'trajectory.bin').read_bytes());raw[-1]^=1;(folder/'trajectory.bin').write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'SHA256'):artifact.load(folder)

    def test_native_runner_and_hardware_gate(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);artifact.save(self.result,folder,'demo')
            result=bridge.execute(folder,self.cfg,simulation=True)
            self.assertTrue(result['task_complete']);self.assertFalse(result['physical_motion'])
            self.assertFalse(result['timing_measured']);self.assertIsNone(result['deadline_misses'])
            with self.assertRaisesRegex(ValueError,'NOT_COMMISSIONED'):bridge.execute(folder,self.cfg)
            cfg=copy.deepcopy(self.cfg)
            for k in ('calibration_verified','dynamics_verified','sdk_mapping_verified','collision_model_verified'):cfg[k]=True
            cfg['execution']['transport_contract_verified']=True
            self.assertFalse(readiness(cfg)['physical_ready'])

    def test_native_runner_rejects_corrupt_binary(self):
        exe=ROOT/'build/tcb705'/('tcb_runner.exe' if sys.platform=='win32' else 'tcb_runner')
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);artifact.save(self.result,folder,'demo');p=folder/'trajectory.bin'
            raw=bytearray(p.read_bytes());raw[-5]^=1;p.write_bytes(raw)
            result=subprocess.run([str(exe),'--simulate-fast',str(p)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('CRC',result.stderr)

class HttpTests(unittest.TestCase):
    def setUp(self):
        from app import State,Server
        from scripts.arm_studio import BoardClient
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state=State(self.tmp.name)
        self.srv=Server(('127.0.0.1',0),self.state,robot='tcb705',simulation=True,profile=ROOT/'robots/tcb705/profile.demo.json')
        threading.Thread(target=self.srv.serve_forever,daemon=True).start()
        self.addCleanup(self.srv.server_close);self.addCleanup(self.srv.shutdown)
        self.client=BoardClient(port=self.srv.server_port)
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def wait(self,jid):
        for _ in range(300):
            s=self.client.get_jobs();j=next((j for j in s['jobs'] if j['id']==jid),None)
            if j and j['status']!='RUNNING' and s['active']!=jid:
                self.assertEqual(j['status'],'DONE',j);return j
            time.sleep(.03)
        self.fail('job timed out')

    def test_public_pipeline_register_plan_without_motion_preview_and_execute(self):
        from user_gui.workflow import BoardPipeline
        pipe=BoardPipeline('http://127.0.0.1:%d'%self.srv.server_port,self.tmp.name)
        caps=self.client.fetch_status();self.assertEqual(caps['motion_modes'],['tcb705'])
        jid=pipe.register(strokes(),lambda:False);pid=pipe.plan(jid,lambda:False)
        with self.assertRaisesRegex(Exception,'不再生成运动轨迹预测图'):pipe.preview(pid)
        self.assertFalse((self.srv.workbench.plans[pid]['folder']/'preview.svg').exists())
        result=pipe.execute(pid,lambda:False)
        self.assertTrue(result['result']['simulation']);self.assertFalse(result['result']['physical_motion'])
        newcfg=copy.deepcopy(self.srv.workbench.machine);newcfg['paper']['origin_m'][0]+=.001
        self.client.save_config(newcfg)
        with self.assertRaisesRegex(ValueError,'变更'):pipe.check_plan(pid)

    def test_legacy_motion_rejected_and_auth_required(self):
        with self.assertRaisesRegex(RuntimeError,'旧 STS'):self.client._request('/api/jog',method='POST',data={})
        req=urllib.request.Request(self.client.base_url+'/api/preset',data=b'{}',headers={'Content-Type':'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as caught:self.opener.open(req)
        self.assertEqual(caught.exception.code,403)
        with self.assertRaisesRegex(RuntimeError,'配置'):self.client.save_config({})

    def test_history_restores_only_plan_without_execution(self):
        from app import State
        from tcb705.workbench import TCBWorkbench
        jid=self.client._request('/api/preset',method='POST',data={'name':'line','width_mm':20,'height_mm':20})['id'];self.wait(jid)
        pid=self.client.plan(jid,mode='demo')['id'];self.wait(pid)
        restored=TCBWorkbench(State(self.tmp.name),simulation=True)
        self.assertIn(pid,restored.plans);self.assertIsNone(restored.active)
        self.assertEqual(restored.jobs,{})
        self.assertEqual(restored.prediction_data(pid)['source'],'cloud')
        with self.assertRaisesRegex(ValueError,'不再生成运动轨迹预测图'):restored.prediction_svg(pid)

    def test_non_simulation_cannot_execute_even_with_verified_flags(self):
        wb=self.srv.workbench;wb.simulation=False
        for key in ('calibration_verified','sdk_mapping_verified','dynamics_verified','collision_model_verified'):wb.machine[key]=True
        wb.machine['execution']['transport_contract_verified']=True
        with self.assertRaisesRegex(RuntimeError,'NOT_COMMISSIONED'):
            self.client._request('/api/execute',method='POST',data={'confirmed':True})

    def test_display_proxy_and_user_confirmation_flow(self):
        from user_gui.display_server import Hub,DisplayServer
        from user_gui.workflow import BoardPipeline,Workflow
        pipe=BoardPipeline(self.client.base_url,self.tmp.name)
        workflow=Workflow(pipe,self.tmp.name)
        hub=Hub(Path(self.tmp.name)/'uploads',token='test-pair-token')
        display=DisplayServer(('127.0.0.1',0),hub,interfaces=[],workflow=workflow)
        threading.Thread(target=display.serve_forever,daemon=True).start()
        self.addCleanup(display.server_close);self.addCleanup(display.shutdown)
        base='http://127.0.0.1:%d'%display.server_port
        def request(path,data=None,token=None):
            headers={'Content-Type':'application/json'}
            if token:headers['X-Screen-Token']=token
            raw=json.dumps(data).encode() if data is not None else None
            with self.opener.open(urllib.request.Request(base+path,data=raw,headers=headers)) as r:
                body=r.read();return json.loads(body) if 'json' in r.headers.get('Content-Type','') else body
        self.assertNotIn('token',request('/api/tcb/status'))
        self.assertIn('天链'.encode(),request('/debug'))
        with self.assertRaises(urllib.error.HTTPError):request('/api/tcb/preset',{},token='bad')
        token=request('/api/state')['control_token']
        self.assertEqual(request('/api/settings/open',{},token)['view'],'settings')
        self.assertEqual(request('/api/settings/close',{},token)['view'],'user')
        # Stub only paid cloud generation. Use actual image extraction, HTTP
        # registration, C++ IK, artifact preview and simulated native execution.
        image=Image.new('RGB',(160,160),'white');draw=ImageDraw.Draw(image);draw.line((60,75,100,75),fill='black',width=2)
        buffer=io.BytesIO();image.save(buffer,format='PNG');raw=buffer.getvalue()
        def local_cloud(raw,folder,cancelled):
            p=folder/'line.png';p.write_bytes(raw);return p
        with patch.object(pipe,'generate',side_effect=local_cloud):
            jid=workflow.reserve('phone01','request01');workflow.submit(jid,raw,{'id':1})
            workflow.worker.join(20);self.assertFalse(workflow.worker.is_alive())
            state=workflow.snapshot();self.assertEqual(state['phase'],'ready',state)
        self.assertFalse(any(j['kind']=='execute' for j in self.client.get_jobs()['jobs']))
        self.assertIn(b'<svg',request(state['preview_url']))
        with self.assertRaises(ValueError):workflow.start(jid,state['revision'],False)
        request('/api/workflow/start',{'job_id':jid,'revision':state['revision'],'confirmed':True},token)
        workflow.worker.join(10);self.assertEqual(workflow.snapshot()['phase'],'completed',workflow.snapshot())
        self.assertIn('模拟验证完成',workflow.snapshot()['message'])
        with self.assertRaises((ValueError,RuntimeError)):workflow.start(jid,state['revision'],True)

if __name__=='__main__':unittest.main(verbosity=2)
