"""Read historical controller-DH/nodes; generate offline fixtures, no hardware IO."""
from pathlib import Path
import hashlib,json,math
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
SOURCE=ROOT/'build/tcb705/startup_speed_20261020'
machine_path=SOURCE/'machine.json';nodes_path=SOURCE/'nodes.json'
c=json.loads(machine_path.read_text(encoding='utf-8-sig'))
n=json.loads(nodes_path.read_text(encoding='utf-8-sig'))
assert c['kinematics']['source']=='controller_dh'
assert c['sdk_mapping']==dict(sdk_to_model_index=list(range(7)),sign=[1]*7,offset_rad=[0]*7)
assert 'model_corrections' not in c and 'T_controller_base_from_model' not in c

# Preserve the existing application's standard-DH-to-origin/Rz convention.
# The copied constants are from the controller record, not the URDF fixture.
import sys
sys.path.insert(0,str(ROOT))
from tcb705.model import dh_rows
rows,tail=dh_rows(c['kinematics'])
model=np.array(rows);tool=tail@np.array(c['T_flange_tcp'])
positions=np.array(n['positions_m'],dtype=float)
joints=np.radians(np.array(n['sdk_degrees'],dtype=float))
rotation=np.array(c['tool_rotation'])
opts=c['ik'];options=[opts['position_tolerance_m'],opts['orientation_tolerance_rad'],opts['max_iterations'],opts['step_limit_rad'],.1,opts['damping'],opts['reference_weight']]

# Confirm a source-supported initial seed, rather than borrowing q_start_rad.
home=np.radians(c['execution']['web_program']['home']['joint_degrees'])
assert np.max(np.abs(joints[0]-home))<1e-14

def fk(q):
    t=np.eye(4)
    for row,a in zip(model,q):
        a*=row[18];co,si=math.cos(a),math.sin(a)
        rz=np.eye(4);rz[:2,:2]=[[co,-si],[si,co]]
        t=t@row[:16].reshape(4,4)@rz
    return t@tool

draw_start=None;phase=n['interval_phase'];i=0
while i<len(phase):
    end=i+1
    while end<len(phase) and phase[end]==phase[i]:end+=1
    if phase[i]==1 and end-i>=64:draw_start=i;break
    i=end
assert draw_start is not None
selected=np.r_[np.arange(193),np.arange(draw_start,draw_start+65)]
poses=np.array([fk(joints[i]) for i in selected])
pe=np.linalg.norm(poses[:,:3,3]-positions[selected],axis=1)
ae=np.arccos(np.clip((np.einsum('nij,ij->n',poses[:,:3,:3],rotation)-1)/2,-1,1))
assert pe.max()<=options[0] and ae.max()<=options[1]

def array(name,a):
    a=np.asarray(a);shape=''.join('[%d]'%x for x in a.shape)
    if a.ndim==1:body=', '.join(format(float(x),'.17g') for x in a)
    else:body='\n'+',\n'.join('    {'+', '.join(format(float(x),'.17g') for x in row)+'}' for row in a)+'\n'
    return 'static const double '+name+shape+' = {'+body+'};\n'

sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
text='''#pragma once
// Generated from historical controller_dh and planned-node records.
// This is an OFFLINE regression fixture; it is not a current board measurement
// and it does not establish physical execution. The associated benchmark file
// explicitly records physical_motion=false. Do not substitute URDF parameters.
namespace controller_dh_fixture {
'''
for key,value in [('MACHINE_SOURCE',str(machine_path.relative_to(ROOT)).replace('\\','/')),
 ('MACHINE_SHA256',sha(machine_path)),('NODES_SOURCE',str(nodes_path.relative_to(ROOT)).replace('\\','/')),
 ('NODES_SHA256',sha(nodes_path)),('MODEL_CONVERTER_SHA256',sha(ROOT/'tcb705/model.py')),
 ('READ_FROM',c['kinematics']['read_from'])]:
    text+='static const char '+key+'[] = '+json.dumps(value)+';\n'
text+='static const unsigned PREFIX_COUNT=193, DRAW_START=%d, DRAW_COUNT=65;\n'%draw_start
text+=array('MODEL',model.ravel())+array('TOOL',tool.ravel())+array('OPTIONS',options)+array('ROTATION',rotation.ravel())
text+=array('PREFIX_POSITION',positions[:193])+array('PREFIX_Q',joints[:193])
text+=array('DRAW_POSITION',positions[draw_start:draw_start+65])+array('DRAW_Q',joints[draw_start:draw_start+65])
text+='static const double RECORDED_MAX_POSITION_ERROR_M=%.17g, RECORDED_MAX_ORIENTATION_ERROR_RAD=%.17g;\n'%(pe.max(),ae.max())
text+='}\n'
(OUT/'controller_dh_fixture.hpp').write_text(text,encoding='utf-8')

# Standalone test support avoids changing the existing throughput test/include
# while an RTL co-simulation may be running. It never loads demo vectors.
support=(OUT/'parallel_test_support.hpp').read_text(encoding='utf-8')
begin=support.index('struct Fixture {');end=support.index('\ninline Pose multiply',begin)
ctor='''struct Fixture {
    double model[147], tool[16], options[7], rotation[9], positions[6], expected[14], poses[32];
    Joints seed;
    Fixture() {
        namespace d=controller_dh_fixture;
        for(int i=0;i<147;i++)model[i]=d::MODEL[i];
        for(int i=0;i<16;i++)tool[i]=d::TOOL[i];
        for(int i=0;i<7;i++){options[i]=d::OPTIONS[i];seed[i]=d::PREFIX_Q[0][i];}
        for(int i=0;i<9;i++)rotation[i]=d::ROTATION[i];
        for(int i=0;i<6;i++)positions[i]=d::PREFIX_POSITION[i/3+1][i%3];
        for(int i=0;i<14;i++)expected[i]=d::PREFIX_Q[i/7+1][i%7];
        for(int i=0;i<32;i++)poses[i]=0;
    }
};
'''
support=support[:begin]+ctor+support[end:]
support=support.replace('namespace parallel_test {','namespace controller_test {')
support=support.replace('#pragma once','#pragma once\n// Generated standalone support: no original fixture/test file modified.\n#include "controller_dh_fixture.hpp"',1)
(OUT/'controller_test_support.hpp').write_text(support,encoding='utf-8')
print(json.dumps({'machine_sha256':sha(machine_path),'nodes_sha256':sha(nodes_path),'prefix_count':193,'draw_start':draw_start,
 'draw_count':65,'home_seed_max_rad_difference':float(np.abs(joints[0]-home).max()),
 'selected_recorded_max_position_m':float(pe.max()),'selected_recorded_max_angle_rad':float(ae.max()),
 'physical_motion':False},indent=2))
