import copy
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from .model import ROOT,vector,transform

def digest(config):
    # Web-program execution settings (mode, speed %, chunking) do not change the
    # planned geometry, so they are not part of the frozen-plan identity.
    # The SDK motion settings (server, queue depth) likewise do not change the geometry.
    if any(k in config.get('execution',{}) for k in ('web_program','sdk')):
        config=copy.deepcopy(config)
        for k in ('web_program','sdk'):config['execution'].pop(k,None)
    return hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def load(path=None):
    p=Path(path) if path else ROOT/'robots/tcb705/profile.armvision.json'
    c=json.loads(p.read_text(encoding='utf-8'));validate(c);return c

def validate(c):
    try:return _validate(c)
    except (KeyError,TypeError,IndexError,OverflowError) as exc:
        raise ValueError('天链配置缺少字段或格式错误: '+str(exc)) from exc

def _validate(c):
    if c.get('schema')!='tcb705-machine-v1' or c.get('robot_type')!='TCB705':raise ValueError('需要 tcb705-machine-v1 配置')
    if type(c['robot_id']) is not int or not 1<=c['robot_id']<=32:raise ValueError('invalid robot_id')
    controller=c['controller']
    for key in ('local_ip','remote_ip'):
        value=controller.get(key,'')
        if not isinstance(value,str):raise ValueError('controller.'+key+' must be text')
        if value:
            import ipaddress
            try:ipaddress.IPv4Address(value)
            except ipaddress.AddressValueError:raise ValueError('invalid controller.'+key)
    for key,default in (('port',8001),('web_port',8010)):
        value=controller.get(key,default)
        if type(value) is not int or not 1<=value<=65535:raise ValueError('invalid controller.'+key)
    if controller.get('local_ip') and controller.get('remote_ip'):
        from .ethernet import endpoint
        endpoint(controller)
    transform(c['T_flange_tcp']);vector(c['q_start_rad'],7,'q_start_rad')
    if 'T_controller_base_from_model' in c:transform(c['T_controller_base_from_model'])
    r=np.eye(4);r[:3,:3]=c['tool_rotation'];transform(r,'tool rotation')
    if np.linalg.norm(r[:3,2]-[0,0,-1])>1e-6:raise ValueError('笔轴必须保持世界竖直向下')
    paper=c['paper'];vector(paper['origin_m'],3,'paper origin')
    x,y=vector(paper['x_axis'],3,'paper x'),vector(paper['y_axis'],3,'paper y')
    if abs(np.linalg.norm(x)-1)>1e-6 or abs(np.linalg.norm(y)-1)>1e-6 or abs(x@y)>1e-6:raise ValueError('paper axes must be orthonormal')
    if np.cross(x,y)[2]<.9:raise ValueError('paper tilt must be less than 25 degrees and normal upward')
    for name in ('width_mm','height_mm'):
        if not .1<=float(paper[name])<=300:raise ValueError('paper size must be 0.1..300 mm')
    limits=c['limits']
    for key in ('velocity_rad_s','acceleration_rad_s2','jerk_rad_s3'):
        if np.any(vector(limits[key],7,key)<=0):raise ValueError('dynamic limits must be positive')
    bounds={'lift_m':(.0001,.3) if 'armvision' in c else (.03,.03),'sample_step_m':(.0001,.005),'max_joint_step_rad':(.001,.3),
        'max_refinement_depth':(0,16),'max_nodes':(2,150000),'max_plan_seconds':(1,3600),
        'draw_speed_m_s':(.0001,.2),'air_speed_m_s':(.0001,.5),'lower_speed_m_s':(.0001,.05),
        'period_s':(.002,.004),'path_tolerance_m':(.000001,.0005),
        'orientation_tolerance_rad':(.00001,.01),'max_duration_s':(1,7200),'verify_step_rad':(.0005,.02)}
    for key,(lo,hi) in bounds.items():
        val=c['planning'][key]
        if type(val) not in (int,float) or not math.isfinite(val) or not lo-1e-12<=val<=hi+1e-12:raise ValueError('invalid planning.'+key)
    for key in ('max_refinement_depth','max_nodes'):
        if type(c['planning'][key]) is not int:raise ValueError(key+' must be integer')
    if c['planning'].get('canvas_fit','stretch') not in ('stretch','contain'):raise ValueError('planning.canvas_fit 必须为 stretch 或 contain')
    final_lift=c['planning'].get('final_lift_m',c['planning']['lift_m'])
    if type(final_lift) not in (int,float) or not math.isfinite(final_lift) or not .0001<=final_lift<=.3:raise ValueError('invalid planning.final_lift_m')
    if 'armvision' in c:
        from .calibration import check_consistency
        check_consistency(c)
    for key in ('position_tolerance_m','orientation_tolerance_rad','max_iterations','step_limit_rad','damping','reference_weight'):
        val=c['ik'][key]
        if type(val) not in (int,float) or not math.isfinite(val) or val<=0:raise ValueError('invalid ik.'+key)
    if c['ik']['max_iterations']>1000:raise ValueError('IK iteration budget too high')
    if type(c['ik']['max_iterations']) is not int:raise ValueError('IK iterations must be integer')
    frames=c['planning'].get('max_frames',150000)
    if type(frames) is not int or not 2<=frames<=800000:raise ValueError('max_frames must be 2..800000 for ZYNQ memory budget (~0.53 KB/frame peak while planning)')
    for key in ('calibration_verified','dynamics_verified','sdk_mapping_verified','collision_model_verified'):
        if type(c[key]) is not bool:raise ValueError(key+' must be boolean')
    if type(c['collision']['self_check']) is not bool:raise ValueError('self_check must be boolean')
    if 'web_program' in c['execution']:
        from .web_executor import settings
        settings(c)
    if 'sdk' in c['execution']:
        from .sdk_motion import sdk_settings
        sdk_settings(c)
    if 'calligraphy' in c:
        from calligraphy.presets import profile
        profile(c)
    if c.get('mounted_tool','pen') not in ('pen','brush','hardpen'):raise ValueError('mounted_tool 只能是 pen、brush 或 hardpen')
    if 'hardpen' in c:
        from calligraphy.hardpen import profile as hardpen_profile
        hardpen_profile(c)
    if not .001<=float(c['collision']['link_radius_m'])<=.1:raise ValueError('invalid collision radius')
    for box in c['collision']['boxes']:
        a,b=vector(box['min_m'],3,'box minimum'),vector(box['max_m'],3,'box maximum')
        if np.any(a>=b):raise ValueError('invalid obstacle box')
    return c

def readiness(c):
    required=('calibration_verified','dynamics_verified','sdk_mapping_verified','collision_model_verified')
    missing=[k for k in required if c.get(k) is not True]
    web=c['execution'].get('web_program',{}).get('enabled') is True
    if web:
        # Auto-mode whole-program path (hmcLine / hmcRobotFree), verified on the real arm.
        from .web_executor import mapping_required
        need=('calibration_verified','sdk_mapping_verified') if mapping_required(c) else ('calibration_verified',)
        missing=[k for k in need if c.get(k) is not True]
        path=('sdk_' if c['execution'].get('sdk',{}).get('enabled') is True else 'web_program_')+c['execution']['web_program'].get('mode','cartesian')
        return dict(physical_ready=not missing,missing=missing,offline_ready=True,execution_path=path)
    if c['execution'].get('transport_contract_verified') is not True:missing.append('transport_contract_verified')
    # Joint streaming (PluseToServo) is still not implemented; only web_program executes.
    missing.append('hardware_streaming_commissioning_not_implemented')
    return dict(physical_ready=False,missing=missing,offline_ready=True)

def demo_config():
    c=load(ROOT/'robots/tcb705/profile.example.json');c['paper']['origin_m']=[.35,-.05,.17]
    c['q_start_rad']=[2.6754729563645343,-.9343866425848552,1.2514604900741522,-2.538996623955584,2.262752345959223,.12919323076792782,.4427284270886426]
    c['collision']['self_check']=False
    c['note']='OFFLINE DEMONSTRATION: no physical calibration, no physical motion. Collision model not commissioned.'
    return c
