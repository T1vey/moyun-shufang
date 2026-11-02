"""Explicit, reversible migration to the October 13 user-selected scheme."""
import copy
import math

VERSION = 'sugar-fast-implementation-v1'


def documented_position_stream(machine, snapshot):
    """Use the readback-checked STS documented speed unit, not measured dynamics.

    The old 100 step/s cap cannot follow 0.9 rad/s sampled trajectories. The
    position stream uses 700 step/s (1.074 rad/s) as an internal ceiling, while
    the existing planned velocity/acceleration/jerk bounds remain unchanged.
    No EEPROM, acceleration, PID, TCP or calibration values are written here.
    """
    out = copy.deepcopy(machine)
    profile = out.setdefault('execution', {}).setdefault('servo_profile', {})
    if profile.get('units_verified') is True:
        raise ValueError('Do not replace an already measured servo profile')
    keys = ('model','mode','firmware','phase','velocity_unit','maximum_speed',
            'acceleration','acceleration_multiplier')
    signatures = {}
    for joint in out['joints']:
        sid = joint['id']; row = snapshot.get(sid, snapshot.get(str(sid), {}))
        if any(key not in row for key in keys):
            raise ValueError('Incomplete STS register readback for ID %s' % sid)
        signatures[str(sid)] = {key: copy.deepcopy(row[key]) for key in keys}
    profile.update(position_stream_policy='sts_phase12_position_v1',speed_codes=700,
                   frame_speed_enabled=False,units_verified=False,
                   verified_registers=signatures,
                   speed_mapping_source='https://ftservo.github.io/ftservo-wiki/reference/parameter/memory-sts/',
                   mapping_scope='Documented register mapping; dynamic response not calibrated')
    profile.pop('acceleration_codes', None)
    from smooth_motion import ServoSettings
    ServoSettings(out, dict(servo_profile=profile,joint_max_velocity_rad_s=[.9]*5,
                           joint_max_acceleration_rad_s2=[4.]*5))
    return out


def migrate(machine):
    if not isinstance(machine,dict) or machine.get('schema') != 'so101-machine-v1':
        raise ValueError('Expected so101-machine-v1')
    out = copy.deepcopy(machine)
    out.setdefault('trajectory',{}).update(
        command_period_s=.02,lift_m=.006,stroke_end_pause_s=0.,
        lift_ready_pause_s=0.,lower_ready_pause_s=.05,travel_ready_pause_s=0.,
        min_lift_motion_s=.22,min_lower_motion_s=.28)
    execution=out.setdefault('execution',{})
    execution.update(default_motion_mode='sugar_fast',vertical_pen_lift=True,
                     elbow_first_lift=False,position_feedback_period_s=.1)
    profile=execution.setdefault('servo_profile',{})
    profile.setdefault('speed_codes',100)
    profile.setdefault('units_verified',False)
    profile.update(frame_speed_enabled=True,unverified_policy='preserve_static')
    execution.setdefault('load_bias_counts',dict(enabled=False,calibrated=False,measurement_id='',samples=[]))
    execution.setdefault('joint_delay_s',dict(enabled=False,calibrated=False,measurement_id='',seconds={}))
    paper=out.setdefault('paper',{})
    # The user explicitly retained the existing home height because clearance
    # is not measured. This offset is relative to saved home_q, not the paper.
    home=float(paper.get('home_height_offset_m',0.) or 0.)
    if not math.isfinite(home):raise ValueError('Invalid home offset')
    out['new_scheme']=dict(version=VERSION,default_motion_mode='sugar_fast',
        calibration_required=True,physical_acceptance='PENDING',
        pressure_offset_policy='Set -1 to -1.5mm only after fitted paper and verified spring holder',
        note='No fabricated TCP, encoder zero, servo units, load bias or delay values.')
    return out
