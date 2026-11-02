"""Bounded offline planner. Returned commands always have physical_authorized=False."""
from dataclasses import dataclass
import math
import time
import numpy as np
from r1a.model import finite_array
from r1a.solve import solve
from .path import drawing_targets,lerp_axis,positive
from .geometry import measure_segment

CONTINUOUS_PROFILES = ('continuous_cubic', 'continuous_quintic', 'continuous_quintic_vaj')


@dataclass
class Plan:
    status: str
    commands: object
    targets: list
    diagnostics: list
    metrics: dict
    physical_authorized: bool=False
    trajectory_segments: object=None
    execution_contract: object=None


def validate_config(cfg):
    if cfg.get('motion_profile', 'rest_quintic') not in ('rest_quintic',) + CONTINUOUS_PROFILES:
        raise ValueError('invalid motion_profile')
    if cfg.get('motion_profile') == 'continuous_quintic_vaj':
        from .retiming import normalize_motion_limits
        normalize_motion_limits(cfg)
        if cfg.get('corner_policy', 'preserve') != 'preserve':
            raise ValueError('only verified preserve corner policy is supported')
        if type(cfg.get('retime_max_passes', 4)) is not int or not 1 <= cfg.get('retime_max_passes', 4) <= 4:
            raise ValueError('invalid retime_max_passes')
    for k in ('max_cartesian_step_m','arc_chord_error_m','lift_m','plane_tolerance_m',
              'max_joint_delta_rad','tracking_error_m','tilt_tolerance_rad','max_velocity_rad_s',
              'max_acceleration_rad_s2','command_period_s','min_segment_s','recovery_joint_offset_rad','approach_axis_step_rad'):
        positive(cfg[k],k)
    for k in ('iterations_per_attempt','attempts_with_recovery','iterations_per_target','max_targets','max_commands','max_total_ik_iterations'):
        if type(cfg[k]) is not int or cfg[k]<1: raise ValueError(f'invalid {k}')
    if cfg['iterations_per_attempt']*cfg['attempts_with_recovery']>cfg['iterations_per_target']:
        raise ValueError('recovery exceeds per-target budget')
    if cfg['max_targets']>10000 or cfg['max_commands']>1000000: raise ValueError('unbounded path config')


def expand_approach(model,q0,targets,cfg,spec=None):
    t,_=model.evaluate(q0); a0=t[:3,:3]@model.tool_axis; p0=t[:3,3]
    first=targets[0]; p1=np.array(first['position']); a1=np.array(first['axis'])
    angle=float(np.arctan2(np.linalg.norm(np.cross(a0,a1)),np.dot(a0,a1)))
    approach=[]
    def segment(pa,pb,aa,ab,phase):
        angle=float(np.arctan2(np.linalg.norm(np.cross(aa,ab)),np.dot(aa,ab)))
        if np.linalg.norm(pb-pa)<1e-10 and angle<1e-10:return
        if (cfg.get('planned_vertical') and phase=='LIFT'
                and np.linalg.norm(np.asarray(pa)[:2]-np.asarray(pb)[:2])<1e-10 and angle<1e-10):
            from .sugar import vertical_samples
            # Initial clearance correction may be less than the 2 mm minimum
            # release check; it is an approach, not the end of a drawn stroke.
            initial_phase='APPROACH' if np.linalg.norm(pb-pa)<.002 else phase
            approach.extend(dict(position=p.tolist(),axis=np.asarray(aa).tolist(),phase=initial_phase,
                stroke=-1,vertical_time_s=t) for p,t in vertical_samples(pa,pb,'LIFT',cfg))
            return
        n=max(1,math.ceil(np.linalg.norm(pb-pa)/cfg['max_cartesian_step_m']),math.ceil(angle/cfg['approach_axis_step_rad']))
        approach.extend(dict(position=((1-f)*pa+f*pb).tolist(),axis=lerp_axis(aa,ab,f).tolist(),phase=phase,
            stroke=-1 if phase=='LIFT' else first['stroke']) for f in np.linspace(0,1,n+1)[1:])
    if spec is not None:
        normal=np.asarray(spec['plane_normal']);origin=np.asarray(spec['plane_origin_m'])
        height=max(float((p0-origin)@normal),float((p1-origin)@normal),float(cfg['lift_m']))
        lift_per_clearance=normal
        travel_axis=-normal
        if 'lift_direction' in spec:
            from .path import unit
            direction=unit(spec['lift_direction'],'lift direction')
            clearance_cos=float(direction@normal)
            if clearance_cos<=.1:
                raise ValueError('lift direction must point away from the paper, with normal projection > 0.1')
            lift_per_clearance=direction/clearance_cos
            travel_axis=np.asarray(spec['pen_axis'])
        raised0=p0+lift_per_clearance*(height-float((p0-origin)@normal))
        raised1=p1+lift_per_clearance*(height-float((p1-origin)@normal))
        segment(p0,raised0,a0,a0,'LIFT')
        segment(raised0,raised0,a0,travel_axis,'APPROACH')
        segment(raised0,raised1,travel_axis,travel_axis,'APPROACH')
        segment(raised1,raised1,travel_axis,a1,'APPROACH')
        segment(raised1,p1,a1,a1,'APPROACH')
    else:segment(p0,p1,a0,a1,'APPROACH')
    if not approach:approach=[dict(first,phase='APPROACH')]
    if len(approach)+len(targets)>cfg['max_targets']:raise ValueError('approach budget exceeded')
    return dict(position=p0.tolist(),axis=a0.tolist(),phase='START',stroke=-1), approach+targets[1:]


def motion_segment(model,qa,qb,a,b,cfg,start_time,emit=True):
    """Quintic rest-to-rest joint interpolation, analytical velocity/accel bounds."""
    delta=qb-qa; size=float(np.max(np.abs(delta)))
    if size>cfg['max_joint_delta_rad']+1e-12 and not b.get('joint_space_air'):
        raise ValueError('PATH_DISCONTINUITY')
    duration=max(cfg['min_segment_s'],1.875*size/cfg['max_velocity_rad_s'],
                 math.sqrt((10/math.sqrt(3))*size/cfg['max_acceleration_rad_s2']))
    n=max(2,math.ceil(duration/cfg['command_period_s']))
    if n>cfg['max_commands']: raise ValueError('COMMAND_BUDGET')
    peak_v=1.875*size/duration; peak_a=(10/math.sqrt(3))*size/duration**2
    metrics=dict(duration_s=duration,peak_velocity_rad_s=peak_v,peak_acceleration_rad_s2=peak_a,
                 max_interpolation_error_m=0.,max_tilt_rad=0.,joint_delta_rad=size)
    if not emit:
        # Rest-quintic f stays in [0,1]: legal endpoints bound the entire
        # joint segment. Continuous mode generates/checks the real samples.
        if not model.legal(qa) or not model.legal(qb):
            raise ValueError('INTERPOLATION_ERROR')
        return [],metrics
    commands=[]; max_position=0.; max_tilt=0.
    issued=sorted(set(np.linspace(0,1,n+1).tolist()))
    probes=np.unique(np.concatenate((np.asarray(issued),np.linspace(0,1,17))))
    for start in range(0,len(probes),512):
        us=probes[start:start+512];fs=10*us**3-15*us**4+6*us**5
        joints=qa+fs[:,None]*delta
        desireds=(1-fs[:,None])*np.asarray(a['position'])+fs[:,None]*np.asarray(b['position'])
        axes=np.asarray([lerp_axis(a['axis'],b['axis'],float(f)) for f in fs])
        measured=measure_segment(model,joints,np.asarray(a['position']),np.asarray(b['position']),desireds,axes)
        max_position=max(max_position,measured['path']);max_tilt=max(max_tilt,measured['tilt'])
    if b['phase']=='DRAW' and (max_position>cfg['tracking_error_m'] or max_tilt>cfg['tilt_tolerance_rad']):
        raise ValueError('DRAW_GEOMETRY_ERROR')
    for u in issued[1:]:
        f=10*u**3-15*u**4+6*u**5
        q=qa+f*delta
        p=(1-f)*np.array(a['position'])+f*np.array(b['position'])
        axis=lerp_axis(a['axis'],b['axis'],f)
        if not model.legal(q):
            raise ValueError('INTERPOLATION_ERROR')
        if emit:
            commands.append(dict(t_s=start_time+u*duration,q_rad=q.tolist(),tip_target_m=p.tolist(),
                                 axis_target=axis.tolist(),phase=b['phase'],stroke=b['stroke'],
                                 pen_down=b['phase']=='DRAW',physical_authorized=False))
    return commands,dict(duration_s=duration,peak_velocity_rad_s=peak_v,peak_acceleration_rad_s2=peak_a,
                         max_interpolation_error_m=max_position,max_tilt_rad=max_tilt,joint_delta_rad=size)


def plan(model,spec,q0,ik_cfg,cfg,backend=None,recovery=True,cancel=None,targets_override=None,final_q=None):
    started=time.perf_counter()
    timing=dict(targets_s=0.,ik_s=0.,segment_checks_s=0.,interpolation_s=0.,total_s=0.)
    targets=[]; diagnostics=[]; commands=[]; stats=dict(ik_iterations=0,ik_calls=0,recovery_calls=0,
        max_interpolation_error_m=0.,max_tilt_rad=0.,peak_velocity_rad_s=0.,peak_acceleration_rad_s2=0.,
        duration_s=0.,completed_targets=0,total_targets=0,commands=0)
    def fail(status):
        timing['total_s']=time.perf_counter()-started
        stats['timing']=dict(timing)
        stats.pop('_trajectory_segments', None)
        stats['unattempted_targets']=max(0,len(targets)-len(diagnostics))
        return Plan(status,None,targets,diagnostics,stats)
    try:
        validate_config(cfg)
        if cfg.get('joint_space_air'):
            cfg = dict(cfg, air_plane_origin_m=spec['plane_origin_m'],air_plane_normal=spec['plane_normal'],
                       air_min_clearance_m=.7*float(cfg['lift_m']))
        q=finite_array(q0,(5,),'q0').copy()
        if not model.legal(q): raise ValueError('illegal initial joints')
        targets=drawing_targets(spec,cfg) if targets_override is None else list(targets_override)
        if not targets or len(targets)>cfg['max_targets']:raise ValueError('invalid transfer target budget')
        if final_q is not None:
            final_q=finite_array(final_q,(5,),'final joints')
            if not model.legal(final_q):raise ValueError('illegal final joints')
        previous,targets=expand_approach(model,q,targets,cfg,spec)
    except (ValueError,KeyError,TypeError,OverflowError) as exc:
        stats['detail']=str(exc); return fail('INVALID_INPUT')
    stats['total_targets']=len(targets)
    timing['targets_s']=time.perf_counter()-started
    if hasattr(backend,'begin_plan'):
        backend.begin_plan(cfg['max_total_ik_iterations'])
    joint_knots=[q.copy()]; path_knots=[previous]
    vertical_anchor = None
    for index,target in enumerate(targets):
        if cancel is not None and cancel(): return fail('ABORT')
        budget=min(cfg['iterations_per_target'],cfg['max_total_ik_iterations']-stats['ik_iterations'])
        if budget<=0: return fail('ITERATION_BUDGET')
        attempts=[]; candidate=None; final_status='IK_FAILED'
        count=cfg['attempts_with_recovery'] if recovery else 1
        planned_vertical = cfg.get('planned_vertical') and 'vertical_time_s' in target
        if planned_vertical:
            if (vertical_anchor is None or previous['phase'] != target['phase']
                    or previous['stroke'] != target['stroke']):
                vertical_anchor = (q.copy(), np.asarray(previous['position']))
            count = 1
        else:
            vertical_anchor = None
        for attempt in range(count):
            if cancel is not None and cancel(): return fail('ABORT')
            remaining=budget-sum(item['iterations'] for item in attempts)
            if remaining<=0: break
            seed=q.copy()
            air_recovery=(attempt and target['phase']!='DRAW'
                          and (attempts[-1]['status'] in ('STAGNATION','MAX_ITER','LIMIT_STALL')
                               or attempts[-1].get('transition_status')=='PATH_DISCONTINUITY')
                          and attempts[-1].get('q_last') is not None)
            if air_recovery:
                # A five-joint axis task can stall at a weighted compromise
                # even when both physical error tolerances are achievable.
                # Retry air moves with position priority, without changing
                # their requested pose or the position/tilt success gates.
                seed=q.copy()
            elif attempt:
                # Perturb only the numeric seed, not the physical/planned pose.
                offset=cfg['recovery_joint_offset_rad']*(1 if attempt%2 else -1)
                seed[1:4]+=np.array([offset,-offset,offset])
                seed=np.clip(seed,model.limits[:,0],model.limits[:,1])
            limit=min(remaining,cfg['iterations_per_attempt'] if recovery else cfg['iterations_per_target'])
            local=dict(ik_cfg,max_iterations=limit)
            if air_recovery:
                weights=list(ik_cfg['weights'])
                weights[3:]=[float(w)*(0.01 if attempt==1 else 0.001) for w in weights[3:]]
                local['weights']=weights
            ik_started=time.perf_counter()
            if (not planned_vertical and attempt==0 and hasattr(backend,'prepare_targets')
                    and (not hasattr(backend,'needs_target_batch') or backend.needs_target_batch())):
                # The backend may compute a speculative normal-attempt prefix.
                # Every returned point still passes the original transition
                # checks below; retries and final_q keep the scalar control path.
                stop=len(targets)-(1 if final_q is not None else 0)
                upcoming=targets[index:min(index+64,stop)]
                if cfg.get('planned_vertical'):
                    # A constrained lift changes the authority seed without
                    # going through the speculative PL IK chain.
                    for offset,row in enumerate(upcoming):
                        if 'vertical_time_s' in row:
                            upcoming=upcoming[:offset]
                            break
                if upcoming:
                    backend.prepare_targets(upcoming,index,cfg['max_total_ik_iterations']-stats['ik_iterations'])
            if planned_vertical:
                from .sugar import vertical_result
                r=vertical_result(model,*vertical_anchor,target,seed,local)
            elif hasattr(backend, 'solve_target'):
                r=backend.solve_target(model,target['position'],target['axis'],seed,local,cancel=cancel)
            else:
                r=solve(model,target['position'],target['axis'],seed,local,backend=backend)
            timing['ik_s']+=time.perf_counter()-ik_started
            stats['ik_iterations']+=r.iterations; stats['ik_calls']+=1
            stats['recovery_calls']+=int(attempt>0)
            # Result records own their JSON-native history; they are never
            # mutated after return. Avoid a recursive copy on every target.
            record=dict(vars(r)); record['attempt']=attempt; record['seed']=seed.tolist()
            if air_recovery:record['recovery_policy']='air_position_priority'
            attempts.append(record)
            final_status=r.status
            if r.status=='OK':
                proposed=np.array(r.q_solution) if final_q is None or index!=len(targets)-1 else final_q.copy()
                try:
                    segment_started=time.perf_counter()
                    portion,metrics=motion_segment(model,q,proposed,previous,target,cfg,stats['duration_s'],
                        emit=cfg.get('motion_profile') not in CONTINUOUS_PROFILES)
                    timing['segment_checks_s']+=time.perf_counter()-segment_started
                except ValueError as exc:
                    final_status=str(exc); record['transition_status']=final_status
                    continue
                candidate=proposed; break
            if r.status in ('NUMERIC','INVALID_INPUT','ABORT'): break
        diagnostics.append(dict(index=index,phase=target['phase'],attempts=attempts,status='OK' if candidate is not None else final_status))
        if candidate is None: return fail(final_status)
        if len(commands)+len(portion)>cfg['max_commands']: return fail('COMMAND_BUDGET')
        commands.extend(portion); q=candidate; previous=target
        joint_knots.append(q.copy()); path_knots.append(target)
        stats['duration_s']+=metrics['duration_s']; stats['completed_targets']+=1
        for field in ('max_interpolation_error_m','max_tilt_rad','peak_velocity_rad_s','peak_acceleration_rad_s2'):
            stats[field]=max(stats[field],metrics[field])
    stats['commands']=len(commands)
    if cfg.get('motion_profile') in CONTINUOUS_PROFILES:
        from .continuous import interpolate
        try:
            interpolation_started=time.perf_counter()
            commands, metrics = interpolate(model,joint_knots,path_knots,cfg,cancel)
            timing['interpolation_s']=time.perf_counter()-interpolation_started
            stats.update(metrics)
            if (metrics['max_draw_path_error_m'] > cfg['tracking_error_m']
                    or metrics['max_draw_tilt_rad'] > cfg['tilt_tolerance_rad']):
                stats['detail']='DRAW sampled FK exceeds configured path/tilt tolerance'
                return fail('DRAW_GEOMETRY_ERROR')
        except ValueError as exc:
            return fail(str(exc))
    timing['total_s']=time.perf_counter()-started
    stats['timing']=dict(timing)
    iterations=[a['iterations'] for d in diagnostics for a in d['attempts']]
    stats['iteration_distribution']=dict(p50=float(np.percentile(iterations,50)),
        p95=float(np.percentile(iterations,95)),maximum=max(iterations)) if iterations else {}
    segments = stats.pop('_trajectory_segments', None)
    return Plan('OK',commands,targets,diagnostics,stats,trajectory_segments=segments)
