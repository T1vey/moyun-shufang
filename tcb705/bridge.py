"""Bounded SDK read-only probe and offline runner; no legacy serial fallback."""
import ipaddress
import json
import subprocess
import sys
import time
from .model import ROOT,Model
from .artifact import load

def feedback(config):
    controller=config['controller']
    for name in ('local_ip','remote_ip'):ipaddress.ip_address(controller[name])
    port=controller['port']
    if type(port) is not int or not 1<=port<=65535:raise ValueError('invalid controller port')
    executable=ROOT/'build/tcb705/tcb_sdk_probe'
    if sys.platform!='linux' or not executable.is_file():raise ValueError('只读 SDK 工具需先在 ZYNQ 运行 python3 scripts/build_tcb705.py --sdk')
    completed=subprocess.run([str(executable),controller['local_ip'],controller['remote_ip'],str(port),str(config['robot_id'])],capture_output=True,text=True,timeout=20)
    if completed.returncode:raise ValueError('华成只读连接失败：'+completed.stderr[-400:])
    lines=[x[len('TCB_JSON '):] for x in completed.stdout.splitlines() if x.startswith('TCB_JSON ')]
    if len(lines)!=1:raise ValueError('SDK 工具未返回唯一的关节读数')
    data=json.loads(lines[0]);model=Model(config);q=model.from_sdk(data['joint_degrees'])
    if not model.legal(q):raise ValueError('反馈经 SDK 映射后超出 URDF 限位，请检查轴序、符号和零位')
    data['q_rad']=q.tolist();data['host_received_monotonic']=time.monotonic()
    data['model_tcp_transform']=model.fk(q).tolist();data['sdk_mapping_verified']=config['sdk_mapping_verified']
    data['feedback_timestamp_source']='host_receive_only'
    return data

def web_feedback(config):
    """Read-only 7-joint + XYZUVW feedback over the controller Web API (port 8010)."""
    from .web_control import Controller
    ctrl=Controller(config['controller'],config['robot_id']);ctrl.login()
    if ctrl.axis_count()!=7:raise ValueError('控制器轴数不是 7')
    degrees=ctrl.joints(7);world=ctrl.pose();model=Model(config);q=model.from_sdk(degrees)
    if not model.legal(q):raise ValueError('反馈经 SDK 映射后超出 URDF 限位，请检查轴序、符号和零位')
    return dict(joint_degrees=degrees,world_mm_deg=world,q_rad=q.tolist(),model_tcp_transform=model.fk(q).tolist(),
        sdk_mapping_verified=config['sdk_mapping_verified'],source='controller_web',host_received_monotonic=time.monotonic())

def web_start(config):
    """Plan start for the web-program path: local IK of the controller's *measured*
    TCP position (pen-vertical target), so the plan begins exactly where the arm is
    even while the local URDF is only approximately aligned (planning_only)."""
    import numpy as np
    from .web_control import Controller,settle_pose,dist3
    ctrl=Controller(config['controller'],config['robot_id']);ctrl.login()
    if ctrl.axis_count()!=7:raise ValueError('控制器轴数不是 7')
    # A mode switch (e.g. auto->manual at the end of a previous run) can move the arm for
    # about a second (15 mm dip seen 2026-10-18): plan only from a still arm.
    still=settle_pose(ctrl,n=5,tol_mm=0.05,timeout=15.0,interval=0.25)
    degrees=ctrl.joints(7);world=ctrl.pose()
    if dist3(world,still)>0.05:raise ValueError('机械臂仍在运动，请稍后再规划')
    model=Model(config)
    seed=model.from_sdk(degrees)
    from .web_executor import mapping_required
    if mapping_required(config):
        # joint mode: the plan must start from the arm's real joints (the model reproduces
        # the controller pose exactly). The planner rejects a tilted pen (START_ORIENTATION):
        # run scripts/tcb705_pen_vertical.py first.
        if not model.legal(seed):raise ValueError('当前关节超出模型限位')
        return dict(joint_degrees=degrees,world_mm_deg=world,q_rad=seed.tolist(),
            model_error_mm=float(np.linalg.norm(model.fk(seed)[:3,3]*1000-np.asarray(world[:3]))),
            source='controller_web_joints',host_received_monotonic=time.monotonic())
    if not model.legal(seed):seed=np.asarray(config['q_start_rad'],dtype=float)
    target=np.eye(4);target[:3,:3]=config['tool_rotation'];target[:3,3]=np.asarray(world[:3])/1000.
    result=model.solve(target,seed,seed)
    if not result['ok'] or not model.legal(result['q']):raise ValueError('本地模型无法从当前位置起步（IK 失败），请把机械臂移到纸面上方的常用位置')
    return dict(joint_degrees=degrees,world_mm_deg=world,q_rad=result['q'].tolist(),seed_error_mm=float(np.linalg.norm(model.fk(seed)[:3,3]-target[:3,3])*1000),
        source='controller_web_ik_start',host_received_monotonic=time.monotonic())

def web_program_enabled(config):
    return config.get('execution',{}).get('web_program',{}).get('enabled') is True

def return_home(config,simulation=False,cancel=lambda:False,progress=None):
    """复位: real motion only through the commissioned whole-program / SDK path, like execute()."""
    if simulation:
        return dict(status='DONE',physical_motion=False,simulation=True,robot_type='TCB705',kind='home')
    if not web_program_enabled(config):raise ValueError('REAL_STREAM_NOT_COMMISSIONED: 实机复位需开启 execution.web_program')
    from .web_executor import return_home as web_home
    from .sdk_motion import sdk_enabled
    if not sdk_enabled(config):
        return web_home(config,cancel=cancel,progress=progress)
    from .sdk_motion import open_client,SdkMotion
    from .web_control import Controller
    client,info=open_client(config)
    try:
        ctrl=Controller(config['controller'],config['robot_id'])
        with SdkMotion(client,ctrl,config) as motion:
            result=web_home(config,cancel=cancel,progress=progress,controller=ctrl,motion=motion)
        result['sdk']=info;return result
    finally:
        client.close()

def execute(folder,config,simulation=False,cancel=lambda:False,realtime=False,progress=None,frozen=None,prepared=None,recovery_cancel=None):
    if not simulation:
        if not web_program_enabled(config):raise ValueError('REAL_STREAM_NOT_COMMISSIONED: 实机执行需开启 execution.web_program（自动模式整程序下发）')
        from .web_executor import execute as web_execute
        from .sdk_motion import sdk_enabled
        if not sdk_enabled(config):
            return web_execute(folder,config,cancel=cancel,progress=progress,frozen=frozen,prepared=prepared,recovery_cancel=recovery_cancel)
        # 2026-10-20: motion through Huacheng SDK V2.4.1 (moveJoints/moveLine, setGlobalSpeed);
        # the Web API still provides pose/state feedback and the manual/auto switch.
        from .sdk_motion import open_client,SdkMotion
        from .web_control import Controller
        client,info=open_client(config)
        try:
            ctrl=Controller(config['controller'],config['robot_id'])
            if progress:progress(dict(event='SDK_CONNECTED',**info))
            with SdkMotion(client,ctrl,config) as motion:
                result=web_execute(folder,config,cancel=cancel,progress=progress,frozen=frozen,controller=ctrl,motion=motion,prepared=prepared,recovery_cancel=recovery_cancel)
            result['sdk']=info;return result
        finally:
            client.close()
    load(folder,config,with_rows=False)
    exe=ROOT/'build/tcb705'/('tcb_runner.exe' if sys.platform=='win32' else 'tcb_runner')
    if not exe.exists():raise ValueError('请先编译 tcb_runner')
    process=subprocess.Popen([str(exe),'--simulate-realtime' if realtime else '--simulate-fast',str(folder/'trajectory.bin')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        while process.poll() is None:
            if cancel():
                process.terminate();process.wait(timeout=3);raise ValueError('CANCELLED: 模拟执行取消')
            time.sleep(.02)
        stdout,stderr=process.communicate(timeout=3)
        if process.returncode:raise ValueError('模拟执行校验失败：'+stderr[-400:])
        result=json.loads(stdout);result['robot_type']='TCB705';return result
    finally:
        if process.poll() is None:process.kill();process.wait()
