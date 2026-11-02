"""CPU-only short-stroke geometry prototype. No controller IO or executable plan.

The existing SDK executes joint target blocks, not the C2/4-ms frame stream.
This prototype retains the original rounded joint nodes. Controller
timing/blending and the live start still need commissioning before integration.
"""
import copy
import time
import numpy as np
from .artifact import nodes_of, nodes_hash
from .collision import check_batch as check_collision_batch
from .config import digest
from .model import Model
from .planner import _plan, PHASE, PlanningError
from .web_executor import prepare_joint, settings


def rounded_sdk_nodes(nodes,copy_nodes=True):
    """Same decimal formatting + float32 conversion as build/SdkClient/sdk_server."""
    # Newly owned internal plans may opt out of copying several thousand
    # immutable coordinates. Public/research callers retain independent data.
    out=copy.deepcopy(nodes) if copy_nodes else nodes
    out['sdk_degrees']=np.asarray([
        [float('%.4f' % round(float(v),4)) for v in row]
        for row in nodes['sdk_degrees']],dtype=np.float32).astype(float).tolist()
    return out


def validate_segments(config,nodes,keep,model,cancel=lambda:False):
    """Check rounded original nodes, without generating FK verification samples.

    All planned knots must be kept. Finite values, joint limits and configured
    node collision checks remain; no intermediate pose/verticality recheck is
    performed. Linear interpolation keeps joint limits when endpoints satisfy
    them, but this does not claim an evaluated Cartesian interpolation error.
    """
    if cancel():raise PlanningError('CANCELLED: 单笔检查取消')
    q=model.from_sdk_batch(nodes['sdk_degrees'])
    if (q.ndim!=2 or q.shape[1]!=7 or len(q)<2 or not np.isfinite(q).all() or
            np.any(q<model.lower) or np.any(q>model.upper)):
        raise PlanningError('FINAL_SAMPLE_LIMIT: SDK 舍入后的关节越界')
    if list(keep)!=list(range(len(q))):
        raise PlanningError('JOINT_NODES_REQUIRED: 下发必须保留全部已规划节点')
    for start in range(0,len(q),1024):
        if cancel():raise PlanningError('CANCELLED: 单笔检查取消')
        check_collision_batch(model,q[start:start+1024])
    if cancel():raise PlanningError('CANCELLED: 单笔检查取消')
    return 0  # no generated interpolation probes


def compile_single(paths,config,q_start,cancel=lambda:False):
    """Return a non-executable measured candidate, preserving all input positions.

    It deliberately carries neither a duration nor velocity/acceleration claims:
    unlike the full planner it does not compute a C2 time law that the current
    SDK block executor would then discard. Do not send these blocks to hardware.
    """
    started=time.perf_counter()
    if cancel():raise PlanningError('CANCELLED: 单笔规划取消')
    if not paths.get('calligraphy') or len(paths.get('paths',[]))!=1:
        raise ValueError('SHORT_STROKE_ONLY: 只接受一个已定义的毛笔笔画')
    if (settings(config)['mode']!='joint' or
            config.get('execution',{}).get('sdk',{}).get('enabled') is not True):
        raise ValueError('SHORT_STROKE_SDK_ONLY: 仅供 SDK 关节点路径研究')
    candidate=_plan(paths,config,q_start,cancel,accelerator=None,_geometry_only=True)
    model=Model(config);nodes=rounded_sdk_nodes(nodes_of(candidate))
    rounded_q=model.from_sdk_batch(nodes['sdk_degrees'])
    if np.any(rounded_q<model.lower) or np.any(rounded_q>model.upper):
        raise PlanningError('FINAL_SAMPLE_LIMIT: SDK 舍入后的关节越界')
    prepared=prepare_joint(config,nodes,cancel,merge=False)
    probes=validate_segments(config,nodes,prepared.keep,model,cancel)
    if cancel():raise PlanningError('CANCELLED: 单笔规划取消')
    if time.perf_counter()-started>config['planning']['max_plan_seconds']:
        raise PlanningError('TIME_BUDGET: 单笔准备超时')
    metrics=dict(candidate['metrics'],blocks=len(prepared.keep)-1,frames=0,
                 execution_prepare_s=prepared.seconds,collision_probe_samples=probes,
                 collision_node_samples=len(nodes['sdk_degrees']),runtime_geometry_verification=False,
                 near_error_mm=prepared.error_mm[0],air_error_mm=prepared.error_mm[1])
    result=dict(schema='tcb705-short-stroke-research-v1',execution_ready=False,
        physical_authorized=False,timing_source='controller_not_commissioned',
        config_digest=digest(config),model_sha256=model.model_sha256,
        q_start_rad=np.asarray(q_start).tolist(),nodes=nodes,
        nodes_sha256=nodes_hash(nodes),keep=list(prepared.keep),metrics=metrics)
    metrics['total_s']=time.perf_counter()-started
    return result
