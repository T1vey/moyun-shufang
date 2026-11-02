"""Synthetic commissioning evidence and transport fault injection, no hardware."""
import copy
import json
import math
import subprocess
import sys
import unittest
from unittest.mock import patch
import numpy as np
from tcb705.config import demo_config,digest,validate
from tcb705.model import Model,ROOT,rpy_matrix
from tcb705.commissioning import audit,pivot_tcp,pose
from tcb705.ethernet import endpoint,inspect


def raw_pose(t):
    r=t[:3,:3];pitch=math.atan2(-r[2,0],math.hypot(r[0,0],r[1,0]))
    roll=math.atan2(r[2,1],r[2,2]);yaw=math.atan2(r[1,0],r[0,0])
    return list(t[:3,3]*1000)+list(np.rad2deg([roll,pitch,yaw]))


class CoordinateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=demo_config();cls.model=Model(cls.config)
        rng=np.random.RandomState(712);base=np.eye(4);base[:3,:3]=rpy_matrix([.1,-.2,.3]);base[:3,3]=[.02,.03,-.01]
        cls.base=base;cls.samples=[]
        for _ in range(16):
            q=np.asarray(cls.config['q_start_rad'])+rng.uniform(-.15,.15,7)
            f=base@cls.model.evaluate(q)[2][-1];tcp=f@cls.model.tool
            degrees=cls.model.to_sdk(q)
            cls.samples.append(dict(schema='tcb705-static-capture-v1',read_only=True,robot_id=1,
                config_digest=digest(cls.config),joint_degrees=degrees,joint_degrees_after=degrees,
                sdk_version='synthetic-2.4.1',host_version='synthetic-1.9.82',tool_id=1,workspace_id=0,
                fk_flange_base_raw=raw_pose(f),fk_tcp_base_raw=raw_pose(tcp)))

    def test_known_base_and_tool_recovered_without_verification_flags(self):
        before=copy.deepcopy(self.config);r=audit(self.config,self.samples,'xyz_mm_uvw_deg_zyx')
        self.assertTrue(r['mapping_candidate_matches_sdk_fk']);self.assertFalse(r['physical_verified'])
        np.testing.assert_allclose(r['T_controller_base_from_model_candidate'],self.base,atol=1e-12)
        np.testing.assert_allclose(r['T_flange_tcp_controller_candidate'],self.model.tool,atol=1e-12)
        self.assertTrue(r['configured_tcp_matches_sdk']);self.assertEqual(self.config,before)

    def test_wrong_joint_sign_fails_holdout(self):
        config=copy.deepcopy(self.config);config['sdk_mapping']['sign'][3]=-1
        # Use a zero offset to bring the wrong-sign joints back inside the legal interval.
        config['sdk_mapping']['offset_rad'][3]=-4.8
        samples=copy.deepcopy(self.samples)
        for row in samples:row['config_digest']=digest(config)
        try:r=audit(config,samples,'xyz_mm_uvw_deg_zyx')
        except ValueError:return # a mapping outside URDF limits is also correctly rejected
        self.assertFalse(r['mapping_candidate_matches_sdk_fk'])

    def test_wrong_tcp_is_detected_separately_from_mapping(self):
        config=copy.deepcopy(self.config);config['T_flange_tcp'][2][3]+=.01
        samples=copy.deepcopy(self.samples)
        for row in samples:row['config_digest']=digest(config)
        r=audit(config,samples,'xyz_mm_uvw_deg_zyx')
        self.assertTrue(r['mapping_candidate_matches_sdk_fk']);self.assertFalse(r['configured_tcp_matches_sdk'])

    def test_repeated_pose_is_not_mapping_evidence(self):
        with self.assertRaisesRegex(ValueError,'5 度'):audit(self.config,[self.samples[0]]*12,'xyz_mm_uvw_deg_zyx')

    def test_bad_holdout_not_hidden_by_base_fit(self):
        samples=copy.deepcopy(self.samples);samples[-1]['fk_flange_base_raw'][0]+=10
        self.assertFalse(audit(self.config,samples,'xyz_mm_uvw_deg_zyx')['mapping_candidate_matches_sdk_fk'])

    def test_moving_or_changed_context_is_rejected(self):
        for field,value in [('joint_degrees_after',[0]*7),('tool_id',7),('robot_id',2),('config_digest','bad')]:
            with self.subTest(field=field):
                samples=copy.deepcopy(self.samples);samples[-1][field]=value
                with self.assertRaises(ValueError):audit(self.config,samples,'xyz_mm_uvw_deg_zyx')

    def test_pose_convention_must_be_explicit(self):
        with self.assertRaises(ValueError):pose([0]*6,None)
        p=pose([100,200,300,180,0,0],'xyz_mm_uvw_deg_zyx')
        np.testing.assert_allclose(p[:3,3],[.1,.2,.3]);np.testing.assert_allclose(p[:3,2],[0,0,-1],atol=1e-15)

    def test_controller_base_transform_applies_to_fk_ik_jacobian_and_frames(self):
        config=copy.deepcopy(self.config);config['T_controller_base_from_model']=self.base.tolist()
        model=Model(config);q=np.array(config['q_start_rad']);p,j,f=model.evaluate(q)
        original,oj,of=self.model.evaluate(q)
        np.testing.assert_allclose(p,self.base@original,atol=1e-13)
        np.testing.assert_allclose(f,np.matmul(self.base,of),atol=1e-13)
        np.testing.assert_allclose(j[:3],self.base[:3,:3]@oj[:3],atol=1e-13)
        np.testing.assert_allclose(j[3:],self.base[:3,:3]@oj[3:],atol=1e-13)
        qs=np.array([q,q+.001]);np.testing.assert_allclose(model.fk_batch(qs),[model.fk(x) for x in qs],atol=1e-13)
        target=model.fk(q+.001);solved=model.solve(target,q)
        self.assertTrue(solved['ok']);np.testing.assert_allclose(model.fk(solved['q']),target,atol=2e-6)

    def test_invalid_base_transform_rejected(self):
        config=copy.deepcopy(self.config);config['T_controller_base_from_model']=np.zeros((4,4)).tolist()
        with self.assertRaises(ValueError):validate(config)

    def pivot_frames(self):
        rng=np.random.RandomState(981);tip=np.array([.01,-.02,.09]);point=np.array([.3,-.1,.2]);frames=[]
        for _ in range(12):
            r=rpy_matrix(rng.uniform(-1,1,3));t=np.eye(4);t[:3,:3]=r;t[:3,3]=point-r@tip;frames.append(t)
        return frames,tip,point

    def test_pivot_recovers_translation_and_not_orientation(self):
        frames,tip,point=self.pivot_frames();r=pivot_tcp(frames)
        np.testing.assert_allclose(r['tcp_translation_m'],tip,atol=1e-12)
        np.testing.assert_allclose(r['pivot_base_m'],point,atol=1e-12)
        self.assertFalse(r['orientation_determined']);self.assertFalse(r['physical_verified'])

    def test_pivot_degenerate_and_shifted_contact_are_rejected(self):
        with self.assertRaises(ValueError):pivot_tcp([np.eye(4)]*8)
        frames,_,_=self.pivot_frames();frames[-1][:3,3]+=.02
        with self.assertRaises(ValueError):pivot_tcp(frames)


class NetworkTests(unittest.TestCase):
    def setUp(self):self.controller={'local_ip':'192.168.4.23','remote_ip':'192.168.4.4','port':8001,'web_port':8010}

    def test_unicast_and_two_different_addresses_required(self):
        for address in ('','0.0.0.0','127.0.0.1','224.1.1.1','255.255.255.255','::1','192.168.4.23'):
            with self.subTest(address=address),self.assertRaises(ValueError):endpoint(dict(self.controller,remote_ip=address))
        self.assertEqual(endpoint(self.controller),('192.168.4.23','192.168.4.4'))

    def test_config_allows_unset_addresses_but_not_invalid_values(self):
        c=demo_config();validate(c)
        for key,value in [('local_ip','nonsense'),('port',True),('web_port',0)]:
            bad=copy.deepcopy(c);bad['controller'][key]=value
            with self.assertRaises(ValueError):validate(bad)

    def mock_result(self,obj):return subprocess.CompletedProcess([],0,json.dumps(obj),'')
    def test_route_checks_without_network_mutations(self):
        with patch('tcb705.ethernet.subprocess.run',side_effect=[self.mock_result([
                {'ifname':'eth0','addr_info':[{'local':'192.168.4.23'}]}]),self.mock_result([{'dev':'eth0'}])]) as run:
            r=inspect(self.controller);self.assertTrue(r['route_ok']);self.assertFalse(r['controller_verified'])
            self.assertEqual(run.call_count,2)
            self.assertEqual(run.call_args_list[1].args[0],['ip','-j','-4','route','get','192.168.4.4','from','192.168.4.23'])

    def test_missing_address_and_wrong_interface_rejected(self):
        with patch('tcb705.ethernet.subprocess.run',return_value=self.mock_result([])),self.assertRaises(ValueError):inspect(self.controller)
        with patch('tcb705.ethernet.subprocess.run',side_effect=[self.mock_result([
            {'ifname':'eth0','addr_info':[{'local':'192.168.4.23'}]}]),self.mock_result([{'dev':'wlan0'}])]),self.assertRaises(ValueError):inspect(self.controller)


class StreamTests(unittest.TestCase):
    def test_native_stream_failure_injection(self):
        executable=ROOT/'build/tcb705'/('tcb_stream_selftest.exe' if sys.platform=='win32' else 'tcb_stream_selftest')
        result=subprocess.run([str(executable)],capture_output=True,text=True,timeout=10,check=True)
        report=json.loads(result.stdout);self.assertTrue(report['passed']);self.assertEqual(report['tests'],13)
        self.assertFalse(report['physical_motion']);self.assertFalse(report['sdk_linked'])


if __name__=='__main__':unittest.main()
