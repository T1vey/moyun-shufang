"""CPU-only compiler for the current SDK joint-block execution contract.

Unlike short_stroke's research artifact, this is an internal session value,
never accepted from an HTTP client or the general frozen-plan API. It retains
rounded targets without repeated FK checks of their joint interpolation.
The SDK/controller owns interpolation timing; no 4 ms time law is claimed.
"""
from dataclasses import dataclass
import time
import numpy as np
from tcb705.planner import _plan
from tcb705.artifact import nodes_hash
from tcb705.config import digest
from tcb705.short_stroke import rounded_sdk_nodes, validate_segments
from tcb705.web_executor import prepare_joint
from .placement import task

@dataclass
class StrokePlan:
    nodes: dict
    prepared: object
    q_start: object
    q_end: object
    config_digest: str
    predecessor: str
    fingerprint: str
    metrics: dict

def compile_stroke(match, raw, size, config, model, q_start, predecessor, cancel):
    start=time.perf_counter()
    paths=task(match['module'],raw,size,config)
    result=_plan(paths,config,q_start,cancel,accelerator=None,_geometry_only=True,
                 _model=model,_hover_finish=True)
    nodes=rounded_sdk_nodes(dict(schema='tcb705-nodes-v1',
        positions_m=result['geometric_positions'].tolist(),
        sdk_degrees=model.to_sdk_batch(result['node_q_rad']).tolist(),
        interval_phase=result['interval_phase'].astype(int).tolist(),
        interval_stroke=result['node_stroke_ids'].astype(int).tolist(),
        stops=list(result['node_stops']),calligraphy=result['calligraphy'],
        interval_feed_ratio=result['interval_feed_ratio']),copy_nodes=False)
    # Merge knots like brush pages (<=0.02 mm, FK re-checked): a 60 mm stroke was
    # ~500 stop-and-go moves of 0.25 mm, so the arm never reached the set speed.
    prepared=prepare_joint(config,nodes,cancel,merge=True)
    keep=list(prepared.keep);count=len(nodes['sdk_degrees'])
    if not keep or keep[0]!=0 or keep[-1]!=count-1 or any(b<=a for a,b in zip(keep,keep[1:])):
        raise ValueError('手写合并节点无效')
    # Limits and collision on every planned knot; merged blocks were FK-checked above.
    probes=validate_segments(config,nodes,list(range(count)),model,cancel)
    if cancel():raise ValueError('CANCELLED')
    q_end=model.from_sdk(nodes['sdk_degrees'][-1])
    metrics=dict(result['metrics'],planning_ms=round((time.perf_counter()-start)*1000,2),
                 blocks=len(prepared.keep)-1,collision_probes=probes,
                 collision_node_samples=len(nodes['sdk_degrees']),runtime_geometry_verification=False,
                 near_error_mm=prepared.error_mm[0],air_error_mm=prepared.error_mm[1],
                 backend='CPU_NATIVE',timing_source='controller_joint_interpolation')
    return StrokePlan(nodes,prepared,np.asarray(q_start).copy(),q_end,digest(config),
                      predecessor,nodes_hash(nodes),metrics)
