"""Atomic frozen plan, bounded little-endian trajectory, SHA256 integrity."""
import hashlib
import json
import os
from pathlib import Path
import struct
import zlib
import numpy as np
from .config import digest,validate
from .model import Model

RECORD=np.dtype([('t','<f8'),('q','<f4',(7,)),('phase','<u4'),('stroke','<i4')])
HEADER=struct.Struct('<8sIIIII')

def atomic_write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    with tmp.open('wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    os.replace(str(tmp),str(path))

def simplify(points,tol=.02):
    """Ramer-Douglas-Peucker (mm). The preview holds one point per 4 ms frame (166k for an 11 min
    drawing, a 2.3 MB SVG that froze the board's software-rendered WebKit); 0.02 mm is invisible
    at the 0.65 mm stroke width. Only the picture is simplified, never the plan."""
    a=np.asarray(points,dtype=float)
    if len(a)<3:return a
    keep=np.zeros(len(a),bool);keep[0]=keep[-1]=True;stack=[(0,len(a)-1)]
    while stack:
        i,j=stack.pop()
        if j-i<2:continue
        d=a[j]-a[i];n=np.hypot(*d);r=a[i+1:j]-a[i]
        dist=np.abs(d[0]*r[:,1]-d[1]*r[:,0])/n if n>1e-12 else np.hypot(r[:,0],r[:,1])
        k=int(np.argmax(dist))
        if dist[k]>tol:k+=i+1;keep[k]=True;stack+=[(i,k),(k,j)]
    return a[keep]

def preview_svg(preview):
    w,h=float(preview['width_mm']),float(preview['height_mm'])
    lines=[]
    for path in preview['paths']:
        if len(path)<2:continue
        points=' '.join('%.3f,%.3f'%(x,h-y) for x,y in simplify(path))
        lines.append('<polyline points="'+points+'"/>')
    return ('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="-2 -2 %.5f %.5f" aria-label="天链七轴最终轨迹预测图">
<defs><linearGradient id="amber" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffe2a6"/><stop offset=".5" stop-color="#f3ad45"/><stop offset="1" stop-color="#d9861f"/></linearGradient></defs>
<g fill="none" stroke="url(#amber)" stroke-width=".65" stroke-linecap="round" stroke-linejoin="round">%s</g></svg>'''%(w+4,h+4,''.join(lines))).encode()

def nodes_of(plan):
    """Geometric nodes (model frame, m) + their IK joints: input of the web-program executor."""
    model=Model(plan['config'])
    nodes=dict(schema='tcb705-nodes-v1',positions_m=np.asarray(plan['geometric_positions']).tolist(),
        sdk_degrees=model.to_sdk_batch(plan['node_q_rad']).tolist(),
        interval_phase=np.asarray(plan['interval_phase']).astype(int).tolist(),
        interval_stroke=np.asarray(plan['node_stroke_ids']).astype(int).tolist(),stops=[int(i) for i in plan['node_stops']])
    if 'calligraphy' in plan:
        nodes['calligraphy']=plan['calligraphy']
        nodes['interval_feed_ratio']=list(plan['interval_feed_ratio'])
    return nodes

def nodes_hash(nodes):
    return hashlib.sha256(json.dumps(nodes,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()

def check_brush_nodes(nodes, config):
    if 'calligraphy' not in nodes:return
    from calligraphy.presets import profile,geometry_profile,VERSION
    meta=nodes['calligraphy']
    if str(meta.get('schema','')).startswith('hardpen-'):
        from calligraphy import hardpen
        if meta.get('version')!=hardpen.VERSION or geometry_profile(meta.get('brush'))!=hardpen.profile(config):
            raise ValueError('硬笔参数或模块版本已变化，请重新规划')
        if meta.get('revision')!=hardpen.revision(config):raise ValueError('硬笔字库或标定已更新，请重新规划')
    elif meta.get('version')!=VERSION or geometry_profile(meta.get('brush'))!=profile(config):
        raise ValueError('毛笔参数或模块版本已变化，请重新规划')
    if meta.get('schema')=='brush-text-v1':
        from calligraphy.composer import revision
        if meta.get('revision')!=revision(config,meta.get('style','kai')):raise ValueError('汉字字库、排版或标定已更新，请重新规划')
    if meta.get('schema')=='brush-poem-v1':
        from calligraphy.poems import revision as poem_revision
        if meta.get('revision')!=poem_revision(config):raise ValueError('诗词库、字库或标定已更新，请重新规划')
    if meta.get('schema')=='brush-couplet-v1':
        from calligraphy.couplets import revision as couplet_revision
        if meta.get('revision')!=couplet_revision(config):raise ValueError('春联库、排版或春联台面已更新，请重新规划')
    r=np.asarray(nodes.get('interval_feed_ratio'),dtype=float)
    if r.shape!=(len(nodes['positions_m'])-1,) or not np.isfinite(r).all() or np.any((r<=0)|(r>1)):
        raise ValueError('书法分段速度无效')

def freeze(plan,mode):
    """(doc, nodes) kept in memory instead of plan files (real mode, 2026-10-18): the same
    values save() + load() + load_nodes() give, without writing the SD card."""
    if plan.get('schema')!='tcb705-plan-v1':raise ValueError('Cannot execute a geometric research candidate')
    doc={k:plan[k] for k in ('schema','config_digest','model_sha256','config','q_start_rad','metrics','period_s','preview')}
    nodes=nodes_of(plan)
    doc.update(mode=mode,physical_authorized=False,in_memory=True,nodes_count=len(nodes['positions_m']))
    if 'calligraphy' in nodes:doc['brush_nodes_sha256']=nodes_hash(nodes)
    return doc,nodes

def check_frozen(doc,nodes,current_config):
    """load()'s configuration/model checks for an in-memory plan, plus load_nodes()' format check."""
    if doc.get('schema')!='tcb705-plan-v1':raise ValueError('plan schema mismatch')
    if digest(current_config)!=doc['config_digest']:raise ValueError('标定或限制已改变，请重新规划')
    if Model(doc['config']).model_sha256!=doc['model_sha256']:raise ValueError('URDF changed; replan required')
    n=len(nodes['positions_m'])
    if nodes.get('schema')!='tcb705-nodes-v1' or n<2 or len(nodes['sdk_degrees'])!=n or len(nodes['interval_phase'])!=n-1 or len(nodes['interval_stroke'])!=n-1:
        raise ValueError('规划节点格式错误')
    if doc.get('brush_nodes_sha256') or 'calligraphy' in nodes:
        if doc.get('brush_nodes_sha256')!=nodes_hash(nodes):raise ValueError('书法执行节点摘要不一致')
        check_brush_nodes(nodes,current_config)

def save(plan,folder,mode):
    if plan.get('schema')!='tcb705-plan-v1':raise ValueError('Cannot save a geometric research candidate as a timed plan')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    rows=np.zeros(len(plan['times']),dtype=RECORD);rows['t']=plan['times'];rows['q']=plan['sdk_degrees'];rows['phase']=plan['phase'];rows['stroke']=plan['stroke_ids']
    body=rows.tobytes();raw=HEADER.pack(b'TCBPLAN1',1,7,len(rows),RECORD.itemsize,zlib.crc32(body))+body
    atomic_write(folder/'trajectory.bin',raw)
    public={k:plan[k] for k in ('schema','config_digest','model_sha256','config','q_start_rad','metrics','period_s','preview')}
    public.update(mode=mode,trajectory_sha256=hashlib.sha256(raw).hexdigest(),trajectory_bytes=len(raw),physical_authorized=False)
    if 'node_q_rad' in plan:
        nodes=nodes_of(plan)
        nraw=json.dumps(nodes,allow_nan=False,separators=(',',':')).encode()
        atomic_write(folder/'nodes.json',nraw)
        public.update(nodes_sha256=hashlib.sha256(nraw).hexdigest(),nodes_count=len(nodes['positions_m']))
    # Portrait jobs display their returned cloud/source image in the user GUI.
    # They no longer synthesize a trajectory picture or write an empty SVG.
    if plan['preview'].get('source')!='cloud':
        atomic_write(folder/'preview.svg',preview_svg(plan['preview']))
    atomic_write(folder/'plan.json',json.dumps(public,ensure_ascii=False,allow_nan=False,indent=2).encode())
    return public

def load(folder,current_config=None,with_rows=True):
    folder=Path(folder);doc=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    if doc.get('schema')!='tcb705-plan-v1':raise ValueError('plan schema mismatch')
    validate(doc['config'])
    if digest(doc['config'])!=doc['config_digest']:raise ValueError('frozen configuration changed')
    if current_config is not None and digest(current_config)!=doc['config_digest']:raise ValueError('标定或限制已改变，请重新规划')
    model=Model(doc['config'])
    if model.model_sha256!=doc['model_sha256']:raise ValueError('URDF changed; replan required')
    path=folder/'trajectory.bin'
    if path.stat().st_size>HEADER.size+750000*RECORD.itemsize:raise ValueError('trajectory size limit')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=doc['trajectory_sha256'] or len(raw)!=doc['trajectory_bytes']:raise ValueError('trajectory SHA256 mismatch')
    if len(raw)<HEADER.size:raise ValueError('trajectory header truncated')
    magic,version,dof,count,size,crc=HEADER.unpack(raw[:HEADER.size]);body=raw[HEADER.size:]
    if (magic!=b'TCBPLAN1' or version!=1 or dof!=7 or size!=RECORD.itemsize or count<2 or count>750000 or len(body)!=count*size or zlib.crc32(body)!=crc):raise ValueError('invalid trajectory format')
    rows=np.frombuffer(body,dtype=RECORD)
    if not np.isfinite(rows['t']).all() or not np.isfinite(rows['q']).all() or rows['t'][0]!=0 or np.any(np.diff(rows['t'])<=0) or np.any(rows['phase']>5):raise ValueError('invalid trajectory data')
    delta=np.diff(rows['t']);period=doc['period_s']
    if period!=doc['config']['planning']['period_s'] or count>doc['config']['planning'].get('max_frames',150000):raise ValueError('trajectory configuration mismatch')
    if np.any(delta>period+1e-8) or np.any(np.abs(delta[:-1]-period)>1e-8):raise ValueError('invalid sampling period')
    q=np.empty((count,7));q[:,model.order]=rows['q'].astype(float)*np.pi/180*model.sign+model.offset
    if np.any(q<model.lower) or np.any(q>model.upper):raise ValueError('trajectory joint limit')
    if np.max(np.abs(q[0]-np.asarray(doc['q_start_rad'])))>2e-6:raise ValueError('start pose mismatch')
    return (doc,rows) if with_rows else doc

def load_nodes(folder,doc):
    folder=Path(folder);raw=(folder/'nodes.json').read_bytes()
    if 'nodes_sha256' not in doc or hashlib.sha256(raw).hexdigest()!=doc['nodes_sha256']:raise ValueError('规划节点缺失或 SHA256 不一致，请重新规划')
    nodes=json.loads(raw)
    n=len(nodes['positions_m'])
    if nodes.get('schema')!='tcb705-nodes-v1' or n<2 or len(nodes['sdk_degrees'])!=n or len(nodes['interval_phase'])!=n-1 or len(nodes['interval_stroke'])!=n-1:
        raise ValueError('规划节点格式错误')
    check_brush_nodes(nodes,doc['config'])
    return nodes
