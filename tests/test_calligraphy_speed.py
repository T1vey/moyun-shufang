"""Main GUI speed owns brush execution; no hardware and no motion IO."""
import copy
import unittest
from unittest.mock import Mock
from types import SimpleNamespace

from calligraphy.presets import BRUSH,binding,profile,task,validate_task
from tcb705.artifact import check_brush_nodes,nodes_hash
from tcb705.config import demo_config
from tcb705.sdk_motion import SdkMotion,SdkClient,live_speed


class BrushSpeedTests(unittest.TestCase):
    def config(self):
        c=demo_config()
        c['calligraphy']=dict(BRUSH,max_press_mm=4,speed_pct=5,verified=True,calibration_binding=binding(c))
        c['execution']['web_program']=dict(mode='joint',draw_speed_pct=40,air_speed_pct=40)
        return c

    def test_speed_is_not_geometry_or_calibration(self):
        c=self.config();p=task('heng',20,c)
        self.assertNotIn('speed_pct',profile(c))
        c['execution']['web_program']['draw_speed_pct']=75
        self.assertTrue(profile(c,True)['verified'])
        validate_task(p,c)
        legacy=copy.deepcopy(p);legacy['calligraphy']['brush']['speed_pct']=5
        validate_task(legacy,c)
        n=dict(calligraphy=legacy['calligraphy'],positions_m=[[0,0,0],[0,0,1]],interval_feed_ratio=[.5])
        h=nodes_hash(n);check_brush_nodes(n,c)
        self.assertEqual(h,nodes_hash(n))
        n['calligraphy']['brush']['max_press_mm']=3
        with self.assertRaises(ValueError):check_brush_nodes(n,c)

    def test_legacy_feed_never_overrides_live_gui_global_speed(self):
        c=self.config();sdk=Mock();sdk.move.side_effect=[10,11,12]
        sdk.finished.return_value=None;sdk.set_speed.side_effect=lambda p:p
        m=SdkMotion(sdk,Mock(),c)
        blocks=[dict(fc='hmcRobotFree',code=dict(endp=[0]*7,speed=2.5,brush_feed_ratio=f)) for f in (.3,.21,.76)]
        content={'programs':[{'codeBlock':blocks}]}
        with m:
            m.set_speed(40);m.start(content,lambda:False)
            self.assertEqual(len(sdk.move.call_args_list),1)
            sdk.set_speed.assert_called_once_with(40)
            self.assertNotIn('ratio',sdk.move.call_args_list[0].kwargs)
            self.assertEqual(live_speed(60),60)
            sdk.set_speed.assert_called_with(60)  # Applies even while the first segment is in flight.
            sdk.finished.side_effect=lambda seq: True if seq==10 else None
            m.pump()
            self.assertNotIn('ratio',sdk.move.call_args_list[1].kwargs)
            live_speed(100);sdk.finished.side_effect=None;sdk.finished.return_value=True
            m.pump()
            self.assertNotIn('ratio',sdk.move.call_args_list[2].kwargs)
        self.assertEqual(len(sdk.move.call_args_list),3)
        self.assertEqual([c.args[0] for c in sdk.set_speed.call_args_list],[40,60,100])

    def test_home_ordinary_and_uniform_brush_blocks_share_global_speed(self):
        c=self.config();sdk=Mock();sdk.move.return_value=10
        sdk.finished.return_value=True;sdk.set_speed.side_effect=lambda p:p
        m=SdkMotion(sdk,Mock(),c);m.set_speed(40)
        for fc,n,extra in [('hmcLine',6,{}),('hmcRobotFree',7,{}),
                           ('hmcRobotFree',7,{'brush_uniform_speed':True})]:
            m.start({'programs':[{'codeBlock':[dict(fc=fc,code=dict(endp=[0]*n,speed=40,**extra))]}]},lambda:False)
        self.assertEqual(sdk.move.call_count,3)
        self.assertTrue(all('ratio' not in c.kwargs for c in sdk.move.call_args_list))
        sdk.set_speed.assert_called_once_with(40)

    def test_small_ratio_is_not_rounded_to_zero_global_override(self):
        client=SdkClient.__new__(SdkClient);client.call=Mock(return_value=['10'])
        client.move('J',[0]*7,ratio=.0004)
        self.assertEqual(client.call.call_args.args[0].split()[4],'0.000400')

    def test_brush_home_program_fallback_uses_same_gui_speed(self):
        from tcb705 import web_executor as W
        from tcb705.model import Model
        from unittest.mock import patch
        c=self.config();model=Model(c)
        c['execution']['web_program'].update(ik_role='execution',home=dict(enabled=True,
            joint_degrees=model.to_sdk(c['q_start_rad']),speed_pct=10))
        ctrl=SimpleNamespace(state=lambda:dict(_phc_alarm_='0',g_state_='1',g_servo_statero_='1',_phc_ctrlkey='100'),
                             active_alarms=lambda:[],pose=lambda:[0,0,300,180,0,0])
        motion=Mock();motion.start.return_value=False
        with patch.object(W,'home_program',wraps=W.home_program) as program:
            with self.assertRaises(W.CancelledByUser):
                W.go_home(ctrl,c,W.settings(c),lambda *a,**kw:None,lambda:False,
                          lambda:0,lambda _:None,'HOME',motion,strict=True)
            self.assertEqual(program.call_args.args[1]['home']['speed_pct'],40)
        self.assertEqual(c['execution']['web_program']['home']['speed_pct'],10)

if __name__=='__main__':unittest.main()
