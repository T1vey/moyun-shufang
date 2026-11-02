"""Explicit endpoint pauses in the saved and executed pen trajectory."""
import copy,math
import numpy as np

VERSION='pen-transitions-v2'
DEFAULTS={'DRAW':('stroke_end_pause_s',0.),'LIFT':('lift_ready_pause_s',.8),
          'LOWER':('lower_ready_pause_s',.2),'TRAVEL':('travel_ready_pause_s',.1)}


def add_endpoint_pauses(result, cfg, *, consume=False):
    """Hold every stroke endpoint and raised endpoint, even with perfect feedback.

    These constant-position pieces are part of the plan, rather than an
    optional encoder tolerance gate. No waits occur at internal DRAW vertices.
    consume=True transfers ownership of freshly generated rows/commands to
    this function, avoiding a second copy of the entire command stream.
    """
    from r1b.continuous import evaluate
    rows=result.trajectory_segments
    if result.status!='OK' or not rows:return
    period=float(cfg['command_period_s']);pauses={}
    if not math.isfinite(period) or period <= 0:raise ValueError('Invalid command_period_s')
    for phase,(key,default) in DEFAULTS.items():
        seconds=float(cfg.get(key,default))
        if not math.isfinite(seconds) or not 0.<=seconds<=5.:raise ValueError('Invalid '+key)
        pauses[phase]=int(math.ceil(seconds/period-1e-9))
    holds={}
    for i,source in enumerate(rows):
        after=rows[i+1] if i+1<len(rows) else None
        boundary=after is None or (source['phase'],source['stroke'])!=(after['phase'],after['stroke'])
        number=pauses.get(source['phase'],0) if boundary else 0
        if number:
            coeff=np.asarray(source['coeffs']);q,v,a=evaluate(coeff,1.,source['duration_s'])
            if not source['hard_stop_end'] or max(np.max(abs(v)),np.max(abs(a)))>1e-7:
                raise ValueError('Pen transition endpoint must be at rest')
            holds[i]=(number,q)
    if len(result.commands)+sum(n for n,_ in holds.values())>cfg.get('max_commands',float('inf')):
        raise ValueError('COMMAND_BUDGET')
    new_rows=[];commands=[];cursor=cycles=block_shift=0;counts={k:0 for k in pauses}
    original=result.commands
    for i,source in enumerate(rows):
        end=source['start_time_s']+source['duration_s']
        row=source if consume else copy.deepcopy(source)
        row['start_time_s']+=cycles*period;row['motion_block_id']+=block_shift
        new_index=len(new_rows);new_rows.append(row)
        while cursor<len(original) and original[cursor]['t_s']<=end+1e-9:
            command=original[cursor] if consume else dict(original[cursor]);cursor+=1
            command.update(t_s=(cursor+cycles)*period,path_segment_index=new_index,motion_block_id=row['motion_block_id'])
            commands.append(command)
        if i not in holds:continue
        number,q=holds[i];coeff=np.asarray(source['coeffs'])
        hold=copy.deepcopy(row);constant=np.zeros_like(coeff);constant[0]=q
        hold.update(coeffs=constant.tolist(),start_time_s=(cursor+cycles)*period,duration_s=number*period,
            motion_block_id=row['motion_block_id']+1,segment_start_m=list(row['segment_end_m']),
            axis_start=list(row['axis_end']),hard_stop_end=True,stop_reason='pen_endpoint_pause',endpoint_pause=True)
        hold_index=len(new_rows);new_rows.append(hold)
        reference=dict(commands[-1]);zero=np.zeros(5).tolist()
        for k in range(1,number+1):
            command=dict(reference)
            command.update(t_s=(cursor+cycles+k)*period,q_rad=q.tolist(),velocity_rad_s=zero,
                acceleration_rad_s2=zero,jerk_rad_s3=zero,tip_target_m=list(row['segment_end_m']),
                axis_target=list(row['axis_end']),path_segment_index=hold_index,
                motion_block_id=hold['motion_block_id'],hard_stop=k==number,endpoint_pause=True)
            commands.append(command)
        cycles+=number;block_shift+=1;counts[source['phase']]+=1
    assert cursor==len(original)
    # Use the same multiplication as fixed-grid command timestamps. Adding
    # 0.8 and 0.1 can otherwise put a phase edge one ULP before its command.
    for i,row in enumerate(new_rows):
        if i==0 or new_rows[i-1]['hard_stop_end']:
            row['start_time_s']=round(row['start_time_s']/period)*period
    for i,row in enumerate(new_rows):
        end=new_rows[i+1]['start_time_s'] if i+1<len(new_rows) else len(commands)*period
        row['duration_s']=end-row['start_time_s']
    result.commands=commands;result.trajectory_segments=new_rows
    result.metrics.update(duration_s=len(commands)*period,commands=len(commands),pen_transition_version=VERSION,
        pen_transitions=dict(version=VERSION,pause_count=counts,planned_pause_s=cycles*period,
            pause_s={p:n*period for p,n in pauses.items()},scope='planned fixed endpoint pauses; no contact sensor or abort gate'))
    for key in ('hard_stop_knots','motion_blocks'):
        if key in result.metrics:result.metrics[key]+=sum(counts.values())
