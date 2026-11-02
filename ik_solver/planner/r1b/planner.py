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


def expand_approach(model,q0,targets,cfg):
    t,_=model.evaluate(q0); a0=t[:3,:3]@model.tool_axis; p0=t[:3,3]
    first=targets[0]; p1=np.array(first['position']); a1=np.array(first['axis'])
    angle=float(np.arctan2(np.linalg.norm(np.cross(a0,a1)),np.dot(a0,a1)))
    n=max(1,math.ceil(np.linalg.norm(p1-p0)/cfg['max_cartesian_step_m']),math.ceil(angle/cfg['approach_axis_step_rad']))
    if n+len(targets)>cfg['max_targets']: raise ValueError('approach budget exceeded')
    approach=[dict(position=((1-f)*p0+f*p1).tolist(),axis=lerp_axis(a0,a1,f).tolist(),phase='APPROACH',stroke=0)
              for f in np.linspace(0,1,n+1)[1:]]
    return dict(position=p0.tolist(),axis=a0.tolist(),phase='START',stroke=-1), approach+targets[1:]


def motion_segment(model,qa,qb,a,b,cfg,start_time,emit=True):
    """Quintic rest-to-rest joint interpolation, analytical velocity/accel bounds."""
    delta=qb-qa; size=float(np.max(np.abs(delta)))
    if size>cfg['max_joint_delta_rad']+1e-12: raise ValueError('PATH_DISCONTINUITY')
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


def plan(model,spec,q0,ik_cfg,cfg,backend=None,recovery=True,cancel=None):
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
        q=finite_array(q0,(5,),'q0').copy()
        if not model.legal(q): raise ValueError('illegal initial joints')
        targets=drawing_targets(spec,cfg)
        previous,targets=expand_approach(model,q,targets,cfg)
    except (ValueError,KeyError,TypeError,OverflowError) as exc:
        stats['detail']=str(exc); return fail('INVALID_INPUT')
    stats['total_targets']=len(targets)
    timing['targets_s']=time.perf_counter()-started
    joint_knots=[q.copy()]; path_knots=[previous]
    for index,target in enumerate(targets):
        if cancel is not None and cancel(): return fail('ABORT')
        budget=min(cfg['iterations_per_target'],cfg['max_total_ik_iterations']-stats['ik_iterations'])
        if budget<=0: return fail('ITERATION_BUDGET')
        attempts=[]; candidate=None; final_status='IK_FAILED'
        count=cfg['attempts_with_recovery'] if recovery else 1
        for attempt in range(count):
            if cancel is not None and cancel(): return fail('ABORT')
            remaining=budget-sum(item['iterations'] for item in attempts)
            if remaining<=0: break
            seed=q.copy()
            if attempt:
                # Perturb only the numeric seed, not the physical/planned pose.
                offset=cfg['recovery_joint_offset_rad']*(1 if attempt%2 else -1)
                seed[1:4]+=np.array([offset,-offset,offset])
                seed=np.clip(seed,model.limits[:,0],model.limits[:,1])
            limit=min(remaining,cfg['iterations_per_attempt'] if recovery else cfg['iterations_per_target'])
            local=dict(ik_cfg,max_iterations=limit)
            ik_started=time.perf_counter()
            if hasattr(backend, 'solve_target'):
                r=backend.solve_target(model,target['position'],target['axis'],seed,local,cancel=cancel)
            else:
                r=solve(model,target['position'],target['axis'],seed,local,backend=backend)
            timing['ik_s']+=time.perf_counter()-ik_started
            stats['ik_iterations']+=r.iterations; stats['ik_calls']+=1
            stats['recovery_calls']+=int(attempt>0)
            # Result records own their JSON-native history; they are never
            # mutated after return. Avoid a recursive copy on every target.
            record=dict(vars(r)); record['attempt']=attempt; record['seed']=seed.tolist(); attempts.append(record)
            final_status=r.status
            if r.status=='OK':
                proposed=np.array(r.q_solution)
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
