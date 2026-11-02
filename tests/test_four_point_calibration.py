"""Four physical corners, affine XYZ fit, stale marks and pending-state workflow."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np
import planning
from drawing_geometry import calibration_signature, paper_frame
from drawing_prediction import feedback_preview
from four_point_calibration import POINTS, UNIT_CORNERS, begin_calibration, calibrate_four_points, fit_positions, ready, validate
from motion import validate_machine
from test_feedback_drawing import machine
from test_studio_jobs import studio_fixture, Widget, DeferredThreads


def fixture():
    m=machine();m['paper'].update(drawing_offset_mm=[50,0],draw_height_offset_m=.004,contact_height_offset_m=.002)
    origin=np.array([.203,-.026,.122]);axes=np.array([[.94,-.24],[.09,1.29],[.008,-.04]])
    points={name:origin+.2*axes@xy for name,xy in zip(POINTS,UNIT_CORNERS)}
    captures={name:dict(counts={j['id']:2048+(i+1)*10 for j in m['joints']},
                       signature=calibration_signature(m),side_mm=200.) for i,name in enumerate(POINTS)}
    def pose(q):
        j=m['joints'][0];count=round(j['zero_count']+j['direction']*q[0]*4096/(2*np.pi))
        i=int((count-2048)//10)-1;p=np.eye(4);p[:3,3]=points[POINTS[i]];return p
    model=Mock();model.pose.side_effect=pose
    return m,points,captures,model,origin,axes


class FourPointMathTests(unittest.TestCase):
    def test_large_residual_override_persists_and_keeps_measured_error(self):
        from app import State
        from workbench import Workbench
        m,p,c,model,_,_=fixture();p['D']+=np.array([0,0,.06])
        with patch('planning.Model',return_value=model),tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError,'超过'):calibrate_four_points(m,c,200)
            updated,detail=calibrate_four_points(m,c,200,allow_large_residual=True)
            self.assertAlmostEqual(detail['fit']['max_fit_residual_mm'],15.,places=9)
            self.assertAlmostEqual(detail['fit']['fit_limit_mm'],5.)
            self.assertTrue(detail['fit']['residual_override_applied'])
            w=Workbench(State(Path(t)));w.configure(updated)
            reloaded=Workbench(State(Path(t)))
            self.assertEqual(reloaded.machine, json.loads(json.dumps(updated)))
            validate(reloaded.machine,require_ready=True)
            del updated['paper']['xy_calibration']['residual_override']
            with self.assertRaisesRegex(ValueError,'超过'):validate(updated)

    def test_override_does_not_accept_crossed_or_duplicate_geometry(self):
        _,p,_,_,_,_=fixture()
        for bad in ({name:p['A'] for name in POINTS},dict(A=p['A'],B=p['C'],C=p['B'],D=p['D'])):
            with self.assertRaises(ValueError):fit_positions(bad,200,[0,0,1],allow_large_residual=True)

    def test_override_record_must_match_recomputed_residual(self):
        m,p,c,model,_,_=fixture();p['D']+=np.array([0,0,.06])
        with patch('planning.Model',return_value=model):
            updated,_=calibrate_four_points(m,c,200,allow_large_residual=True)
            updated['paper']['xy_calibration']['residual_override']['accepted_max_residual_mm']=0.
            with self.assertRaisesRegex(ValueError,'强制应用记录'):validate(updated)

    def test_exact_affine_xyz_uses_square_centre_and_clears_old_offsets(self):
        m,p,c,model,origin,axes=fixture();before=copy.deepcopy(m)
        with patch('planning.Model',return_value=model):
            updated,d=calibrate_four_points(m,c,200);validate(updated,require_ready=True)
        self.assertEqual(m,before);self.assertEqual(updated['model'],m['model'])
        self.assertEqual(updated['joints'],m['joints']);self.assertTrue(ready(updated['paper']))
        frame=paper_frame(updated['paper'])
        np.testing.assert_allclose(frame['origin'],origin,atol=1e-12)
        np.testing.assert_allclose(np.asarray([frame['u'],frame['v']]).T@frame['matrix'],axes,atol=1e-12)
        self.assertEqual(updated['paper']['drawing_offset_mm'],[0,0])
        self.assertEqual(updated['paper']['draw_height_offset_m'],0.)
        self.assertEqual(updated['paper']['contact_height_offset_m'],0.)
        self.assertLess(d['fit']['max_fit_residual_mm'],1e-9)

    def test_fourth_corner_contributes_to_fit_and_residual_is_reported(self):
        _,p,_,_,origin,_=fixture();p['D']=p['D']+np.array([0,0,.004])
        fit=fit_positions(p,200,[0,0,1])
        np.testing.assert_allclose(fit['origin_m'],origin+[0,0,.001],atol=1e-12)
        self.assertAlmostEqual(fit['max_fit_residual_mm'],1.,places=10)
        self.assertEqual(len(fit['fit_residual_mm']),4)

    def test_all_four_canvas_corners_and_preview_match_physical_coordinates(self):
        m,p,c,model,_,_=fixture()
        with patch('planning.Model',return_value=model):updated,_=calibrate_four_points(m,c,200)
        path=[[0,0],[200,0],[200,200],[0,200],[0,0]]
        paths=dict(units='mm',width_mm=200,height_mm=200,paths=[path])
        spec=planning.drawing_spec(paths,updated['paper'],[0]*5);trace=[]
        for i,segment in enumerate(spec['strokes'][0]['segments']):
            np.testing.assert_allclose(segment['start_m'],p[POINTS[i]],atol=1e-12)
            np.testing.assert_allclose(segment['end_m'],p[POINTS[(i+1)%4]],atol=1e-12)
            for k in ('start_m','end_m'):
                trace.append(dict(phase='DRAW',stroke=0,source_segment_id=[0,i],model_tip_m=segment[k],elapsed_s=len(trace)))
        preview=feedback_preview(dict(paths=paths,machine=updated,drawing=spec),dict(points=trace))
        for i,row in enumerate(preview['rows']):
            # Preview preserves the preceding endpoint when joining feedback rows.
            points=np.asarray(row['predicted_points_mm'])
            np.testing.assert_allclose(points[[0,-1]],path[i:i+2],atol=1e-10)

    def test_offsets_and_height_use_fitted_axes_and_normal_once(self):
        m,_,c,model,origin,axes=fixture()
        with patch('planning.Model',return_value=model):updated,_=calibrate_four_points(m,c,200)
        updated['paper'].update(drawing_offset_mm=[20,-10],draw_height_offset_m=.001,contact_height_offset_m=.002)
        f=paper_frame(updated['paper'])
        np.testing.assert_allclose(f['origin'],origin+axes@np.array([.02,-.01])+.003*f['normal'],atol=1e-12)

    def test_missing_stale_partial_counts_and_changed_span_rejected(self):
        m,_,c,model,_,_=fixture()
        for mutate in (lambda x:x.pop('D'),lambda x:x['D'].update(signature='old'),
                       lambda x:x['A']['counts'].pop(5),lambda x:x['B'].update(side_mm=100),
                       lambda x:x['C']['counts'].update({2:True})):
            bad=copy.deepcopy(c);mutate(bad)
            with patch('planning.Model',return_value=model),self.assertRaises(ValueError):calibrate_four_points(m,bad,200)
        self.assertNotIn('xy_calibration',m['paper'])

    def test_duplicate_collinear_crossed_and_inconsistent_points_rejected(self):
        _,p,_,_,_,_=fixture()
        examples=[{name:p['A'] for name in POINTS},
                  {name:np.array([i*.1,0.,0.]) for i,name in enumerate(POINTS)},
                  dict(A=p['A'],B=p['C'],C=p['B'],D=p['D']),
                  dict(p,D=p['D']+np.array([0,0,.03]))]
        for example in examples:
            with self.assertRaises(ValueError):fit_positions(example,200,[0,0,1])

    def test_canvas_downward_y_preserves_coordinates_but_lift_is_above_paper(self):
        m,p,c,model,origin,axes=fixture()
        axes[:,1]*=-1
        for name,xy in zip(POINTS,UNIT_CORNERS):p[name]=origin+.2*axes@xy
        with patch('planning.Model',return_value=model):
            updated,_=calibrate_four_points(m,c,200);validate(updated,require_ready=True)
        frame=paper_frame(updated['paper'])
        self.assertGreater(frame['normal'][2],.99)
        self.assertLess(frame['pen_axis'][2],-.99)
        np.testing.assert_allclose(np.asarray([frame['u'],frame['v']]).T@frame['matrix'],axes,atol=1e-12)
        self.assertLess(np.linalg.det(frame['matrix']),0.)
        for name,xy in zip(POINTS,UNIT_CORNERS):
            actual=frame['origin']+np.asarray([frame['u'],frame['v']]).T@frame['matrix']@(.2*xy)
            np.testing.assert_allclose(actual,p[name],atol=1e-12)

    def test_config_does_not_trust_tampered_fit(self):
        m,_,c,model,_,_=fixture()
        with patch('planning.Model',return_value=model):
            updated,_=calibrate_four_points(m,c,200)
            updated['paper']['xy_calibration']['fit']['origin_m'][2]+=.01
            with self.assertRaisesRegex(ValueError,'拟合结果不一致'):validate(updated)

    def test_pending_disables_drawing_but_leaves_encoder_configuration_valid(self):
        m,_,_,_,_,_=fixture();m['paper']['xy_calibration']=dict(schema='old-three-point')
        pending=begin_calibration(m)
        self.assertNotIn('xy_calibration',pending['paper']);self.assertFalse(ready(pending['paper']))
        validate_machine(pending)
        with self.assertRaisesRegex(ValueError,'四点标定尚未完成'):validate_machine(pending,drawing=True)
        with self.assertRaisesRegex(ValueError,'四点标定尚未完成'):planning.drawing_spec({},pending['paper'],[0]*5)


class FourPointWorkflowTests(unittest.TestCase):
    def test_gui_restart_with_saved_calibration_does_not_ask_for_new_marks(self):
        m,p,c,model,_,_=fixture();p['D']+=np.array([0,0,.06])
        with patch('planning.Model',return_value=model):updated,_=calibrate_four_points(m,c,200,True)
        s=studio_fixture();s._geometry_captures={};s.var_geometry_span=Widget()
        s.var_draw_x=Widget();s.var_draw_y=Widget();s.lbl_geometry_points=Widget()
        s._sync_four_point_fields(updated,load_draft=True)
        self.assertEqual(s.btn_plan.options['state'],'normal')
        self.assertIn('无需重新采点',s.lbl_geometry_points.options['text'])

    def test_gui_apply_saves_four_point_config_without_planning_or_motion(self):
        m,p,captures,model,_,_=fixture();m=begin_calibration(m)
        s=studio_fixture();s._four_point_ready=False;s._geometry_captures=captures
        s.var_geometry_span=Widget('200');s.var_draw_x=Widget();s.var_draw_y=Widget()
        s.var_geometry_force=Widget(True)
        s.lbl_geometry_points=Widget();s.lbl_drawing_alignment=Widget()
        s._sync_pen_height_fields=Mock();s._invalidate_geometry_plan=Mock();s._plan=Mock()
        s.client.fetch_status.return_value=dict(four_point_calibration_supported=True)
        s.client.fetch_config.return_value=m;threads=DeferredThreads()
        with tempfile.TemporaryDirectory() as t,patch('scripts.arm_studio.threading.Thread',threads.thread),\
             patch('scripts.arm_studio.Path.home',return_value=Path(t)),\
             patch('scripts.arm_studio.refresh_existing_calibration_snapshots',return_value=[]),\
             patch('planning.Model',return_value=model):
            s._apply_geometry_calibration();threads.run_next();s.root.drain()
            saved=s.client.save_config.call_args.args[0];validate(saved,require_ready=True)
            self.assertTrue(s._four_point_ready);self.assertEqual(s.var_draw_x.get(),'0')
            s._plan.assert_not_called();s.client.execute.assert_not_called()
            s._invalidate_geometry_plan.assert_called_once()

    def test_gui_restores_only_matching_capture_drafts(self):
        m,_,captures,_,_,_=fixture();m=begin_calibration(m)
        s=studio_fixture();s._geometry_captures={};s._show_geometry_section=Mock()
        s.var_geometry_span=Widget();s.var_draw_x=Widget();s.var_draw_y=Widget();s.lbl_geometry_points=Widget()
        with tempfile.TemporaryDirectory() as t:
            s._geometry_draft_path=Path(t)/'draft.json'
            for signature,expected in [('stale',set()),(calibration_signature(m),set(POINTS))]:
                s._geometry_draft_path.write_text(json.dumps(dict(signature=signature,side_mm=200,captures=captures)))
                s._sync_four_point_fields(m,load_draft=True);s.root.drain()
                self.assertEqual(set(s._geometry_captures),expected)

    def test_pending_read_pose_is_read_only_and_home_cannot_open_port(self):
        from app import State
        from protocol import DemoPort
        from workbench import Workbench
        with tempfile.TemporaryDirectory() as t:
            port=DemoPort();factory=Mock(return_value=port)
            w=Workbench(State(Path(t),allow_real=True,real_factory=factory),allow_motion=True)
            w.configure(begin_calibration(machine()))
            data=dict(mode='real',port='/dev/ttyACM0',baudrate=1000000,confirmed=True)
            job=w.start('read_pen_pose',data);w.worker.join(3)
            self.assertEqual(w.jobs[job['id']]['status'],'DONE')
            self.assertTrue(all(packet[4] in (1,2) for packet in port.writes))
            factory.reset_mock();job=w.start('home',data);w.worker.join(3)
            self.assertEqual(w.jobs[job['id']]['status'],'FAILED');factory.assert_not_called()

    def test_legacy_config_cannot_replace_pending_four_point_configuration(self):
        from app import State
        from workbench import Workbench
        with tempfile.TemporaryDirectory() as t:
            w=Workbench(State(Path(t)));old=machine();w.configure(begin_calibration(old))
            before=w.config_file.read_bytes()
            with self.assertRaisesRegex(ValueError,'不能恢复旧三点'):w.configure(old)
            self.assertEqual(w.config_file.read_bytes(),before)

    def test_gui_requires_all_four_marks_and_saves_read_only_capture_draft(self):
        m,_,captures,_,_,_=fixture();m=begin_calibration(m)
        s=studio_fixture();s._four_point_ready=False;s._geometry_captures={}
        s.var_geometry_span=Widget('200');s.var_calibration_source=Widget('板端')
        s.btn_geometry_apply=Widget();s.lbl_geometry_points=Widget();s.client.fetch_config.return_value=m
        s.client.read_pen_pose.return_value=dict(id='pose');s._wait_job=Mock()
        threads=DeferredThreads()
        with tempfile.TemporaryDirectory() as t,patch('scripts.arm_studio.threading.Thread',threads.thread):
            s._geometry_draft_path=Path(t)/'draft.json'
            for name in POINTS:
                s._wait_job.return_value=dict(status='DONE',result=dict(counts=captures[name]['counts']))
                s._capture_geometry_point(name);threads.run_next();s.root.drain()
            self.assertEqual(set(s._geometry_captures),set(POINTS))
            self.assertEqual(s.btn_geometry_apply.options['state'],'normal')
            self.assertEqual(s.btn_plan.options['state'],'disabled')
            self.assertEqual(set(json.loads(s._geometry_draft_path.read_text())['captures']),set(POINTS))
            s.client.save_config.assert_not_called();s.client.execute.assert_not_called()


if __name__=='__main__':unittest.main()
