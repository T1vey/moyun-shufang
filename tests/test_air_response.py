import unittest
from unittest.mock import patch
import numpy as np
from scripts.measure_air_response import plan_line,air_guard,measure
from tcb705.config import load
from tcb705.model import Model,ROOT

class Clock:
    def __init__(self):self.t=0.
    def __call__(self):self.t+=.005;return self.t

class Sdk:
    def __init__(self,m,q,refuse=False,stale=False,fail=False):
        self.m=m;self.q=q;self.end=q;self.n=0;self.refuse=refuse;self.stale=stale;self.fail=fail
    def move(self,kind,target,**kw):
        self.end=self.m.from_sdk(target);return 0 if self.refuse else 12
    def call(self,cmd):
        self.n+=1
        q=self.q if self.stale else self.q+(self.end-self.q)*min(1,self.n/20)
        return [str(v) for v in self.m.to_sdk(q)]
    def finished(self,seq):return False if self.fail else (True if self.n>=20 and not self.stale else None)
    def state(self):return dict(move=0,paused=False,link=True)

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=load(ROOT/'robots/tcb705/profile.armvision_joint.json');cls.m=Model(cls.c)
        cls.q=cls.m.from_sdk([-1.063614,30.688248,.352936,72.049026,-.163422,77.785263,-.712051])
        cls.z=cls.c['paper']['origin_m'][2]
    def test_plan_is_bounded_air_line(self):
        for direction in (1,-1):
            sdk,anchor,g=plan_line(self.m,self.q,direction,self.z)
            p=self.m.fk(self.m.from_sdk(sdk))
            self.assertLess(abs((p[1,3]-anchor[1,3])*1000-direction*5),.01)
            self.assertLess(g['line_error_mm'],.05)
    def test_reject_insufficient_clearance(self):
        with self.assertRaisesRegex(ValueError,'AIR_CLEARANCE'):
            plan_line(self.m,self.q,1,self.m.fk(self.q)[2,3]-.02)
    def test_reject_nonfinite_and_large_excursion(self):
        anchor=self.m.fk(self.q)
        with self.assertRaisesRegex(ValueError,'INVALID_JOINTS'):
            air_guard(self.m,np.full((1,7),np.nan),anchor,self.z)
        bad=self.q.copy();bad[0]+=.15
        with self.assertRaises(ValueError):air_guard(self.m,bad[None],anchor,self.z)
    def test_measures_feedback_not_command_ack(self):
        with patch('scripts.measure_air_response.time.sleep'):
            r=measure(Sdk(self.m,self.q),self.m,self.q,1,self.z,Clock())
        self.assertGreater(r['release_to_feedback_threshold_ms'],r['planning_ms']+r['command_ack_ms'])
        self.assertGreater(len(r['samples']),19)
    def test_refusal_failure_stale_all_abort(self):
        for kw,error in [({'refuse':True},'NO_TRACKABLE'),({'fail':True},'SDK_MOTION_FAILED'),({'stale':True},'NO_FEEDBACK_PROGRESS')]:
            with self.subTest(kw=kw),patch('scripts.measure_air_response.time.sleep'):
                with self.assertRaisesRegex(RuntimeError,error):measure(Sdk(self.m,self.q,**kw),self.m,self.q,1,self.z,Clock())

if __name__=='__main__':unittest.main()
