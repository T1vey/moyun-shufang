"""Strict metric line/circle primitives with explicit paper plane and strokes."""
import math
import numpy as np
from r1a.model import finite_array


def _scalar3(value, label):
    """取出三个 Python 标量并校验有限。

    3 维向量上用 numpy 的调度开销是实际计算的数百倍 (实测 isclose 0.75 ms/次,
    cross 0.96 ms/次 @ 667 MHz Cortex-A9), 所以这些小运算一律走标量。
    """
    try:
        x=float(value[0]); y=float(value[1]); z=float(value[2])
    except (TypeError, IndexError, ValueError, KeyError):
        raise ValueError(f'{label} must be a 3-vector')
    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
        raise ValueError(f'{label} must be finite')
    return x,y,z


def _unit3(value, label):
    x,y,z=_scalar3(value,label)
    if abs(math.sqrt(x*x+y*y+z*z)-1.0)>1e-8:
        raise ValueError(f'{label} must be unit')
    return x,y,z


def unit(value, label):
    x,y,z=_unit3(value,label)
    return np.array((x,y,z))


def positive(value, label):
    v=float(value)
    if not np.isfinite(v) or v<=0: raise ValueError(f'{label} must be finite positive')
    return v


def lerp_axis(a,b,f):
    """两点轴向的球面插值 (slerp)。标量展开, 与原 numpy 实现数值等价。"""
    ax,ay,az=_unit3(a,'axis A')
    bx,by,bz=_unit3(b,'axis B')
    cx=ay*bz-az*by; cy=az*bx-ax*bz; cz=ax*by-ay*bx
    angle=math.atan2(math.sqrt(cx*cx+cy*cy+cz*cz), ax*bx+ay*by+az*bz)
    if angle>math.pi-1e-6: raise ValueError('antipodal transition requires a specified intermediate axis')
    f=float(f)
    if angle<1e-8:
        vx=(1.0-f)*ax+f*bx; vy=(1.0-f)*ay+f*by; vz=(1.0-f)*az+f*bz
    else:
        s=math.sin(angle)
        w1=math.sin((1.0-f)*angle)/s; w2=math.sin(f*angle)/s
        vx=w1*ax+w2*bx; vy=w1*ay+w2*by; vz=w1*az+w2*bz
    n=math.sqrt(vx*vx+vy*vy+vz*vz)
    return np.array((vx/n,vy/n,vz/n))


def axis_parameters(a,b):
    """Validate segment endpoints once; retain the scalar slerp angle."""
    ax,ay,az=_unit3(a,'axis A');bx,by,bz=_unit3(b,'axis B')
    cx=ay*bz-az*by;cy=az*bx-ax*bz;cz=ax*by-ay*bx
    angle=math.atan2(math.sqrt(cx*cx+cy*cy+cz*cz),ax*bx+ay*by+az*bz)
    if angle>math.pi-1e-6:
        raise ValueError('antipodal transition requires a specified intermediate axis')
    return (ax,ay,az),(bx,by,bz),angle


def interpolate_axes(starts,ends,angles,us):
    """Vectorized slerp for validated, possibly different segment endpoints."""
    linear=angles<1e-8
    values=np.empty_like(starts)
    values[linear]=(1-us[linear,None])*starts[linear]+us[linear,None]*ends[linear]
    spherical=~linear
    if spherical.any():
        t=angles[spherical];f=us[spherical];s=np.sin(t)
        values[spherical]=(np.sin((1-f)*t)/s)[:,None]*starts[spherical]+(np.sin(f*t)/s)[:,None]*ends[spherical]
    values/=np.sqrt(np.sum(values*values,axis=1))[:,None]
    return values


def line(a,b,step,cap):
    a,b=finite_array(a,(3,),'line start'),finite_array(b,(3,),'line end')
    n=max(1,int(math.ceil(np.linalg.norm(b-a)/positive(step,'step'))))
    if n+1>cap: raise ValueError('too many line samples')
    return np.linspace(a,b,n+1)


def arc(center,u,v,radius,start,sweep,step,chord,cap):
    center=finite_array(center,(3,),'center'); u,v=unit(u,'u'),unit(v,'v')
    if abs(np.dot(u,v))>1e-8: raise ValueError('arc basis not orthogonal')
    radius=positive(radius,'radius'); step=positive(step,'step'); chord=positive(chord,'chord')
    start,sweep=float(start),float(sweep)
    if not np.isfinite([start,sweep]).all() or abs(sweep)<1e-12 or abs(sweep)>2*np.pi+1e-10:
        raise ValueError('sweep must be nonzero and at most one revolution')
    sag_angle=2*np.arccos(np.clip(1-chord/radius,-1,1))
    angle=min(step/radius,sag_angle,np.pi/2)
    if angle<=0: raise ValueError('chord precision below supported range')
    n=max(1,int(math.ceil(abs(sweep)/angle)))
    if n+1>cap: raise ValueError('too many arc samples')
    t=np.linspace(start,start+sweep,n+1)
    return center+radius*(np.cos(t)[:,None]*u+np.sin(t)[:,None]*v)


def drawing_targets(spec, cfg):
    if spec.get('units')!='m_rad': raise ValueError('path requires m_rad')
    origin=finite_array(spec['plane_origin_m'],(3,),'plane origin')
    normal=unit(spec['plane_normal'],'plane normal')
    axis=unit(spec['pen_axis'],'pen axis')
    strokes=spec['strokes']
    if not isinstance(strokes,list) or not strokes: raise ValueError('empty drawing')
    cap=cfg['max_targets']; targets=[]; previous_up=None
    smooth = cfg.get('motion_profile') == 'continuous_quintic_vaj'
    def add_segment(a,b,phase,stroke):
        for p in line(a,b,cfg['max_cartesian_step_m'],cap)[1:]:
            targets.append(dict(position=p.tolist(),axis=axis.tolist(),phase=phase,stroke=stroke))
            if len(targets)>cap: raise ValueError('target budget exceeded')
    for index,stroke in enumerate(strokes):
        points=[]; provenance=[]; kinds=[]
        if not stroke.get('segments'): raise ValueError('empty stroke')
        for segment_index, segment in enumerate(stroke['segments']):
            if segment['type']=='line':
                samples=line(segment['start_m'],segment['end_m'],cfg['max_cartesian_step_m'],cap)
            elif segment['type']=='arc':
                samples=arc(segment['center_m'],segment['u'],segment['v'],segment['radius_m'],
                            segment['start_rad'],segment['sweep_rad'],cfg['max_cartesian_step_m'],cfg['arc_chord_error_m'],cap)
            else: raise ValueError('unsupported segment type')
            if np.max(np.abs((samples-origin)@normal))>cfg['plane_tolerance_m']:
                raise ValueError('drawing points are not on the declared plane')
            if points and np.linalg.norm(points[-1]-samples[0])>1e-9:
                raise ValueError('gap inside a stroke; declare another stroke')
            rows = samples if not points else samples[1:]
            points.extend(rows)
            provenance.extend([[index, segment_index]] * len(rows))
            kinds.extend(['sample'] * max(0, len(rows)-1) + ['source_vertex'])
            if len(points)>cap: raise ValueError('stroke budget exceeded')
        first,last=np.array(points[0]),np.array(points[-1])
        first_up=first+normal*cfg['lift_m']; last_up=last+normal*cfg['lift_m']
        if previous_up is None:
            targets.append(dict(position=first_up.tolist(),axis=axis.tolist(),phase='APPROACH',stroke=index))
        else:
            add_segment(previous_up,first_up,'TRAVEL',index)
        add_segment(first_up,first,'LOWER',index)
        for number, p in enumerate(points[1:], 1):
            row = dict(position=p.tolist(),axis=axis.tolist(),phase='DRAW',stroke=index)
            if smooth:
                row.update(source_segment_id=provenance[number], node_kind=kinds[number])
            targets.append(row)
        add_segment(last,last_up,'LIFT',index)
        previous_up=last_up
        if len(targets)>cap: raise ValueError('drawing budget exceeded')
    return targets
