"""Deterministic rate/deadband/bias plant and feedback retiming experiment.

Assumptions are explicit simulation inputs, not identified STS3215 parameters.
Measurements are taken before each command write, including the final settle.
"""
import math
import numpy as np
from motion import counts_from_angles, angles_from_counts


class ServoPlant:
    def __init__(self, initial_counts, max_rate_counts_s=190., bias_counts=None, deadband_counts=0.):
        self.counts={int(k):float(v) for k,v in initial_counts.items()}
        self.target=dict(self.counts)
        self.max_rate=float(max_rate_counts_s)
        self.bias={int(k):float(v) for k,v in (bias_counts or {}).items()}
        self.deadband=float(deadband_counts)
        if (not self.counts or not np.isfinite(list(self.counts.values())+list(self.bias.values())+[self.max_rate,self.deadband]).all()
                or self.max_rate<=0 or self.deadband<0 or not set(self.bias)<=set(self.counts)):
            raise ValueError('invalid plant configuration')
    def command(self,counts):
        if set(counts)!=set(self.counts) or not np.isfinite(list(counts.values())).all():
            raise ValueError('invalid plant target')
        self.target={k:float(v) for k,v in counts.items()}
    def advance(self,duration_s,speed=100.):
        if not np.isfinite([duration_s,speed]).all() or duration_s<0 or speed<=0:
            raise ValueError('invalid duration/speed')
        rate=min(self.max_rate,speed)
        for sid,value in self.counts.items():
            error=self.target[sid]+self.bias.get(sid,0)-value
            if abs(error)>self.deadband:
                self.counts[sid]=value+math.copysign(min(abs(error)-self.deadband,rate*duration_s),error)
    def feedback(self):
        return {sid:int(round(v)) for sid,v in self.counts.items()}


def replay_commands(model,machine,commands,initial_counts,speed=100.,max_rate_counts_s=190.,
                    bias_counts=None,deadband_counts=0.,settle_s=1.,controller='open_loop',
                    tip_tolerance_m=.001,normal_tolerance_m=.00075,feedback_tolerance_counts=1,
                    max_wait_s=1.):
    if not commands or controller not in ('open_loop','feedback_retime'):
        raise ValueError('nonempty commands and known controller required')
    if not np.isfinite([settle_s,tip_tolerance_m,normal_tolerance_m,max_wait_s]).all() or min(settle_s,tip_tolerance_m,normal_tolerance_m,max_wait_s)<=0:
        raise ValueError('invalid tracking thresholds')
    plant=ServoPlant(initial_counts,max_rate_counts_s,bias_counts,deadband_counts)
    previous_t=wall=wait_total=0.
    last=dict(initial_counts); last_feedback=dict(initial_counts)
    last_command=None
    normal=np.asarray(machine.get('paper',{}).get('normal',[0,0,1]),float)
    if normal.shape!=(3,) or not np.isclose(np.linalg.norm(normal),1):
        raise ValueError('paper normal must be unit length')
    samples=[]; tip_errors=[]; normal_errors=[]
    max_following=max_target_step=max_feedback_step=0
    draw_frames=zero_target_frames=small_target_frames=zero_feedback_frames=0
    stopped=None
    final_target=None
    def observe(feedback,command):
        q=angles_from_counts(machine,feedback)
        delta=model.pose(q)[:3,3]-np.asarray(command['tip_target_m'])
        return float(np.linalg.norm(delta)),float(abs(delta@normal))
    for index,command in enumerate(commands):
        when=float(command['t_s'])
        if not np.isfinite(when) or when<=previous_t:
            raise ValueError('command times must increase')
        dt=when-previous_t
        plant.advance(dt,speed); wall+=dt
        feedback=plant.feedback()
        # Feedback holds virtual path progress until the previous command arrives.
        # A persistent bias cannot be cured by waiting: terminate on max_wait.
        waited=0.
        if controller=='feedback_retime':
            while max(abs(feedback[sid]-last[sid]) for sid in last)>feedback_tolerance_counts:
                if waited>=max_wait_s-1e-12:
                    stopped='FOLLOWING_TIMEOUT'; break
                step=min(.01,max_wait_s-waited)
                plant.advance(step,speed); wall+=step; waited+=step
                feedback=plant.feedback()
            wait_total+=waited
        if stopped:
            break
        target=counts_from_angles(machine,command['q_rad'])
        following=max(abs(feedback[sid]-last[sid]) for sid in last)
        target_step=max(abs(target[sid]-last[sid]) for sid in last)
        feedback_step=max(abs(feedback[sid]-last_feedback[sid]) for sid in last)
        max_following=max(max_following,following)
        max_target_step=max(max_target_step,target_step)
        max_feedback_step=max(max_feedback_step,feedback_step)
        tip,plane=observe(feedback,command)
        if command.get('pen_down'):
            draw_frames+=1; tip_errors.append(tip); normal_errors.append(plane)
            zero_target_frames+=int(target_step==0)
            small_target_frames+=int(target_step<=1)
            zero_feedback_frames+=int(feedback_step==0)
        if index<4 or index%50==0 or index==len(commands)-1:
            samples.append(dict(index=index,planned_s=when,wall_s=wall,wait_s=waited,
                target_counts=target,feedback_counts=feedback,pen_down=bool(command.get('pen_down')),
                tip_error_m=tip,normal_error_m=plane))
        plant.command(target)
        last=target; last_feedback=feedback; last_command=command
        final_target=target; previous_t=when
    plant.advance(settle_s,speed)
    feedback=plant.feedback()
    final_error=max(abs(feedback[sid]-last[sid]) for sid in last)
    final_tip,final_normal=observe(feedback,last_command) if last_command else (None,None)
    task_complete=stopped is None and final_target is not None and final_error<=8
    max_tip=max(tip_errors,default=0.); max_normal=max(normal_errors,default=0.)
    qualified=bool(task_complete and draw_frames and max_tip<=tip_tolerance_m and max_normal<=normal_tolerance_m
                   and final_tip<=tip_tolerance_m and final_normal<=normal_tolerance_m)
    return dict(scope='OFFLINE_RATE_LIMITED_PLANT',controller=controller,
        task_complete=task_complete,tracking_qualified=qualified,
        tracking_status='PASS' if qualified else (stopped or 'TRACKING_FAIL'),
        command_count=len(commands),executed_commands=0 if final_target is None else index+(not bool(stopped)),
        planned_duration_s=float(commands[-1]['t_s']),elapsed_s=wall+settle_s,added_wait_s=wait_total,
        draw_frames=draw_frames,zero_target_draw_frames=zero_target_frames,
        small_target_draw_frames=small_target_frames,zero_feedback_draw_frames=zero_feedback_frames,
        max_following_error_counts=int(max_following),max_target_step_counts=int(max_target_step),
        max_feedback_step_counts=int(max_feedback_step),max_draw_tip_error_m=max_tip,
        rms_draw_tip_error_m=float(np.sqrt(np.mean(np.square(tip_errors)))) if tip_errors else None,
        max_draw_normal_error_m=max_normal,final_error_counts=int(final_error),
        final_tip_error_m=final_tip,final_normal_error_m=final_normal,final_feedback_counts=feedback,
        thresholds=dict(tip_tolerance_m=tip_tolerance_m,normal_tolerance_m=normal_tolerance_m,
            feedback_tolerance_counts=feedback_tolerance_counts,max_wait_s=max_wait_s),
        plant=dict(max_rate_counts_s=max_rate_counts_s,command_speed=speed,
            bias_counts=bias_counts or {},deadband_counts=deadband_counts),samples=samples)
