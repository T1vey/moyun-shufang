"""Full offline drawing plan: native continuous IK, C2 joint curves and retiming."""
import math
import time
import numpy as np
from .config import validate,digest
from .model import Model,vector,pose_error
from .collision import check as check_collision

PHASE={'APPROACH':0,'DRAW':1,'LIFT':2,'TRAVEL':3,'LOWER':4,'FINISH':5}
class PlanningError(ValueError):pass

def coefficients(q,dt,phases,stops=()):
    """Quintic Hermite with shared derivatives; stops have zero v/a (C2)."""
    stops=set(stops)
    sec=np.diff(q,axis=0)/dt[:,None];vel=np.zeros_like(q)
    for i in range(1,len(q)-1):
        if i in stops or phases[i-1]!=phases[i]:continue
        a,b=sec[i-1],sec[i]
        vel[i]=(dt[i]*a+dt[i-1]*b)/(dt[i-1]+dt[i])
    acc=np.zeros_like(q)
    for i in range(1,len(q)-1):
        if i not in stops and phases[i-1]==phases[i]:acc[i]=2*(sec[i]-sec[i-1])/(dt[i-1]+dt[i])
    a0=q[:-1];a1=vel[:-1]*dt[:,None];a2=.5*acc[:-1]*dt[:,None]**2
    b1=vel[1:]*dt[:,None];b2=acc[1:]*dt[:,None]**2;delta=q[1:]-a0-a1-a2
    vdelta=b1-a1-2*a2;adelta=b2-2*a2
    return np.stack([a0,a1,a2,10*delta-4*vdelta+.5*adelta,-15*delta+7*vdelta-adelta,6*delta-3*vdelta+.5*adelta],axis=1)

def evaluate_coeff(c,u):
    return np.polynomial.polynomial.polyval(u,c).T

def extrema(c,order):
    d=c.copy()
    for _ in range(order):d=d[1:]*np.arange(1,len(d))[:,None]
    maxima=np.zeros(7);mins=np.zeros(7);maxs=np.zeros(7)
    for j in range(7):
        roots=np.polynomial.polynomial.polyroots(d[1:,j]*np.arange(1,len(d))) if len(d)>1 else []
        us=[0.,1.]+[float(r.real) for r in roots if abs(r.imag)<1e-8 and 0<r.real<1]
        val=np.polynomial.polynomial.polyval(us,d[:,j]);maxima[j]=np.max(np.abs(val));mins[j]=np.min(val);maxs[j]=np.max(val)
    return maxima,mins,maxs

def plan(paths,config,q_start=None,cancel=lambda:False,progress=None):
    started=time.perf_counter();validate(config)
    from .calibration import assert_model_ready,map_canvas
    assert_model_ready(config)
    if 'armvision' in config:paths=map_canvas(paths,config)
    model=Model(config);cfg=config['planning'];paper=config['paper']
    q_start=vector(config['q_start_rad'] if q_start is None else q_start,7,'start').copy()
    if not model.legal(q_start):raise PlanningError('START_LIMIT: 起始关节超限')
    origin=vector(paper['origin_m'],3,'origin');x=vector(paper['x_axis'],3,'x');y=vector(paper['y_axis'],3,'y');normal=np.cross(x,y)
    target_r=np.asarray(config['tool_rotation']);q=[q_start];positions=[model.fk(q_start)[:3,3]];phases=[];stroke_ids=[]
    if paths.get('units')!='mm':raise PlanningError('笔画单位必须为 mm')
    if paths.get('coordinate_system','full_canvas_xy_up') not in ('full_canvas_xy_up','full_canvas_xy_down'):raise PlanningError('未知笔画坐标系')
    chains=[]
    for chain in paths.get('paths',[]):
        a=np.asarray(chain,dtype=float)
        if a.ndim!=2 or a.shape[1]!=2 or not np.isfinite(a).all() or len(a)<2:raise PlanningError('笔画必须为有限二维坐标折线')
        if np.any(a<-.001) or np.any(a[:,0]>paper['width_mm']+.001) or np.any(a[:,1]>paper['height_mm']+.001):raise PlanningError('笔画超出标定纸面')
        if paths.get('coordinate_system')=='full_canvas_xy_down':
            height=float(paths['height_mm'])
            if not math.isfinite(height) or not 0<height<=paper['height_mm']:raise PlanningError('画布高度超出标定范围')
            a=a.copy();a[:,1]=height-a[:,1]
            if np.any(a[:,1]<-.001):raise PlanningError('笔画超出画布高度')
        a=a[np.r_[True,np.linalg.norm(np.diff(a,axis=0),axis=1)>1e-8]]
        if len(a)>1:chains.append(a)
    if not chains:raise PlanningError('没有有效笔画')
    if sum(len(a) for a in chains)>cfg['max_nodes']:raise PlanningError('INPUT_BUDGET: 笔画点数过多')
    def world(p):return origin+(x*p[0]+y*p[1])*.001
    def plane_height(point):return origin[2]-(normal[0]*(point[0]-origin[0])+normal[1]*(point[1]-origin[1]))/normal[2]
    start_pose=model.fk(q_start);target_pose=np.eye(4);target_pose[:3,:3]=target_r;target_pose[:3,3]=positions[0]
    if pose_error(target_pose,start_pose)[1]>cfg['orientation_tolerance_rad']:raise PlanningError('START_ORIENTATION: 请先示教笔轴竖直的起始姿态，不能直接跳到第一帧')
    if positions[0][2]<plane_height(positions[0])+cfg['lift_m']-cfg['path_tolerance_m']:raise PlanningError('START_CLEARANCE: 起点必须在纸面上方至少 %.3f mm'%(cfg['lift_m']*1000))
    # Endpoint nearest-neighbour sorting changes order/direction, never connects blank areas.
    ordered=[];cursor=positions[0]
    remaining=list(enumerate(chains))
    while remaining:
        k,rev=min(((k,rev) for k,(_,a) in enumerate(remaining) for rev in (False,True)),key=lambda v:np.linalg.norm(world(remaining[v[0]][1][-1 if v[1] else 0])-cursor))
        index,a=remaining.pop(k);a=a[::-1] if rev else a;ordered.append((index,a));cursor=world(a[-1])
    target_counter=0;iterations=0;stop_nodes={0}
    def checkpoint():
        if cancel():raise PlanningError('CANCELLED: 规划取消')
        if time.perf_counter()-started>cfg['max_plan_seconds']:raise PlanningError('TIME_BUDGET: 规划耗时超过预算')
        if len(q)>cfg['max_nodes']:raise PlanningError('NODE_BUDGET: 轨迹细分节点过多')
    def reach(end,phase,stroke,depth=0):
        nonlocal iterations,target_counter
        checkpoint();begin=positions[-1];goal=np.eye(4);goal[:3,:3]=target_r;goal[:3,3]=end
        result=model.solve(goal,q[-1],q[-1]);iterations+=result['iterations']
        good=result['ok'] and np.max(np.abs(result['q']-q[-1]))<=cfg['max_joint_step_rad']
        if not good:
            if depth>=cfg['max_refinement_depth'] or np.linalg.norm(end-begin)<1e-7:
                raise PlanningError('IK_CONTINUITY: stroke=%d phase=%s point=%s pos_error=%.6g angle=%.6g'%(stroke,phase,end.tolist(),result['position_error_m'],result['orientation_error_rad']))
            midpoint=(begin+end)*.5;reach(midpoint,phase,stroke,depth+1);reach(end,phase,stroke,depth+1);return
        check_collision(model,result['q'])
        q.append(result['q']);positions.append(end.copy());phases.append(PHASE[phase]);stroke_ids.append(stroke)
        target_counter+=1
        if progress and target_counter%100==0:progress('IK',target_counter)
    def line(end,phase,stroke):
        begin=positions[-1].copy();distance=np.linalg.norm(end-begin)
        if distance<1e-9:return
        n=max(1,int(math.ceil(distance/cfg['sample_step_m'])))
        for i in range(1,n+1):reach(begin+(end-begin)*(i/n),phase,stroke)
    for sequence,(index,chain) in enumerate(ordered):
        start=world(chain[0]);up=start+np.array([0,0,cfg['lift_m']])
        # On tilted paper, traverse at a height clearing both endpoints.
        travel_z=max(positions[-1][2],up[2])
        if positions[-1][2]<travel_z:line(positions[-1]+[0,0,travel_z-positions[-1][2]],'LIFT',index)
        line(np.array([up[0],up[1],travel_z]),'TRAVEL',index)
        line(start,'LOWER',index)
        for j,point in enumerate(chain[1:],1):
            line(world(point),'DRAW',index)
            if j<len(chain)-1:
                incoming=chain[j]-chain[j-1];outgoing=chain[j+1]-chain[j]
                cosine=float(incoming@outgoing/(np.linalg.norm(incoming)*np.linalg.norm(outgoing)))
                # Real corners need a smooth stop, not a blanket slowdown of the
                # entire stroke. Dense points on smooth curves remain continuous.
                if cosine<math.cos(math.radians(30)):stop_nodes.add(len(q)-1)
        lift=cfg.get('final_lift_m',cfg['lift_m']) if sequence==len(ordered)-1 else cfg['lift_m']
        line(world(chain[-1])+[0,0,lift],'LIFT',index)
    qs=np.array(q);ps=np.array(positions);ph=np.array(phases,dtype=np.uint32);ids=np.array(stroke_ids,dtype=np.int32)
    if len(qs)<2:raise PlanningError('empty trajectory')
    speed=np.where(ph==PHASE['DRAW'],cfg['draw_speed_m_s'],np.where(ph==PHASE['LOWER'],cfg['lower_speed_m_s'],cfg['air_speed_m_s']))
    dt=np.maximum(np.linalg.norm(np.diff(ps,axis=0),axis=1)/speed,cfg['period_s'])
    # Give a whole phase one smooth start/stop envelope. A 1 mm first segment
    # must not force the complete picture to use its acceleration-limited speed.
    edges=np.unique(np.r_[0,np.flatnonzero(ph[1:]!=ph[:-1])+1,list(stop_nodes),len(ph)]).astype(int)
    lengths=np.linalg.norm(np.diff(ps,axis=0),axis=1)
    for start,end in zip(edges[:-1],edges[1:]):
        cumulative=np.r_[0,np.cumsum(lengths[start:end])];length=cumulative[-1]
        fraction=cumulative/length;lo=np.zeros_like(fraction);hi=np.ones_like(fraction)
        for _ in range(45):
            mid=(lo+hi)*.5;value=mid**3*(10+mid*(-15+6*mid))
            lo=np.where(value<fraction,mid,lo);hi=np.where(value>=fraction,mid,hi)
        normalized=(lo+hi)*.5;normalized[0]=0.;normalized[-1]=1.
        duration=max(1.875*length/float(speed[start]),.12)
        dt[start:end]=np.maximum(np.diff(normalized)*duration,cfg['period_s'])
    limits=config['limits'];v=np.array(limits['velocity_rad_s']);a=np.array(limits['acceleration_rad_s2']);jerk=np.array(limits['jerk_rad_s3'])
    dt=np.maximum(dt,np.max(np.abs(np.diff(qs,axis=0))/v,axis=1))
    # Retiming each stop-to-stop block preserves shared C2 derivatives.
    coeff=coefficients(qs,dt,ph,stop_nodes);factors=np.ones(len(dt));peaks=np.zeros((len(dt),3,7))
    for i,c in enumerate(coeff):
        checkpoint()
        _,low,high=extrema(c,0)
        if np.any(low<model.lower-1e-10) or np.any(high>model.upper+1e-10):raise PlanningError('CURVE_LIMIT: 多项式区间越过关节限位')
        for order,limit in [(1,v),(2,a),(3,jerk)]:
            peak=extrema(c,order)[0]/dt[i]**order
            peaks[i,order-1]=peak
            factors[i]=max(factors[i],float(np.max(peak/limit))**(1/order))
    # Independent phase scaling is valid because both endpoint derivatives are zero.
    for start,end in zip(edges[:-1],edges[1:]):
        stretch=max(factors[start:end])*1.005;dt[start:end]*=stretch
        for order in range(1,4):peaks[start:end,order-1]/=stretch**order
    factor=float(max(factors));coeff=coefficients(qs,dt,ph,stop_nodes);times=np.r_[0,np.cumsum(dt)]
    if times[-1]>cfg['max_duration_s']:raise PlanningError('DURATION_BUDGET: 计划时间过长')
    metrics={'ik_iterations':iterations,'time_stretch':factor,'nodes':len(qs),'duration_s':float(times[-1]),'corner_stops':len(stop_nodes)-1,'max_path_error_m':0.,'max_orientation_error_rad':0.,'max_joint_step_rad':float(np.max(np.abs(np.diff(qs,axis=0))))}
    metrics.update(joint_peak_velocity_rad_s=peaks[:,0].max(axis=0).tolist(),
                   joint_peak_acceleration_rad_s2=peaks[:,1].max(axis=0).tolist(),
                   joint_peak_jerk_rad_s3=peaks[:,2].max(axis=0).tolist())
    # Verify curved joint intervals before time sampling; reject instead of hiding distortion.
    for i,c in enumerate(coeff):
        checkpoint();n=max(8,int(np.ceil(np.max(np.abs(qs[i+1]-qs[i]))/cfg['verify_step_rad'])))
        us=np.linspace(0,1,n+1);qq=evaluate_coeff(c,us);poses=model.fk_batch(qq)
        begin,end=ps[i],ps[i+1];delta=end-begin;denom=delta@delta
        frac=np.clip((poses[:,:3,3]-begin)@delta/max(denom,1e-30),0,1)
        nearest=begin+frac[:,None]*delta
        dist=np.linalg.norm(poses[:,:3,3]-nearest,axis=1)
        angles=np.arccos(np.clip((np.einsum('nij,ij->n',poses[:,:3,:3],target_r)-1)/2,-1,1))
        metrics['max_path_error_m']=max(metrics['max_path_error_m'],float(max(dist)))
        metrics['max_orientation_error_rad']=max(metrics['max_orientation_error_rad'],float(max(angles)))
        if max(dist)>cfg['path_tolerance_m'] or max(angles)>cfg['orientation_tolerance_rad']:
            raise PlanningError('CURVE_GEOMETRY: interval=%d path=%.6g angle=%.6g; reduce sample_step_m'%(i,max(dist),max(angles)))
        if ph[i] in (PHASE['LIFT'],PHASE['LOWER']) and np.any(np.diff(poses[:,2,3])*(1 if ph[i]==PHASE['LIFT'] else -1)<-cfg['path_tolerance_m']):raise PlanningError('LIFT_NON_MONOTONIC')
        for row in qq:check_collision(model,row)
    count=int(math.ceil(times[-1]/cfg['period_s']))+1
    if count>cfg.get('max_frames',150000):raise PlanningError('FRAME_BUDGET: 采样帧数超过 ZYNQ 内存预算，减少图形复杂度后重试')
    ticks=np.arange(count,dtype=float)*cfg['period_s'];ticks[-1]=times[-1]
    seg=np.minimum(np.searchsorted(times,ticks,side='right')-1,len(dt)-1);u=(ticks-times[seg])/dt[seg]
    samples=np.zeros((count,7))
    for power in range(5,-1,-1):samples=samples*u[:,None]+coeff[seg,power,:]
    # Freeze the actual SDK float32 rounding into the model-space samples.
    sdk=((samples[:,model.order]-model.offset)*model.sign*180/math.pi).astype(np.float32)
    rounded=np.empty_like(samples);rounded[:,model.order]=sdk.astype(float)*math.pi/180*model.sign+model.offset
    poses=model.fk_batch(rounded);checkpoint()
    begin,end=ps[seg],ps[seg+1];delta=end-begin
    frac=np.clip(np.einsum('ij,ij->i',poses[:,:3,3]-begin,delta)/np.maximum(np.einsum('ij,ij->i',delta,delta),1e-30),0,1)
    distances=np.linalg.norm(poses[:,:3,3]-(begin+frac[:,None]*delta),axis=1)
    angles=np.arccos(np.clip((np.einsum('nij,ij->n',poses[:,:3,:3],target_r)-1)/2,-1,1))
    if max(distances)>cfg['path_tolerance_m'] or max(angles)>cfg['orientation_tolerance_rad']:raise PlanningError('FINAL_SAMPLE_GEOMETRY: float32 发送轨迹超差')
    if np.any(rounded<model.lower) or np.any(rounded>model.upper):raise PlanningError('FINAL_SAMPLE_LIMIT')
    metrics.update(max_path_error_m=max(metrics['max_path_error_m'],float(max(distances))),max_orientation_error_rad=max(metrics['max_orientation_error_rad'],float(max(angles))),planning_s=time.perf_counter()-started,frames=count,ik_backend='ZYNQ_CPU_NATIVE_7R',motion_algorithm_version='tcb705-c2-v1',motion_mode='tcb705',collision_model_verified=config['collision_model_verified'])
    preview=[]
    for sid in sorted(set(ids)):
        mask=(ph[seg]==PHASE['DRAW'])&(ids[seg]==sid);xy=(poses[mask,:3,3]-origin)@np.stack([x,y],axis=1)*1000
        if len(xy)>1:preview.append(xy.tolist())
    return dict(schema='tcb705-plan-v1',config_digest=digest(config),model_sha256=model.model_sha256,
        config=config,q_start_rad=q_start.tolist(),metrics=metrics,period_s=cfg['period_s'],
        preview=dict(width_mm=paper['width_mm'],height_mm=paper['height_mm'],paths=preview),
        times=ticks,q_rad=rounded,sdk_degrees=sdk,phase=ph[seg],stroke_ids=ids[seg],
        interval_times=times,coefficients=coeff,geometric_positions=ps,interval_phase=ph)
