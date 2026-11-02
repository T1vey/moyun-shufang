"""Full offline drawing plan: native continuous IK, C2 joint curves and retiming."""
import math
import time
import numpy as np
from .config import validate,digest
from .model import Model,vector,pose_error
from .collision import check as check_collision,check_batch as check_collision_batch

PHASE={'APPROACH':0,'DRAW':1,'LIFT':2,'TRAVEL':3,'LOWER':4,'FINISH':5}
class PlanningError(ValueError):pass

def coefficients(q,dt,phases,stops=()):
    """Quintic Hermite with shared derivatives; stops have zero v/a (C2)."""
    sec=np.diff(q,axis=0)/dt[:,None];vel=np.zeros_like(q);acc=np.zeros_like(q)
    # All interior knots at once (same per-element formulas as the scalar loop).
    i=np.arange(1,len(q)-1);phases=np.asarray(phases)
    keep=phases[i-1]==phases[i]
    if len(stops):keep&=~np.isin(i,np.fromiter(stops,dtype=int))
    i=i[keep];span=(dt[i-1]+dt[i])[:,None]
    vel[i]=(dt[i,None]*sec[i-1]+dt[i-1,None]*sec[i])/span
    acc[i]=2*(sec[i]-sec[i-1])/span
    a0=q[:-1];a1=vel[:-1]*dt[:,None];a2=.5*acc[:-1]*dt[:,None]**2
    b1=vel[1:]*dt[:,None];b2=acc[1:]*dt[:,None]**2;delta=q[1:]-a0-a1-a2
    vdelta=b1-a1-2*a2;adelta=b2-2*a2
    return np.stack([a0,a1,a2,10*delta-4*vdelta+.5*adelta,-15*delta+7*vdelta-adelta,6*delta-3*vdelta+.5*adelta],axis=1)

def evaluate_coeff(c,u):
    return np.polynomial.polynomial.polyval(u,c).T

def evaluate_rows(c,u):
    """evaluate_coeff for many intervals: c (m,6,7) gathered per sample, u (m,).
    Same Horner order as numpy polyval, so every value is bit-identical."""
    u=u[:,None];s=c[:,5]+u*0
    for power in range(4,-1,-1):s=c[:,power]+s*u
    return s

def extrema(c,order):
    d=c.copy()
    for _ in range(order):d=d[1:]*np.arange(1,len(d))[:,None]
    maxima=np.zeros(7);mins=np.zeros(7);maxs=np.zeros(7)
    for j in range(7):
        roots=np.polynomial.polynomial.polyroots(d[1:,j]*np.arange(1,len(d))) if len(d)>1 else []
        us=[0.,1.]+[float(r.real) for r in roots if abs(r.imag)<1e-8 and 0<r.real<1]
        val=np.polynomial.polynomial.polyval(us,d[:,j]);maxima[j]=np.max(np.abs(val));mins[j]=np.min(val);maxs[j]=np.max(val)
    return maxima,mins,maxs

def plan(paths,config,q_start=None,cancel=lambda:False,progress=None,accelerator=None):
    from .accel_runtime import open_accelerator
    owned=False;reason=None
    if accelerator is None:
        accelerator,reason=open_accelerator();owned=accelerator is not None
    try:
        result=_plan(paths,config,q_start,cancel,progress,accelerator)
        if reason:result['metrics']['ik_accel_unavailable_reason']=reason
        return result
    finally:
        if owned:accelerator.close()

def _plan(paths,config,q_start=None,cancel=lambda:False,progress=None,accelerator=None,*,_geometry_only=False,_model=None,_hover_finish=False):
    started=time.perf_counter();validate(config)
    from .calibration import assert_model_ready,map_canvas
    assert_model_ready(config)
    brush=paths.get('calligraphy')
    if brush:
        from calligraphy.presets import validate_task
        validate_task(paths,config)
    elif 'armvision' in config:paths=map_canvas(paths,config)
    model=_model or Model(config);cfg=config['planning'];paper=config['paper']
    if brush:
        from calligraphy.couplets import surface
        paper=surface(config,brush)   # 春联 is written on its own calibrated table
    q_start=vector(config['q_start_rad'] if q_start is None else q_start,7,'start').copy()
    if not model.legal(q_start):raise PlanningError('START_LIMIT: 起始关节超限')
    origin=vector(paper['origin_m'],3,'origin');x=vector(paper['x_axis'],3,'x');y=vector(paper['y_axis'],3,'y');normal=np.cross(x,y)
    target_r=np.asarray(config['tool_rotation']);q=[q_start];positions=[model.fk(q_start)[:3,3]];phases=[];stroke_ids=[]
    if paths.get('units')!='mm':raise PlanningError('笔画单位必须为 mm')
    if paths.get('coordinate_system','full_canvas_xy_up') not in ('full_canvas_xy_up','full_canvas_xy_down'):raise PlanningError('未知笔画坐标系')
    chains=[]
    for chain_index,chain in enumerate(paths.get('paths',[])):
        a=np.asarray(chain,dtype=float)
        if a.ndim!=2 or a.shape[1]!=2 or not np.isfinite(a).all() or len(a)<2:raise PlanningError('笔画必须为有限二维坐标折线')
        if np.any(a<-.001) or np.any(a[:,0]>paper['width_mm']+.001) or np.any(a[:,1]>paper['height_mm']+.001):raise PlanningError('笔画超出标定纸面')
        if paths.get('coordinate_system')=='full_canvas_xy_down':
            height=float(paths['height_mm'])
            if not math.isfinite(height) or not 0<height<=paper['height_mm']:raise PlanningError('画布高度超出标定范围')
            a=a.copy();a[:,1]=height-a[:,1]
            if np.any(a[:,1]<-.001):raise PlanningError('笔画超出画布高度')
        if brush:
            a=np.column_stack([a,brush['depth_mm'][chain_index],brush['feed_ratio'][chain_index]])
            # Same XY with changing pressure is a real, vertical motion.
            a=a[np.r_[True,np.linalg.norm(np.diff(a[:,:3],axis=0),axis=1)>1e-8]]
        else:
            a=a[np.r_[True,np.linalg.norm(np.diff(a,axis=0),axis=1)>1e-8]]
        if len(a)>1:chains.append(a)
    if not chains:raise PlanningError('没有有效笔画')
    if sum(len(a) for a in chains)>cfg['max_nodes']:raise PlanningError('INPUT_BUDGET: 笔画点数过多')
    def world(p):return origin+(x*p[0]+y*p[1]-normal*(p[2] if brush and len(p)>2 else 0))*.001
    def plane_height(point):return origin[2]-(normal[0]*(point[0]-origin[0])+normal[1]*(point[1]-origin[1]))/normal[2]
    start_pose=model.fk(q_start);target_pose=np.eye(4);target_pose[:3,:3]=target_r;target_pose[:3,3]=positions[0]
    if pose_error(target_pose,start_pose)[1]>cfg['orientation_tolerance_rad']:raise PlanningError('START_ORIENTATION: 请先示教笔轴竖直的起始姿态，不能直接跳到第一帧')
    if positions[0][2]<plane_height(positions[0])+cfg['lift_m']-cfg['path_tolerance_m']:raise PlanningError('START_CLEARANCE: 起点必须在纸面上方至少 %.3f mm'%(cfg['lift_m']*1000))
    # Endpoint nearest-neighbour sorting changes order/direction, never connects blank areas.
    ordered=[];cursor=positions[0]
    remaining=[] if brush else list(enumerate(chains))
    if brush:ordered=list(enumerate(chains))
    # (k, start/end) endpoints in the same order as the former min() generator;
    # argmin keeps its first-minimum tie rule.
    ends=np.array([[a[0],a[-1]] for a in chains],dtype=float)
    ends=origin+(x*ends[...,0,None]+y*ends[...,1,None])*.001
    while remaining:
        best=int(np.argmin(np.linalg.norm(ends.reshape(-1,3)-cursor,axis=1)));k,rev=best//2,bool(best%2)
        index,a=remaining.pop(k);ends=np.delete(ends,k,axis=0)
        a=a[::-1] if rev else a;ordered.append((index,a));cursor=world(a[-1])
    from .planning_batches import ChainDispatcher
    dispatcher=ChainDispatcher(model,accelerator,cancel)
    target_counter=0;iterations=0;stop_nodes={0};schedule=[];planned_positions=[positions[0]];feed_ratios=[]
    def checkpoint():
        if cancel():raise PlanningError('CANCELLED: 规划取消')
        if time.perf_counter()-started>cfg['max_plan_seconds']:raise PlanningError('TIME_BUDGET: 规划耗时超过预算')
        if len(q)>cfg['max_nodes']:raise PlanningError('NODE_BUDGET: 轨迹细分节点过多')
    def reach(end,phase,stroke,depth=0,proposed=None,feed=1.):
        nonlocal iterations,target_counter
        checkpoint();begin=positions[-1]
        if proposed is None:
            goal=np.eye(4);goal[:3,:3]=target_r;goal[:3,3]=end;proposed=model.solve(goal,q[-1],q[-1])
        result=proposed;iterations+=result['iterations']
        good=result['ok'] and np.max(np.abs(result['q']-q[-1]))<=cfg['max_joint_step_rad']
        if not good:
            dispatcher.invalidate()
            if depth>=cfg['max_refinement_depth'] or np.linalg.norm(end-begin)<1e-7:
                raise PlanningError('IK_CONTINUITY: stroke=%d phase=%s point=%s pos_error=%s angle=%s'%(stroke,phase,end.tolist(),result['position_error_m'],result['orientation_error_rad']))
            midpoint=(begin+end)*.5;reach(midpoint,phase,stroke,depth+1,feed=feed);reach(end,phase,stroke,depth+1,feed=feed);return
        # collision of every node is checked once, vectorised, after the IK chain (same verdict)
        q.append(result['q']);positions.append(end.copy());phases.append(PHASE[phase]);stroke_ids.append(stroke)
        feed_ratios.append(feed)
        target_counter+=1
        if progress and target_counter%100==0:progress('IK',target_counter)
    def line(end,phase,stroke,feed=1.):
        begin=planned_positions[-1].copy();distance=np.linalg.norm(end-begin)
        if distance<1e-9:return
        step=min(cfg['sample_step_m'],.0004) if brush and phase=='DRAW' else cfg['sample_step_m']
        n=max(1,int(math.ceil(distance/step)))
        if len(schedule)+n>cfg['max_nodes']:raise PlanningError('NODE_BUDGET: 轨迹细分节点过多')
        points=begin+(end-begin)*(np.arange(1,n+1)/n)[:,None]
        schedule.extend([point,phase,stroke,False,feed] for point in points);planned_positions.extend(points)
    for sequence,(index,chain) in enumerate(ordered):
        start=world(chain[0]);up=world(chain[0][:2])+np.array([0,0,cfg['lift_m']])
        # On tilted paper, traverse at a height clearing both endpoints.
        travel_z=max(planned_positions[-1][2],up[2])
        if planned_positions[-1][2]<travel_z:line(planned_positions[-1]+[0,0,travel_z-planned_positions[-1][2]],'LIFT',index)
        line(np.array([up[0],up[1],travel_z]),'TRAVEL',index)
        line(start,'LOWER',index,feed=.3 if brush else 1.)
        # Real corners need a smooth stop, not a blanket slowdown of the
        # entire stroke. Dense points on smooth curves remain continuous.
        step=np.diff(chain[:,:3] if brush else chain,axis=0);incoming,outgoing=step[:-1],step[1:]
        cosine=np.einsum('ij,ij->i',incoming,outgoing)/np.maximum(1e-20,(np.sqrt(np.einsum('ij,ij->i',incoming,incoming))*np.sqrt(np.einsum('ij,ij->i',outgoing,outgoing))))
        corner=(cosine<math.cos(math.radians(30))).tolist()+[False]
        for point,stop in zip(chain[1:],corner):
            line(world(point),'DRAW',index,feed=float(point[3]) if brush else 1.)
            if stop and schedule:schedule[-1][3]=True
        lift=cfg.get('final_lift_m',cfg['lift_m']) if sequence==len(ordered)-1 and not _hover_finish else cfg['lift_m']
        line(world(chain[-1])+[0,0,lift],'LIFT',index)
    targets=np.tile(np.eye(4),(len(schedule),1,1));targets[:,:3,:3]=target_r
    targets[:,:3,3]=np.asarray(planned_positions[1:])
    if _geometry_only and accelerator is None:
        # The native chain already carries each result as the next seed. Verify
        # the whole successful prefix at once instead of 64 Python dispatches.
        # On a bad row preserve the original reach/refinement path and discard
        # every following speculative result before solving from the new seed.
        i=0
        while i<len(schedule):
            checkpoint();batch_started=time.perf_counter()
            rows=model.solve_chain(targets[i:i+64],q[-1])
            dispatcher.cpu_s+=time.perf_counter()-batch_started
            dispatcher.cpu_batches+=1;dispatcher.batches+=1
            qq=np.asarray([r['q'] for r in rows])
            good=np.array([r['ok'] for r in rows]) & np.isfinite(qq).all(axis=1)
            good &= np.max(np.abs(np.diff(np.vstack((q[-1],qq)),axis=0)),axis=1)<=cfg['max_joint_step_rad']
            n=len(rows) if good.all() else int(np.flatnonzero(~good)[0])
            if n:
                base=len(q);part=schedule[i:i+n]
                q.extend(qq[:n]);positions.extend(targets[i:i+n,:3,3].copy())
                phases.extend(PHASE[row[1]] for row in part);stroke_ids.extend(row[2] for row in part)
                feed_ratios.extend(row[4] for row in part)
                stop_nodes.update(base+k for k,row in enumerate(part) if row[3])
                iterations+=sum(r['iterations'] for r in rows[:n]);target_counter+=n
                dispatcher.accepted+=n;i+=n
            if n<len(rows):
                end,phase,stroke,stop,feed=schedule[i]
                reach(end,phase,stroke,proposed=rows[n],feed=feed)
                if stop:stop_nodes.add(len(q)-1)
                dispatcher.accepted+=1;dispatcher.invalidations+=1;i+=1
    else:
        for i,(end,phase,stroke,stop,feed) in enumerate(schedule):
            checkpoint();proposed=dispatcher.next(targets[i:i+64],q[-1])
            reach(end,phase,stroke,proposed=proposed,feed=feed)
            if stop:stop_nodes.add(len(q)-1)
    qs=np.array(q);ps=np.array(positions);ph=np.array(phases,dtype=np.uint32);ids=np.array(stroke_ids,dtype=np.int32)
    if len(qs)<2:raise PlanningError('empty trajectory')
    check_collision_batch(model,qs[1:])
    if _geometry_only:
        # Non-executable intermediate for the short-stroke research path. It has
        # no time law or frame stream and deliberately cannot pass artifact.freeze.
        result=dict(schema='tcb705-geometry-candidate-v1',config=config,
            model_sha256=model.model_sha256,q_start_rad=q_start.tolist(),
            geometric_positions=ps,interval_phase=ph,node_q_rad=qs,
            node_stroke_ids=ids,node_stops=sorted(stop_nodes),
            metrics=dict(dispatcher.metrics(),nodes=len(qs),
                         geometry_s=time.perf_counter()-started))
        _add_brush_metadata(result,brush,feed_ratios)
        return result
    speed=np.where(ph==PHASE['DRAW'],cfg['draw_speed_m_s'],np.where(ph==PHASE['LOWER'],cfg['lower_speed_m_s'],cfg['air_speed_m_s']))
    if brush:speed=speed*np.asarray(feed_ratios)
    dt=np.maximum(np.linalg.norm(np.diff(ps,axis=0),axis=1)/speed,cfg['period_s'])
    # Give a whole phase one smooth start/stop envelope. A 1 mm first segment
    # must not force the complete picture to use its acceleration-limited speed.
    edges=np.unique(np.r_[0,np.flatnonzero(ph[1:]!=ph[:-1])+1,list(stop_nodes),len(ph)]).astype(int)
    lengths=np.linalg.norm(np.diff(ps,axis=0),axis=1)
    # The bisection is element-wise, so all phases share one 45-step loop
    # (one numpy call per step instead of one per step and phase).
    blocks=list(zip(edges[:-1].tolist(),edges[1:].tolist()));fractions=[];totals=[]
    for start,end in blocks:
        cumulative=np.r_[0,np.cumsum(lengths[start:end])];length=cumulative[-1]
        fractions.append(cumulative/length);totals.append(length)
    fraction=np.concatenate(fractions);lo=np.zeros_like(fraction);hi=np.ones_like(fraction)
    for _ in range(45):
        mid=(lo+hi)*.5;value=mid**3*(10+mid*(-15+6*mid))
        lo=np.where(value<fraction,mid,lo);hi=np.where(value>=fraction,mid,hi)
    normalized=(lo+hi)*.5;offset=0
    for (start,end),length in zip(blocks,totals):
        part=normalized[offset:offset+end-start+1];offset+=end-start+1;part[0]=0.;part[-1]=1.
        if brush:
            # Do not stretch the whole stroke by its slow entry feed, or erase
            # authored feed changes when applying the phase start/stop envelope.
            base=(cfg['draw_speed_m_s'] if ph[start]==PHASE['DRAW'] else
                  cfg['lower_speed_m_s'] if ph[start]==PHASE['LOWER'] else cfg['air_speed_m_s'])
            duration=max(1.875*length/base,.12)
            dt[start:end]=np.maximum(dt[start:end],np.diff(part)*duration)
        else:
            duration=max(1.875*length/float(speed[start]),.12)
            dt[start:end]=np.maximum(np.diff(part)*duration,cfg['period_s'])
    if brush:
        # Respect every interval's feed cap after the whole-phase envelope.
        dt=np.maximum(dt,1.875*lengths/speed)
    limits=config['limits'];v=np.array(limits['velocity_rad_s']);a=np.array(limits['acceleration_rad_s2']);jerk=np.array(limits['jerk_rad_s3'])
    dt=np.maximum(dt,np.max(np.abs(np.diff(qs,axis=0))/v,axis=1))
    # Retiming each stop-to-stop block preserves shared C2 derivatives.
    coeff=coefficients(qs,dt,ph,stop_nodes);factors=np.ones(len(dt));peaks=np.zeros((len(dt),3,7))
    for first in range(0,len(coeff),1024):
        checkpoint()
        batch=model.extrema_batch(coeff[first:first+1024]);last=first+len(batch)
        low,high=batch[:,0,1],batch[:,0,2]
        if np.any(low<model.lower-1e-10) or np.any(high>model.upper+1e-10):raise PlanningError('CURVE_LIMIT: 多项式区间越过关节限位')
        for order,limit in [(1,v),(2,a),(3,jerk)]:
            peak=batch[:,order,0]/dt[first:last,None]**order
            peaks[first:last,order-1]=peak
            factors[first:last]=np.maximum(factors[first:last],np.max(peak/limit,axis=1)**(1/order))
    # Independent phase scaling is valid because both endpoint derivatives are zero.
    for start,end in blocks:
        stretch=factors[start:end].max()*1.005;dt[start:end]*=stretch
        for order in range(1,4):peaks[start:end,order-1]/=stretch**order
    factor=float(factors.max());coeff=coefficients(qs,dt,ph,stop_nodes);times=np.r_[0,np.cumsum(dt)]
    if times[-1]>cfg['max_duration_s']:raise PlanningError('DURATION_BUDGET: 计划时间过长')
    metrics={'ik_iterations':iterations,'time_stretch':factor,'nodes':len(qs),'duration_s':float(times[-1]),'corner_stops':len(stop_nodes)-1,'max_path_error_m':None,'max_orientation_error_rad':None,'max_joint_step_rad':float(np.max(np.abs(np.diff(qs,axis=0))))}
    metrics.update(dispatcher.metrics())
    metrics.update(joint_peak_velocity_rad_s=peaks[:,0].max(axis=0).tolist(),
                   joint_peak_acceleration_rad_s2=peaks[:,1].max(axis=0).tolist(),
                   joint_peak_jerk_rad_s3=peaks[:,2].max(axis=0).tolist())
    # No additional FK probe grid: execution still uses the C2 coefficients,
    # analytic joint/dynamic bounds and the timed stream generated below.
    metrics.update(geometry_fk_batches=0,geometry_probe_samples=0,
                   runtime_geometry_verification=False,geometry_error_evaluated=False)
    count=int(math.ceil(times[-1]/cfg['period_s']))+1
    if count>cfg.get('max_frames',150000):raise PlanningError('FRAME_BUDGET: 采样帧数超过 ZYNQ 内存预算，减少图形复杂度后重试')
    ticks=np.arange(count,dtype=float)*cfg['period_s'];ticks[-1]=times[-1]
    seg=np.minimum(np.searchsorted(times,ticks,side='right')-1,len(dt)-1);u=(ticks-times[seg])/dt[seg]
    if getattr(model,'native_sampling',False):
        # Same Horner + float32 rounding in C++ (identical operation order, 2026-10-18).
        sdk,rounded=model.sample_rows(coeff,seg,u)
    else:
        samples=np.zeros((count,7))
        for power in range(5,-1,-1):samples=samples*u[:,None]+coeff[seg,power,:]
        # Freeze the actual SDK float32 rounding into the model-space samples.
        sdk=((samples[:,model.order]-model.offset)*model.sign*180/math.pi).astype(np.float32)
        rounded=np.empty_like(samples);rounded[:,model.order]=sdk.astype(float)*math.pi/180*model.sign+model.offset
    checkpoint()
    if not np.isfinite(rounded).all() or not np.isfinite(sdk).all():raise PlanningError('FINAL_SAMPLE_NONFINITE')
    if np.any(rounded<model.lower) or np.any(rounded>model.upper):raise PlanningError('FINAL_SAMPLE_LIMIT')
    metrics.update(planning_s=time.perf_counter()-started,frames=count,
                   motion_algorithm_version='tcb705-c2-v3-no-runtime-fk',motion_mode='tcb705',
                   collision_model_verified=config['collision_model_verified'])
    ph_seg,ids_seg=ph[seg],ids[seg]
    # Portraits display the cloud image; authored brush paths remain available
    # for calligraphy/handwriting. Neither preview claims to be an FK prediction.
    preview=[np.asarray(chain)[:,:2].tolist() for _,chain in ordered] if brush else []
    preview_source='authored_paths' if brush else 'cloud'
    result=dict(schema='tcb705-plan-v1',config_digest=digest(config),model_sha256=model.model_sha256,
        config=config,q_start_rad=q_start.tolist(),metrics=metrics,period_s=cfg['period_s'],
        preview=dict(width_mm=paper['width_mm'],height_mm=paper['height_mm'],paths=preview,source=preview_source),
        times=ticks,q_rad=rounded,sdk_degrees=sdk,phase=ph_seg,stroke_ids=ids_seg,
        interval_times=times,coefficients=coeff,geometric_positions=ps,interval_phase=ph,
        node_q_rad=qs,node_stroke_ids=ids,node_stops=sorted(stop_nodes))
    _add_brush_metadata(result,brush,feed_ratios)
    return result


def _add_brush_metadata(result,brush,feed_ratios):
    if brush:
        result['calligraphy']=dict(module=brush['module'],version=brush['version'],brush=brush['brush'])
        # Every schema keeps its identity (2026-10-27): execution then checks the revision and
        # writes on the right surface (poem, couplet table, hard pen), not only brush-text-v1.
        if brush.get('schema'):
            result['calligraphy'].update({k:v for k,v in brush.items() if k not in ('depth_mm','feed_ratio')})
        result['interval_feed_ratio']=feed_ratios
