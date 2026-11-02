"""Offline coordinate audit and read-only captures. Never promotes verified flags."""
import json
import subprocess
import sys
import time
import numpy as np
from .config import digest
from .model import ROOT,Model,vector,transform,rpy_matrix,pose_error
from .ethernet import endpoint,inspect


def pose(raw,convention):
    if convention!='xyz_mm_uvw_deg_zyx':raise ValueError('必须明确确认 SDK 位姿为 XYZ毫米、UVW度、ZYX旋转约定')
    raw=vector(raw,6,'SDK pose');out=np.eye(4)
    out[:3,3]=raw[:3]/1000.;out[:3,:3]=rpy_matrix(np.deg2rad(raw[3:]));return out


def capture(config):
    local,remote=endpoint(config['controller']);network=inspect(config['controller'])
    executable=ROOT/'build/tcb705/tcb_commission_probe'
    if sys.platform!='linux' or not executable.is_file():raise ValueError('请先在 ZYNQ 编译 tcb_commission_probe')
    done=subprocess.run([str(executable),local,remote,str(config['controller']['port']),str(config['robot_id'])],
        capture_output=True,text=True,timeout=30)
    if done.returncode:raise ValueError('只读采集失败：'+done.stderr[-400:])
    rows=[s[9:] for s in done.stdout.splitlines() if s.startswith('TCB_JSON ')]
    if len(rows)!=1:raise ValueError('SDK 未返回唯一有效样本')
    data=json.loads(rows[0]);data['network']=network;data['config_digest']=digest(config)
    data['host_received_unix_s']=time.time();return data


def mean_transform(values):
    values=[transform(t) for t in values]
    u,_,v=np.linalg.svd(sum(t[:3,:3] for t in values))
    r=u@np.diag([1.,1.,np.linalg.det(u@v)])@v
    out=np.eye(4);out[:3,:3]=r;out[:3,3]=np.mean([t[:3,3] for t in values],axis=0);return out


def audit(config,samples,convention,base_transform=None):
    """Compare configured joint mapping against SDK FK on held-out samples.

    Fits only a constant base-frame candidate using the first half. It does not
    guess a seven-axis permutation, fit zero offsets, or approve physical TCP.
    SDK tool transforms are inferred from FK with/without the selected tool.
    """
    if len(samples)<10:raise ValueError('至少采集 10 个不同静止姿态，前半拟合基座，后半独立核对')
    model=Model(config);qrows=[];model_flange=[];sdk_flange=[];sdk_tcp=[];contexts=set()
    for sample in samples:
        if sample.get('schema')!='tcb705-static-capture-v1' or sample.get('read_only') is not True:
            raise ValueError('不是只读静态采集样本')
        if sample['robot_id']!=config['robot_id']:raise ValueError('样本机器人 ID 不一致')
        if sample.get('config_digest')!=digest(config):raise ValueError('样本与当前配置不一致，需要重新采集')
        q0=vector(sample['joint_degrees'],7,'joint degrees')
        q1=vector(sample['joint_degrees_after'],7,'joint degrees after')
        if np.max(np.abs(q1-q0))>.02:raise ValueError('采集期间关节发生移动')
        contexts.add((sample['sdk_version'],sample['host_version'],sample['tool_id'],sample['workspace_id']))
        q=model.from_sdk(q0)
        if not model.legal(q):raise ValueError('映射后的关节超出模型限位')
        qrows.append(q0);model_flange.append(model.base_inverse@model.evaluate(q)[2][-1])
        sdk_flange.append(pose(sample['fk_flange_base_raw'],convention))
        sdk_tcp.append(pose(sample['fk_tcp_base_raw'],convention))
    if len(contexts)!=1:raise ValueError('采集期间 SDK/Host/工具/工作坐标上下文变化')
    split=len(samples)//2
    # Both subsets need varied joints; repeated snapshots cannot establish a mapping.
    spread=np.minimum(np.ptp(qrows[:split],axis=0),np.ptp(qrows[split:],axis=0))
    if np.any(spread<5):raise ValueError('各轴在拟合组和核对组内均需至少 5 度变化，重复姿态不能验证映射')
    base=transform(base_transform) if base_transform is not None else mean_transform(
        [b@np.linalg.inv(a) for a,b in zip(model_flange[:split],sdk_flange[:split])])
    tcp_candidates=[np.linalg.inv(f)@t for f,t in zip(sdk_flange,sdk_tcp)]
    tcp=mean_transform(tcp_candidates[:split])
    rows=[]
    for i,(mf,sf,st) in enumerate(zip(model_flange,sdk_flange,sdk_tcp)):
        pe,ae=pose_error(base@mf,sf);te,ta=pose_error(base@mf@model.tool,st)
        ce,ca=pose_error(sf@tcp,st)
        rows.append(dict(index=i,subset='fit' if i<split else 'holdout',flange_error_mm=pe*1000,
            flange_error_deg=float(np.rad2deg(ae)),configured_tcp_error_mm=te*1000,
            configured_tcp_error_deg=float(np.rad2deg(ta)),candidate_tool_error_mm=ce*1000,
            candidate_tool_error_deg=float(np.rad2deg(ca))))
    limits={'flange_error_mm':.5,'flange_error_deg':.2,'candidate_tool_error_mm':.2,'candidate_tool_error_deg':.1}
    match=all(row[k]<=v for row in rows[split:] for k,v in limits.items())
    return dict(schema='tcb705-coordinate-audit-v1',config_digest=digest(config),
        samples=len(samples),fit_samples=split,holdout_samples=len(samples)-split,
        mapping_candidate_matches_sdk_fk=match,physical_verified=False,configured_tcp_matches_sdk=all(
            r['configured_tcp_error_mm']<=.5 and r['configured_tcp_error_deg']<=.2 for r in rows[split:]),
        T_controller_base_from_model_candidate=base.tolist(),T_flange_tcp_controller_candidate=tcp.tolist(),
        tool_id=samples[0]['tool_id'],pose_convention_assumed=convention,
        thresholds=limits,rows=rows,notes=[
        '只核对当前轴序/符号/零位候选，不自动辨识或修改。',
        'SDK 工具定义不证明它等于实际笔尖；tool_id=0 的候选通常只是法兰。',
        '默认姿态换算必须用控制器实测确认；数值匹配不自动写入已标定标志。',
        '基座候选可填写到 T_controller_base_from_model；本工具不自动应用或确认现场方向。'])


def pivot_tcp(flange_transforms):
    """Constant physical pivot fit, translation only; orientation remains unknown."""
    if len(flange_transforms)<8:raise ValueError('TCP 定点法至少需要 8 个不同方向的法兰位姿')
    frames=[transform(t) for t in flange_transforms];a=np.vstack([np.c_[t[:3,:3],-np.eye(3)] for t in frames])
    b=np.concatenate([-t[:3,3] for t in frames]);solution,_,rank,singular=np.linalg.lstsq(a,b,rcond=None)
    if rank!=6 or singular[0]/singular[-1]>100:raise ValueError('姿态变化不足或单轴旋转，TCP 定点解不可观测')
    residual=(a@solution-b).reshape(-1,3);errors=np.linalg.norm(residual,axis=1)*1000
    if np.max(errors)>.5:raise ValueError('定点残差超过 0.5 mm，请检查笔尖是否保持同一点')
    # Leave-one-out prediction prevents a small fitted residual hiding a bad sample.
    holdout=[]
    for i in range(len(frames)):
        mask=np.repeat(np.arange(len(frames))!=i,3);x,_,r,s=np.linalg.lstsq(a[mask],b[mask],rcond=None)
        if r!=6 or s[0]/s[-1]>100:raise ValueError('留一检验缺少足够独立姿态')
        holdout.append(float(np.linalg.norm(a[3*i:3*i+3]@x-b[3*i:3*i+3])*1000))
    if max(holdout)>.5:raise ValueError('TCP 留一检验超过 0.5 mm')
    return dict(schema='tcb705-pivot-tcp-v1',tcp_translation_m=solution[:3].tolist(),pivot_base_m=solution[3:].tolist(),
        max_residual_mm=float(max(errors)),max_holdout_mm=max(holdout),condition_number=float(singular[0]/singular[-1]),
        samples=len(frames),orientation_determined=False,physical_verified=False)
