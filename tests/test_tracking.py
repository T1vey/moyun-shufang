import sys
from pathlib import Path
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'scripts'))
from planning import nominal
from simulate_closed_loop import machine_fixture
from motion import counts_from_angles,Executor
from tracking import TrackingMonitor
from protocol import DemoPort
from unittest.mock import patch
from types import SimpleNamespace

class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.model,paper,self.q=nominal(); self.machine=machine_fixture(self.model,paper)
        self.counts=counts_from_angles(self.machine,self.q)
        self.command=dict(pen_down=True,tip_target_m=self.model.pose(self.q)[:3,3].tolist())
    def test_counts_can_pass_old_gate_but_fail_millimetre_gate(self):
        counts=dict(self.counts); counts[2]+=40
        row=TrackingMonitor(self.machine).observe(counts,self.command)
        self.assertFalse(row['qualified']); self.assertGreater(row['normal_error_m'],.001)
    def test_quantization_and_lift(self):
        monitor=TrackingMonitor(self.machine)
        self.assertTrue(monitor.observe(self.counts,self.command)['qualified'])
        self.assertIsNone(monitor.observe(self.counts,dict(pen_down=False)))
        self.assertTrue(monitor.summary()['tracking_qualified'])
    def test_paper_normal_not_world_z(self):
        self.machine['paper']['normal']=[1,0,0]
        counts=dict(self.counts); counts[1]+=5
        monitor=TrackingMonitor(self.machine); row=monitor.observe(counts,self.command)
        delta=monitor.model.pose(__import__('motion').angles_from_counts(self.machine,counts))[:3,3]-self.command['tip_target_m']
        self.assertAlmostEqual(row['normal_error_m'],abs(delta[0]))
    def test_executor_stops_before_next_target_on_pen_error(self):
        self.machine['execution']={'guard_policy':'strict'}
        port=DemoPort(); port.positions.update(self.counts)
        clock=[0.]; frames=[(.1,dict(self.counts)),(.2,dict(self.counts))]
        original=__import__('motion').read_all
        def shifted(*args,**kwargs):
            c=original(*args,**kwargs)
            if clock[0]>=.15: c[2]+=40
            return c
        audit=[]
        with patch('motion.time.monotonic',lambda:clock[0]), patch('motion.time.sleep',lambda dt:clock.__setitem__(0,clock[0]+dt)), patch('motion.read_all',shifted):
            with self.assertRaisesRegex(RuntimeError,'笔尖跟踪'):
                Executor(port,self.machine,audit=lambda k,v:audit.append((k,v))).run_frames(frames,self.counts,[self.command,self.command])
        self.assertTrue(any(k=='TRACKING_FAIL' for k,v in audit))
        self.assertEqual(len([w for w in port.writes if w[4]==0x83]),2) # first target + hold
if __name__=='__main__': unittest.main()
