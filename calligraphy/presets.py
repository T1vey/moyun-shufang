"""Editable module library: 50-unit, X-right/Y-down drawings, depth and feed ratios.

Ratios describe choreography, not force in newtons or calibrated line widths.
Composite strokes are continuous; radicals are ordered lists with lifts between.
"""
import copy
import hashlib
import json
import math
from functools import lru_cache

VERSION = 'brush-modules-20261021-v4'
BRUSH = dict(hair_length_mm=9.0, max_diameter_mm=2.0, ink_supply='tube')
# User-confirmed upper bound; actual compression is still calibrated per setup.
# 2026-10-26: new brush (hair 13 mm, 4 mm thick) with 6 mm of usable press.
MAX_PRESS_MM = 6.0
TOOLS = ('pen', 'brush', 'hardpen')   # 画笔 sketches, 毛笔 brush writing, 硬笔 hard-pen writing: own calibrations
TOOL_NAMES = {'pen': '画笔', 'brush': '毛笔', 'hardpen': '硬笔'}
TASK_NAMES = {'pen': '素描绘画', 'brush': '毛笔字', 'hardpen': '硬笔字'}
from .library import STROKES, RADICALS, NOTES, CATEGORY, ALIASES, ref
from .curves import sample, BrushCurve


def modules(key):
    if key in STROKES:
        return [copy.deepcopy(STROKES[key][1])]
    if key not in RADICALS:
        raise ValueError('未知书法模块')
    out=[]
    for r in RADICALS[key][1]:
        source=STROKES[r['module']][1]
        x,y,w,h=r['box']
        lo=[min(p[j] for p in source) for j in (0,1)]
        span=[max(p[j] for p in source)-lo[j] for j in (0,1)]
        chain=[]
        for px,py,d,v in source:
            nx=(px-lo[0])/span[0] if span[0] else .5
            ny=(py-lo[1])/span[1] if span[1] else .5
            if r.get('mirror_x'):nx=1-nx
            chain.append([50*(x+w*nx),50*(y+h*ny),d*r['press_scale'],min(1.,v*r['feed_scale'])])
        out.append(chain)
    return out


@lru_cache(maxsize=128)
def preview_modules(key):
    # Same curve, coarser tessellation for 66 px tiles on the Zynq WebKit display.
    # Immutable cached values prevent catalog callers from mutating preset data.
    return tuple(tuple(tuple(round(v,6) for v in p) for p in
                 BrushCurve(c).sample(step_mm=.8,tolerance_mm=.02,compression_step=.06,feed_step=.08))
                 for c in modules(key))


def catalog():
    return dict(version=VERSION, brush=BRUSH, items=[
        dict(id=k, name=v[0], group=group, stroke_count=len(modules(k)),
             category=CATEGORY[k],aliases=ALIASES.get(k,''),
             description=NOTES[k],strokes=preview_modules(k))
        for group, table in [('basic',STROKES),('radical',RADICALS)] for k,v in table.items()])


def number(v, lo, hi, name):
    if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:
        raise ValueError('%s 必须在 %g～%g 之间'%(name,lo,hi))
    return float(v)

def binding(config):
    """Changing TCP, paper, kinematic model or orientation invalidates brush verification."""
    keys=('T_flange_tcp','paper','tool_rotation','sdk_mapping','kinematics','model_corrections',
          'joint_limits_rad','T_controller_base_from_model','armvision')
    return hashlib.sha256(json.dumps({k:config.get(k) for k in keys},sort_keys=True,
                                    allow_nan=False,separators=(',',':')).encode()).hexdigest()

def profile(config, require_verified=False):
    p=config.get('calligraphy',{})
    depth=number(p.get('max_press_mm',0),0,MAX_PRESS_MM,'毛笔最大下压量')
    verified=p.get('verified') is True and p.get('calibration_binding')==binding(config)
    if require_verified and (not verified or depth<=0):
        raise ValueError('请先在书法模式中核对当前毛笔 TCP、落纸零点，并保存实测下压上限')
    # Speed is an execution setting shared with the main GUI, not a brush
    # calibration or part of the frozen geometric path.
    out=dict(BRUSH,max_press_mm=depth,verified=verified)
    if 'hair_length_mm' in p:out['hair_length_mm']=number(p['hair_length_mm'],1,60,'毛长 (mm)')
    if 'max_diameter_mm' in p:out['max_diameter_mm']=number(p['max_diameter_mm'],.5,20,'最粗直径 (mm)')
    if depth>out['hair_length_mm']:raise ValueError('毛笔下压上限不能超过毛长')
    # Brush calibration (2026-10-26): the brush tip touches the paper at its own flange Z;
    # sketches keep the ArmVision pen height. Part of the geometry, so plans follow it.
    if p.get('contact_z_mm') is not None:out['contact_z_mm']=number(p['contact_z_mm'],0,1000,'毛笔落笔 Z (mm)')
    return out

def mounted_tool(config):
    tool=config.get('mounted_tool','pen')
    if tool not in TOOLS:raise ValueError('当前工具只能是画笔、毛笔或硬笔')
    return tool

def tool_fits(tool, need):
    """画笔 and 硬笔 are the same physical pen (2026-10-27): hard-pen writing also runs with the pen mounted."""
    return tool==need or (need=='hardpen' and tool=='pen')

def tool_of(meta):
    """The tool a plan needs: its calligraphy metadata decides (None = a sketch for the pen)."""
    if not meta:return 'pen'
    return 'hardpen' if str(meta.get('schema','')).startswith('hardpen-') else 'brush'

def geometry_profile(p):
    """Accept older plans' unused speed field without changing their node hash."""
    return {k:v for k,v in p.items() if k!='speed_pct'} if isinstance(p,dict) else p

def task(key, size_mm, config):
    """Place a preset, at its requested physical size, at the centre of the calibrated paper."""
    size=number(size_mm,10,80,'模块大小')
    p=profile(config)
    W,H=float(config['paper']['width_mm']),float(config['paper']['height_mm'])
    if size+4>min(W,H):raise ValueError('模块尺寸超出纸面，请缩小；四周至少留 2 mm')
    raw=modules(key)
    allp=[pt for chain in raw for pt in chain]
    lo=[min(a[j] for a in allp) for j in (0,1)]
    hi=[max(a[j] for a in allp) for j in (0,1)]
    # Uniform scaling; depth is independent of the chosen XY size.
    scale=size/50
    off=[(W-(hi[0]-lo[0])*scale)/2-lo[0]*scale,
         (H-(hi[1]-lo[1])*scale)/2-lo[1]*scale]
    paths=[];depths=[];feeds=[]
    for chain in raw:
        dense=sample(chain,scale)
        paths.append([[round(a[0]*scale+off[0],6),round(a[1]*scale+off[1],6)] for a in dense])
        depths.append([a[2]*p['max_press_mm'] for a in dense])
        feeds.append([a[3] for a in dense])
    meta=dict(schema='brush-preset-v1',module=key,version=VERSION,brush=p,
              depth_mm=depths,feed_ratio=feeds,size_mm=size)
    return dict(units='mm',width_mm=W,height_mm=H,coordinate_system='full_canvas_xy_down',
                paths=paths,calligraphy=meta)

def validate_task(paths, config):
    m=paths.get('calligraphy')
    if not isinstance(m,dict) or m.get('schema') not in ('brush-preset-v1','brush-text-v1','brush-handwriting-v1','brush-couplet-v1','brush-poem-v1','hardpen-text-v1','hardpen-doc-v1'):
        raise ValueError('书法轨迹格式错误')
    # Both formats are reconstructed on the server, never trust uploaded paths.
    if m['schema']=='brush-handwriting-v1':
        from handwriting.placement import task as handwriting_task
        expected=handwriting_task(m.get('module'),m.get('raw_points'),m.get('size_mm'),config)
    elif m['schema']=='brush-text-v1':
        from .composer import task as text_task
        expected=text_task(m.get('text'),m.get('font_size_mm'),m.get('page_index'),config,m.get('style','kai'),column=m.get('column'))
    elif m['schema']=='brush-poem-v1':
        from .poems import task as poem_task
        expected=poem_task(m.get('poem_id'),m.get('font_size_mm'),m.get('page_index'),m.get('segment_index'),config)
    elif m['schema']=='hardpen-text-v1':
        from .hardpen import task as hardpen_task
        expected=hardpen_task(m.get('text'),m.get('font_size_mm'),config)
    elif m['schema']=='hardpen-doc-v1':
        from .hardpen import unit_task
        expected=unit_task(m.get('text'),m.get('font_size_mm'),m.get('layout'),m.get('unit_index'),config)
    elif m['schema']=='brush-couplet-v1':
        from .couplets import task as couplet_task
        expected=couplet_task(m.get('couplet_id'),m.get('page_index'),config)
    else:
        expected=task(m.get('module'),m.get('size_mm'),config)
    # Comparison is read-only; copy only the dictionaries whose legacy speed
    # metadata is normalized, not every point of the complete stroke again.
    candidate=dict(paths)
    candidate['calligraphy']=dict(m,brush=geometry_profile(m.get('brush')))
    if expected!=candidate:
        raise ValueError('书法模块参数或毛笔标定已变化，请重新生成')
    return m

def preview_svg(key):
    """Illustrative width follows pressure ratio, never represented as calibrated ink width."""
    chains=preview_modules(key);p=[pt for c in chains for pt in c]
    x0=min(a[0] for a in p)-5;y0=min(a[1] for a in p)-5
    w=max(20,max(a[0] for a in p)-x0+5);h=max(20,max(a[1] for a in p)-y0+5)
    lines=[]
    for c in chains:
        if len(c)<2:continue
        for a,b in zip(c,c[1:]):
            d=(a[2]+b[2])/2
            lines.append('<path d="M %.6f %.6f L %.6f %.6f" stroke-width="%.2f" stroke-opacity="%.2f"/>'%
                         (a[0],a[1],b[0],b[1],.4+3.4*d,.38+.62*d))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%g %g %g %g">'
            '<g fill="none" stroke="#e8a84a" stroke-linecap="round" stroke-linejoin="round">%s</g></svg>'%
            (x0,y0,w,h,''.join(lines))).encode()
