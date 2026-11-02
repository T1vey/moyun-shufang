"""Bounded 5 mm air-only commissioning probe; explicit --execute-air required.

Measures simulated release -> local IK/segment validation -> SDK dispatch ->
feedback displacement >0.05 mm. NOT a handwriting recognizer or paper test.
Never changes calibration, clears faults, homes, or executes research artifacts.
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tcb705.config import load
from tcb705.model import Model,pose_error
from tcb705.collision import check_batch
from tcb705.sdk_motion import open_client
from tcb705.web_control import Controller,settle_pose


def air_guard(model,q,anchor,paper_z):
    q=np.asarray(q,dtype=float)
    if q.ndim!=2 or q.shape[1]!=7 or not np.isfinite(q).all():
        raise ValueError('INVALID_JOINTS')
    if np.any(q<model.lower) or np.any(q>model.upper):
        raise ValueError('JOINT_LIMIT')
    poses=model.fk_batch(q)
    xyz=poses[:,:3,3]
    if np.any(xyz[:,2]<paper_z+.060):raise ValueError('AIR_CLEARANCE_60MM')
    if np.any(np.linalg.norm(xyz-anchor[:3,3],axis=1)>.008):
        raise ValueError('AIR_ENVELOPE_8MM')
    if np.any(np.abs(xyz[:,2]-anchor[2,3])>.001):raise ValueError('AIR_HEIGHT_1MM')
    if any(pose_error(anchor,p)[1]>.0175 for p in poses):raise ValueError('AIR_ORIENTATION_1DEG')
    check_batch(model,q)
    return poses


def plan_line(model,q0,direction,paper_z):
    """21-point seeded IK chain, then check actual rounded unblended SDK segment."""
    anchor=model.fk(q0)
    targets=np.repeat(anchor[None],21,axis=0)
    targets[:,1,3]+=float(direction)*np.linspace(0,.005,21)
    solved=model.solve_chain(targets,q0)
    if len(solved)!=len(targets) or not all(r['ok'] for r in solved):raise ValueError('IK_FAILED')
    chain=np.array([r['q'] for r in solved])
    if np.max(np.abs(chain-q0))>np.deg2rad(2):raise ValueError('JOINT_DELTA_2DEG')
    air_guard(model,chain,anchor,paper_z)
    sdk_q=np.asarray([float('%.4f'%v) for v in model.to_sdk(chain[-1])],dtype=np.float32).astype(float)
    end=model.from_sdk(sdk_q)
    fractions=np.linspace(0,1,129)
    rounded=q0+(end-q0)*fractions[:,None]
    poses=air_guard(model,rounded,anchor,paper_z)
    straight=anchor[:3,3]+np.array([0,direction*.005,0])*fractions[:,None]
    error=float(np.max(np.linalg.norm(poses[:,:3,3]-straight,axis=1)))
    if error>.00005:raise ValueError('JOINT_LINE_ERROR_0_05MM')
    return sdk_q,anchor,dict(nodes=21,segment_probes=129,line_error_mm=error*1000)


def measure(sdk,model,q0,direction,paper_z,clock=time.perf_counter,trace=None):
    t0=clock()  # Synthetic release: preloaded line input, connection already ready.
    target,anchor,geometry=plan_line(model,q0,direction,paper_z)
    planned=clock()
    seq=sdk.move('J',target,smooth=0,acc=0,dec=0)
    ack=clock()
    if seq<10:raise RuntimeError('NO_TRACKABLE_SEQUENCE: %s'%seq)
    samples=[];first=None;last_below=None;changed=[];previous=None;done_time=None
    if trace is not None:
        trace.update(target_sdk_degrees=target.tolist(),start_q_rad=q0.tolist(),samples=samples,
                     planning_ms=(planned-t0)*1000,command_ack_ms=(ack-planned)*1000,sequence=seq)
    target_q=model.from_sdk(target);last_change=clock();stable=0
    while clock()-t0<8:
        a=clock();q=model.from_sdk([float(v) for v in sdk.call('JOINTS')]);b=clock()
        pose=model.fk(q);displacement=float(np.linalg.norm(pose[:3,3]-anchor[:3,3]))*1000
        air_guard(model,q[None],anchor,paper_z)
        if np.max(np.abs(q-q0))>np.deg2rad(3):raise RuntimeError('LIVE_JOINT_ENVELOPE')
        item=dict(request_ms=(a-t0)*1000,response_ms=(b-t0)*1000,
                  displacement_mm=displacement,q_rad=q.tolist())
        samples.append(item)
        if previous is None or np.max(np.abs(q-previous))>1e-8:
            changed.append((b-t0)*1000);previous=q.copy();last_change=b
        if first is None:
            if displacement>.05:first=item
            else:last_below=item
        done=sdk.finished(seq)
        if done is False:raise RuntimeError('SDK_MOTION_FAILED')
        if done is True and done_time is None:done_time=(clock()-t0)*1000
        endpoint_error=np.linalg.norm(pose[:3,3]-model.fk(target_q)[:3,3])
        near=np.max(np.abs(q-target_q))<np.deg2rad(.15) and endpoint_error<.0003
        stable=stable+1 if near else 0
        if done is True and stable>=3:
            state=sdk.state()
            if state['move']==0 and state['link'] and not state['paused']:break
        if b-last_change>2 and done is not True:raise RuntimeError('NO_FEEDBACK_PROGRESS')
        time.sleep(.002)
    else:raise RuntimeError('MOTION_DEADLINE')
    if first is None:raise RuntimeError('NO_MEASURED_DISPLACEMENT')
    if np.linalg.norm(pose[:3,3]-model.fk(target_q)[:3,3])>.0003:raise RuntimeError('ENDPOINT_ERROR')
    return dict(planning_ms=(planned-t0)*1000,command_ack_ms=(ack-planned)*1000,
        release_to_feedback_threshold_ms=first['response_ms'],
        dispatch_to_feedback_threshold_ms=first['response_ms']-(planned-t0)*1000,
        last_below_threshold_ms=last_below['response_ms'] if last_below else None,
        first_above_request_ms=first['request_ms'],first_above_response_ms=first['response_ms'],
        threshold_mm=.05,completion_ms=(clock()-t0)*1000,sequence=seq,geometry=geometry,
        done_callback_observed_ms=done_time,endpoint_error_mm=float(endpoint_error)*1000,
        final_q_rad=q.tolist(),distinct_feedback_ms=changed,samples=samples)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--execute-air',action='store_true');p.add_argument('--trials',type=int,default=4)
    args=p.parse_args()
    if not 1<=args.trials<=6:raise ValueError('1..6 trials only')
    c=load(args.config);model=Model(c);paper_z=c['paper']['origin_m'][2]
    ctrl=Controller(c['controller'],c['robot_id'],timeout=1);ctrl.login()
    sdk,info=open_client(c);old_speed=None;stop_event=threading.Event();armed=False
    report=dict(kind='air-only-5mm-line-response',real_motion=args.execute_air,
        includes_handwriting_recognition=False,includes_pen_contact=False,
        sensor_timestamp_available=False,sdk=info,records=[])
    def emergency(reason):
        print('STOP',reason,flush=True)
        try:sdk.stop(True)
        except Exception as e:print('SDK_STOP_ERROR',str(e),flush=True)
        print('WEB_STOP',ctrl.stop(),flush=True)
    def watchdog():
        if not stop_event.wait(55):emergency('TEST_WATCHDOG_55_SECONDS')
    try:
        state=ctrl.state();alarms=ctrl.strict_active_alarms();ss=sdk.state()
        if alarms or sdk.alarms() or state['_phc_alarm_']!='0':raise RuntimeError('ACTIVE_ALARM')
        if ss['move']!=0 or ss['paused'] or not ss['link']:raise RuntimeError('CONTROLLER_NOT_IDLE')
        if state['_phc_key']=='100':raise RuntimeError('EXISTING_PROGRAM_RUNNING')
        before=settle_pose(ctrl,n=3,interval=.05)
        q=model.from_sdk([float(v) for v in sdk.call('JOINTS')]);anchor=model.fk(q)
        if np.linalg.norm(anchor[:3,3]*1000-before[:3])>.5:raise RuntimeError('SDK_WEB_MISMATCH')
        air_guard(model,q[None],anchor,paper_z)
        _,_,geometry=plan_line(model,q,1,paper_z)
        report['before']=dict(pose=before,state=state,geometry=geometry)
        print('PREFLIGHT',json.dumps(report['before']),flush=True)
        if not args.execute_air:return
        threading.Thread(target=watchdog,daemon=True).start();armed=True
        old_speed=sdk.speed()
        if state['g_servo_statero_']!='1' or state['_phc_ctrlkey']!='100':
            ctrl.power('auto');time.sleep(1.5)
        state=ctrl.state()
        if state['g_servo_statero_']!='1' or state['_phc_alarm_']!='0' or ctrl.strict_active_alarms():
            raise RuntimeError('ENABLE_FAILED: '+json.dumps(state))
        now=settle_pose(ctrl,n=3,interval=.1)
        if np.linalg.norm(np.array(now[:3])-before[:3])>10:raise RuntimeError('ENABLE_SHIFT')
        q=model.from_sdk([float(v) for v in sdk.call('JOINTS')]);origin=model.fk(q)
        air_guard(model,q[None],origin,paper_z)
        speed=c['execution']['web_program']['draw_speed_pct'];sdk.set_speed(speed)
        report['speed_pct']=speed;report['ready_pose']=now
        print('READY_ENABLED',json.dumps(dict(pose=now,speed=speed)),flush=True)
        for i in range(args.trials):
            if ctrl.strict_active_alarms() or sdk.alarms():raise RuntimeError('ALARM_BETWEEN_TRIALS')
            state=sdk.state()
            if state['move']!=0 or state['paused'] or not state['link']:raise RuntimeError('NOT_IDLE')
            # Stationary start is verified before simulated release, as in an armed session.
            qs=[]
            for _ in range(5):
                qs.append(model.from_sdk([float(v) for v in sdk.call('JOINTS')]));time.sleep(.015)
            if np.max(np.ptp(np.asarray(qs),axis=0))>np.deg2rad(.015):raise RuntimeError('START_NOT_STATIONARY')
            q=qs[-1]
            if np.linalg.norm(model.fk(q)[:3,3]-origin[:3,3])>.006:raise RuntimeError('GLOBAL_AIR_ENVELOPE')
            trace={};report['active_trial']=trace
            record=measure(sdk,model,q,1 if i%2==0 else -1,paper_z,trace=trace)
            report.pop('active_trial')
            record['trial']=i+1;report['records'].append(record)
            print('TRIAL',json.dumps({k:v for k,v in record.items() if k not in ('samples','distinct_feedback_ms','final_q_rad')}),flush=True)
            time.sleep(.25)
        report['final_pose']=settle_pose(ctrl,n=3,interval=.05)
        report['final_state']=ctrl.state();report['final_sdk_state']=sdk.state()
        report['final_alarms']=ctrl.strict_active_alarms()
        print('COMPLETE',json.dumps({k:report[k] for k in ('final_pose','final_state','final_sdk_state','final_alarms')}),flush=True)
    except BaseException as e:
        report['error']=type(e).__name__+': '+str(e)
        if armed:emergency(report['error'])
        raise
    finally:
        if armed:
            try:sdk.stop(True)
            except Exception as e:report['final_stop_error']=str(e);ctrl.stop()
        if old_speed is not None:
            try:sdk.set_speed(old_speed)
            except Exception as e:report['speed_restore_error']=str(e)
        stop_event.set();sdk.close()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')

if __name__=='__main__':main()
