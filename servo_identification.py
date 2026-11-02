"""Fit measured servo units, static sag and lag from saved samples; no I/O."""
import hashlib
import json
import math
import numpy as np

SCHEMA = 'so101-servo-identification-v1'
RAD_PER_COUNT = 2 * math.pi / 4096


def _finite(value, label, positive=False):
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(label+' must be finite'+(' and positive' if positive else ''))
    return value


def _unit_fit(rows, measured_key, code_key):
    results = {}; reasons = []
    for joint in range(1, 6):
        selected = [r for r in rows if r.get('joint_id') == joint]
        if len(selected) < 3:
            reasons.append('joint_%d_needs_three_%s_samples' % (joint,code_key)); continue
        codes=np.array([_finite(r[code_key],code_key,True) for r in selected])
        if len(np.unique(codes)) < 2:
            reasons.append('joint_%d_needs_two_%s_codes' % (joint,code_key)); continue
        values=np.array([_finite(r[measured_key],measured_key,True) for r in selected])
        unit=float(np.dot(codes,values)/np.dot(codes,codes))
        maximum=float(np.max(np.abs(codes*unit-values)/values))
        results[str(joint)]=dict(unit=unit,max_relative_error=maximum,samples=len(selected))
        if maximum > .15: reasons.append('joint_%d_%s_fit_error_above_15pct' % (joint,code_key))
    unit=float(np.median([r['unit'] for r in results.values()])) if results else None
    if unit and any(abs(r['unit']-unit)/unit > .15 for r in results.values()):
        reasons.append(code_key+'_units_disagree_between_joints')
    return dict(status='PASS' if not reasons else 'PENDING_OR_REJECT', common_unit=unit,
                per_joint=results,reasons=reasons)


def identify(dataset):
    if dataset.get('schema') != SCHEMA or dataset.get('source') not in ('measured','simulation'):
        raise ValueError('Need explicit identification schema and measured/simulation source')
    digest=hashlib.sha256(json.dumps(dataset,sort_keys=True,allow_nan=False).encode()).hexdigest()
    speed_rows=[]
    for row in dataset.get('speed_samples',[]):
        if row.get('steady_window') is not True:
            raise ValueError('Speed measurements must exclude acceleration/deceleration windows')
        value=abs(_finite(row['distance_counts'],'distance_counts'))*RAD_PER_COUNT/_finite(row['elapsed_s'],'elapsed_s',True)
        speed_rows.append(dict(row,measured_rad_s=value))
    speed=_unit_fit(speed_rows,'measured_rad_s','speed_code')
    acceleration=_unit_fit(dataset.get('acceleration_samples',[]),'measured_rad_s2','acceleration_code')
    servo=dict(frame_speed_enabled=False,units_verified=False,unverified_policy='preserve_static')
    actual=dataset['source']=='measured'
    signature=dataset.get('verified_registers')
    registers_ok=isinstance(signature,dict) and bool(signature)
    if registers_ok:
        for joint in range(1,6):
            row=signature.get(str(joint),signature)
            if not isinstance(row,dict) or any(k not in row for k in ('firmware','velocity_unit','maximum_acceleration','acceleration_multiplier')):
                registers_ok=False;break
            fw=row['firmware']
            if not isinstance(fw,dict) or any(type(fw.get(k)) is not int for k in ('major','minor')):
                registers_ok=False;break
            if any(type(row[k]) is not int for k in ('velocity_unit','maximum_acceleration','acceleration_multiplier')):
                registers_ok=False;break
    if speed['status']=='PASS' and acceleration['status']=='PASS':
        servo.update(speed_unit_rad_s=speed['common_unit'],acceleration_unit_rad_s2=acceleration['common_unit'],
            units_verified=actual and registers_ok,measurement_id=digest)
        if registers_ok:servo['verified_registers']=signature
    bias_result=dict(status='PENDING',samples=[],reasons=[])
    for row in dataset.get('load_samples',[]):
        if row.get('stationary') is not True or _finite(row.get('settled_s',0),'settled_s') < .5:
            raise ValueError('Load samples require a stationary settled window of at least 0.5 s')
        tip=np.asarray(row['tip_m'],float)
        if tip.shape!=(3,) or not np.isfinite(tip).all():raise ValueError('tip_m must be finite XYZ')
        counts={str(j):_finite(row['target_counts'][str(j)],'target')-_finite(row['measured_counts'][str(j)],'measured') for j in range(1,6)}
        if max(abs(c) for c in counts.values()) > 32:raise ValueError('Static bias above 32 counts requires mechanical investigation')
        bias_result['samples'].append(dict(tip_m=tip.tolist(),counts=counts))
    if len(bias_result['samples'])>=5:
        points=np.array([r['tip_m'] for r in bias_result['samples']])
        if np.linalg.matrix_rank(points[:,:2]-points[:,:2].mean(axis=0),tol=1e-5)>=2:
            bias_result['status']='PASS'
        else:bias_result['reasons'].append('load_points_do_not_span_2D')
    delay_result=dict(status='PENDING',seconds={},rms_counts={},reasons=[])
    for row in dataset.get('delay_samples',[]):
        joint=str(row.get('joint_id'))
        if joint not in ('1','2','3','4','5') or joint in delay_result['seconds']:
            raise ValueError('Exactly one delay series per joint ID')
        # Static bias and time lag are confounded on a constant-velocity ramp.
        # A separately measured sag is required, rather than silently fitting both.
        if row.get('bias_independently_measured') is not True:
            raise ValueError('Delay identification requires an independently measured static bias')
        bias=_finite(row['bias_counts'],'bias_counts')
        t=np.asarray(row['time_s'],float);target=np.asarray(row['target_counts'],float);observed=np.asarray(row['measured_counts'],float)
        if (t.ndim!=1 or len(t)<20 or target.shape!=t.shape or observed.shape!=t.shape
                or not all(np.isfinite(a).all() for a in (t,target,observed)) or np.any(np.diff(t)<=0) or t[-1]-t[0]<1.):
            raise ValueError('Delay series requires >=20 monotonic finite timestamped samples spanning >=1s')
        if np.ptp(target)<20.:raise ValueError('Insufficient movement to identify delay')
        valid=t>=t[0]+.5
        if np.sum(valid)<10:raise ValueError('Insufficient delayed-window samples')
        grid=np.linspace(0.,.2,201)
        costs=np.array([np.mean((np.interp(t[valid]-delay,t,target)-bias-observed[valid])**2) for delay in grid])
        index=int(np.argmin(costs));rms=float(np.sqrt(costs[index]))
        delay_result['seconds'][joint]=float(grid[index]);delay_result['rms_counts'][joint]=rms
        if index==200:delay_result['reasons'].append('joint_'+joint+'_lag_at_0.2s_limit')
        if rms>3.:delay_result['reasons'].append('joint_'+joint+'_lag_residual_above_3counts')
        if float(np.max(costs)-np.min(costs))<1.:
            delay_result['reasons'].append('joint_'+joint+'_lag_unidentifiable')
    if len(delay_result['seconds'])==5 and not delay_result['reasons']:delay_result['status']='PASS'
    candidate=dict(servo_profile=servo,
        load_bias_counts=dict(enabled=False,calibrated=actual and bias_result['status']=='PASS',measurement_id=digest,samples=bias_result['samples']),
        joint_delay_s=dict(enabled=False,calibrated=actual and delay_result['status']=='PASS',measurement_id=digest,seconds=delay_result['seconds']))
    return dict(schema=SCHEMA,source=dataset['source'],measurement_id=digest,speed=speed,acceleration=acceleration,
                load_bias=bias_result,delay=delay_result,register_signature='PASS' if registers_ok else 'PENDING',execution_candidate=candidate,
                physical_motion_sent=False,note='Offline fitted candidates remain disabled. Verify register convention and independent low-speed motion before enabling.')
