"""ArmVision A/B range + landing Z/UVW, in controller mm/degrees.

Matches widget.cpp's range sorting and main.py's swap_xy transform.
It does not infer TCP, robot zeroes or the controller-to-model frame mapping.
"""
import copy
import math
import numpy as np
from .model import vector

METHOD = 'armvision-ab-z-uvw-v1'

def fields(value):
    try:return _fields(value)
    except (KeyError,TypeError,IndexError,OverflowError) as exc:raise ValueError('ArmVision 标定字段缺失或格式错误: '+str(exc)) from exc

def _fields(value):
    a=copy.deepcopy(value)
    if a.get('method')!=METHOD:raise ValueError('需要 ArmVision A/B 标定')
    for key,n in (('a_mm',2),('b_mm',2),('pose_uvw_deg',3)):
        a[key]=vector(a[key],n,key).tolist()
    for key in ('z_table_mm','lift_mm','final_lift_mm','draw_speed_percent'):
        if type(a[key]) not in (int,float) or not math.isfinite(a[key]):raise ValueError('无效标定参数 '+key)
    if not 0<a['lift_mm']<=300 or not 0<a['final_lift_mm']<=300:raise ValueError('抬笔高度必须为 0..300 mm（不含 0）')
    if not 0<a['draw_speed_percent']<=100:raise ValueError('绘制速度是 0..100 的程序速度百分比（不含 0）')
    if type(a['robot_id']) is not int or not 1<=a['robot_id']<=32:raise ValueError('无效机器人 ID')
    if type(a['swap_xy']) is not bool:raise ValueError('swap_xy 必须为布尔值')
    for k in ('tool','coord','extool'):
        if type(a[k]) is not int or a[k]<0:raise ValueError('无效坐标/工具编号 '+k)
    x0,x1=sorted((a['a_mm'][0],a['b_mm'][0]));y0,y1=sorted((a['a_mm'][1],a['b_mm'][1]))
    if not .1<=x1-x0<=300 or not .1<=y1-y0<=300:raise ValueError('A/B 两点的 X、Y 跨度必须为 0.1..300 mm')
    a['table']={'x_min':x0,'x_max':x1,'y_min':y0,'y_max':y1,'z_table':a['z_table_mm']}
    width,height=(y1-y0,x1-x0) if a['swap_xy'] else (x1-x0,y1-y0)
    a['image']={'target_width_mm':round(width,1),'target_height_mm':round(height,1)}
    return a

def paper_frame(value):
    a=fields(value);return _frame(a['table'],a['swap_xy'])

def _frame(t,swap_xy):
    if swap_xy:
        return dict(origin_m=[t['x_max']/1000,t['y_min']/1000,t['z_table']/1000],
                    x_axis=[0,1,0],y_axis=[-1,0,0],width_mm=t['y_max']-t['y_min'],height_mm=t['x_max']-t['x_min'])
    return dict(origin_m=[t['x_min']/1000,t['y_min']/1000,t['z_table']/1000],
                x_axis=[1,0,0],y_axis=[0,1,0],width_mm=t['x_max']-t['x_min'],height_mm=t['y_max']-t['y_min'])

# 春联台面: own A/B corners, same landing Z, pen pose and axis convention as the
# main calibration, so it lies in the same plane; only its extent may exceed 300 mm.
COUPLET_SPAN_MM=(100.,650.)

def couplet_frame(armvision,table):
    a=fields(armvision)
    try:A,B=vector(table['a_mm'],2,'春联台面 A'),vector(table['b_mm'],2,'春联台面 B')
    except (KeyError,TypeError) as exc:raise ValueError('春联台面需要 A、B 两点坐标') from exc
    x0,x1=sorted((float(A[0]),float(B[0])));y0,y1=sorted((float(A[1]),float(B[1])))
    lo,hi=COUPLET_SPAN_MM
    if not lo<=x1-x0<=hi or not lo<=y1-y0<=hi:raise ValueError('春联台面 A/B 两点的 X、Y 跨度必须为 %g..%g mm'%(lo,hi))
    return _frame({'x_min':x0,'x_max':x1,'y_min':y0,'y_max':y1,'z_table':a['z_table_mm']},a['swap_xy'])

def check_couplet_reach(config,model,inset_mm=10.,step_mm=10.):
    """Pen-vertical IK must reach every inset corner of the couplet table along
    continuous straight lines from its centre. Offline only, never moves."""
    p=config['couplet_paper'];o=np.asarray(p['origin_m']);x=np.asarray(p['x_axis']);y=np.asarray(p['y_axis'])
    W,H=p['width_mm'],p['height_mm'];R=np.asarray(config['tool_rotation']);limit=config['planning']['max_joint_step_rad']
    def at(u,v):
        g=np.eye(4);g[:3,:3]=R;g[:3,3]=o+(x*u+y*v)*.001;return g
    def solve(u,v,seed):
        r=model.solve(at(u,v),seed,seed)
        return r['q'] if r['ok'] and model.legal(r['q']) and np.max(np.abs(r['q']-seed))<=limit*4 else None
    seed=np.asarray(config['q_start_rad'],dtype=float);centre=None
    for k in range(4):   # q_start may be far above the table: approach the centre in a few hops
        centre=model.solve(at(W/2,H/2),seed,seed)
        if centre['ok'] and model.legal(centre['q']):break
        seed=centre['q']
    if not centre['ok'] or not model.legal(centre['q']):raise ValueError('春联台面中心机械臂够不到，请把台面移近底座')
    for u,v in ((inset_mm,inset_mm),(W-inset_mm,inset_mm),(inset_mm,H-inset_mm),(W-inset_mm,H-inset_mm)):
        q=centre['q'];n=max(1,int(np.ceil(np.hypot(u-W/2,v-H/2)/step_mm)))
        for i in range(1,n+1):
            q=solve(W/2+(u-W/2)*i/n,H/2+(v-H/2)*i/n,q)
            if q is None:raise ValueError('春联台面角点（%.0f, %.0f mm）机械臂够不到，请把台面往底座方向挪'%(u,v))

def apply_armvision(config,value,reset_verified=True):
    c=copy.deepcopy(config);a=fields(value)
    c['armvision']=a;c['paper']=paper_frame(a);c['robot_id']=a['robot_id']
    if c.get('couplet_table'):c['couplet_paper']=couplet_frame(a,c['couplet_table'])
    else:c.pop('couplet_table',None);c.pop('couplet_paper',None)
    c['planning']['lift_m']=a['lift_mm']/1000
    c['planning']['final_lift_m']=a['final_lift_mm']/1000
    # 100 is a controller program percentage, not 100 mm/s.
    # Local IK velocities retain separate physical limits.
    if reset_verified:c['calibration_verified']=False
    c.pop('paper_measurements',None)
    return c

def check_consistency(config):
    a=fields(config['armvision']);expected=paper_frame(a)
    for k,v in expected.items():
        if not np.allclose(config['paper'][k],v,atol=1e-10,rtol=0):raise ValueError('ArmVision 标定与派生纸面不一致，请重新保存标定')
    if config['robot_id']!=a['robot_id']:raise ValueError('ArmVision 机器人 ID 不一致')
    if config.get('couplet_table'):
        expected=couplet_frame(a,config['couplet_table'])
        for k,v in expected.items():
            if not np.allclose(config.get('couplet_paper',{}).get(k,np.nan),v,atol=1e-10,rtol=0):raise ValueError('春联台面与派生坐标不一致，请重新保存春联台面')
    elif 'couplet_paper' in config:raise ValueError('春联台面缺少 A/B 标定记录')
    for key,source in (('lift_m','lift_mm'),('final_lift_m','final_lift_mm')):
        if abs(config['planning'][key]-a[source]/1000)>1e-12:raise ValueError('ArmVision 抬笔高度不一致')

def capture(value,slot,world_mm_deg):
    """Controller feedback only, never FK of an unverified example TCP."""
    a=copy.deepcopy(value);p=vector(world_mm_deg,6,'控制器 XYZUVW')
    if slot in ('a','b'):a[slot+'_mm']=[round(float(v),3) for v in p[:2]]
    elif slot=='landing':
        a['z_table_mm']=round(float(p[2]),3);a['pose_uvw_deg']=[round(float(v),3) for v in p[3:]]
    else:raise ValueError('采集位置必须为 a、b 或 landing')
    return a

def map_canvas(paths,config):
    """swap_xy: X=x_max-y/h*X_span, Y=y_min+x/w*Y_span (Y-up).

    The planner's paper axes implement this transform. Normalize the incoming
    whole canvas, never its cropped stroke bounding box.
    """
    from stroke_paths import resize_paths
    W,H=config['paper']['width_mm'],config['paper']['height_mm']
    fit=config['planning'].get('canvas_fit','stretch')
    if fit=='stretch':  # original ArmVision behaviour: independent X/Y scale (distorts aspect)
        return resize_paths(paths,W,H)
    # 'contain': one uniform scale so the drawing keeps its proportions, centred on the paper
    w,h=float(paths['width_mm']),float(paths['height_mm']);s=min(W/w,H/h)
    out=resize_paths(paths,w*s,h*s);dx,dy=(W-w*s)/2,(H-h*s)/2
    out['paths']=[[[x+dx,y+dy] for x,y in chain] for chain in out['paths']]
    out['width_mm'],out['height_mm']=W,H
    out['drawing_resize'].update(fit='contain',scale=s,offset_mm=[dx,dy])
    from stroke_paths import path_digest
    out['path_sha256']=path_digest(out)
    return out

def assert_model_ready(config):
    if 'armvision' not in config:return
    web=config.get('execution',{}).get('web_program',{})
    planning_only=web.get('enabled') is True and web.get('mode','cartesian')=='cartesian' and web.get('ik_role','planning_only')=='planning_only'
    if not config['calibration_verified'] or (not config['sdk_mapping_verified'] and not planning_only):
        raise ValueError('ArmVision 标定已导入；本地七轴 IK 仍需核对控制器坐标、TCP 和关节映射。离线算法演示请使用 profile.demo.json。')
    a=config['armvision']
    if any(a[k]!=0 for k in ('tool','coord','extool')):
        raise ValueError('已保存原控制器工具/坐标编号；当前本地 IK 尚未适配，不能套用默认转换')
    u,v,w=a['pose_uvw_deg']
    # Pen vertical (U=180, V=0); the roll W about the pen axis is free (web path keeps
    # the controller's current roll, e.g. W=180), but tool_rotation must match it exactly.
    if not (abs(abs(u)-180)<1e-9 and abs(v)<1e-9):
        raise ValueError('ArmVision UVW 必须为笔轴竖直（U=180, V=0）')
    from .model import rpy_matrix
    if not np.allclose(config['tool_rotation'],rpy_matrix(np.radians(a['pose_uvw_deg'])),atol=1e-9,rtol=0):
        raise ValueError('本地工具姿态与导入的 ArmVision UVW 不一致')
