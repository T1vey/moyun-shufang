"""Bounded C1 brush curves, sampled for the existing joint planner (no SciPy).

Each channel uses shape-preserving cubic Hermite slopes. Thus an extremum in
compression/feed cannot overshoot the authored range. Parameter continuity is
not a claim of continuous physical controller velocity.
"""
import math
from functools import lru_cache


def slopes(t, values):
    h=[b-a for a,b in zip(t,t[1:])]
    delta=[(b-a)/dt for a,b,dt in zip(values,values[1:],h)]
    if len(values)==2:return [delta[0],delta[0]]
    m=[0.]*len(values)
    for i in range(1,len(values)-1):
        before,after=delta[i-1],delta[i]
        if before*after>0:
            w1=2*h[i]+h[i-1];w2=h[i]+2*h[i-1]
            m[i]=(w1+w2)/(w1/before+w2/after)
    def endpoint(h0,h1,d0,d1):
        v=((2*h0+h1)*d0-h0*d1)/(h0+h1)
        if v*d0<=0:return 0.
        if d0*d1<=0 and abs(v)>3*abs(d0):return 3*d0
        return v
    m[0]=endpoint(h[0],h[1],delta[0],delta[1])
    m[-1]=endpoint(h[-1],h[-2],delta[-1],delta[-2])
    return m


class BrushCurve:
    def __init__(self,points):
        if len(points)<2:raise ValueError('笔画至少需要两个关键帧')
        self.points=[list(map(float,p)) for p in points]
        for p in self.points:
            if len(p)!=4 or not all(math.isfinite(x) for x in p):raise ValueError('书法关键帧无效')
            if not 0<=p[2]<=1 or not 0<p[3]<=1:raise ValueError('提按或速度比例越界')
        self.t=[0.]
        for a,b in zip(self.points,self.points[1:]):
            # A stationary XY pressure release must still have a non-zero span.
            span=max(math.hypot(b[0]-a[0],b[1]-a[1]),2*abs(b[2]-a[2]),abs(b[3]-a[3]),.01)
            self.t.append(self.t[-1]+span)
        channels=[slopes(self.t,[p[j] for p in self.points]) for j in range(4)]
        # Ease contact and release without introducing a pressure/feed jump.
        for j in (2,3):channels[j][0]=channels[j][-1]=0.
        self.tangents=list(map(list,zip(*channels)))

    def at(self,index,u):
        if u<=0:return self.points[index].copy()
        if u>=1:return self.points[index+1].copy()
        a,b=self.points[index:index+2];ma,mb=self.tangents[index:index+2]
        h=self.t[index+1]-self.t[index]
        u2=u*u;u3=u2*u
        return [(2*u3-3*u2+1)*x+(u3-2*u2+u)*h*dx+(-2*u3+3*u2)*y+(u3-u2)*h*dy
                for x,y,dx,dy in zip(a,b,ma,mb)]

    def derivative(self,index,u):
        """Derivative with respect to the segment-local u parameter."""
        a,b=self.points[index:index+2];ma,mb=self.tangents[index:index+2]
        h=self.t[index+1]-self.t[index];u2=u*u
        return [(6*u2-6*u)*x+(3*u2-4*u+1)*h*dx+(-6*u2+6*u)*y+(3*u2-2*u)*h*dy
                for x,y,dx,dy in zip(a,b,ma,mb)]

    def sample(self,scale=1.,step_mm=.35,tolerance_mm=.006,compression_step=.035,feed_step=.04):
        if not math.isfinite(scale) or scale<=0:raise ValueError('无效的笔画缩放')
        out=[self.points[0].copy()]
        def subdivide(index,lo,hi,a,b,level):
            da=self.derivative(index,lo);db=self.derivative(index,hi);span=hi-lo
            # The difference from the chord is a cubic Bezier with zero endpoints.
            # Its two interior control vectors bound the entire error by convexity,
            # including extrema that midpoint-only probing could miss.
            e1=[(span*da[j]-(b[j]-a[j]))/3 for j in (0,1)]
            e2=[((b[j]-a[j])-span*db[j])/3 for j in (0,1)]
            chord_error=max(math.hypot(*e1),math.hypot(*e2))*scale
            acceptable=(math.hypot(b[0]-a[0],b[1]-a[1])*scale<=step_mm and
                        chord_error<=tolerance_mm and abs(b[2]-a[2])<=compression_step and abs(b[3]-a[3])<=feed_step)
            if acceptable:
                out.append(b);return
            if level>=20:raise ValueError('书法曲线细分超过预算')
            mid=(lo+hi)/2;p=self.at(index,mid)
            subdivide(index,lo,mid,a,p,level+1);subdivide(index,mid,hi,p,b,level+1)
        for i,(a,b) in enumerate(zip(self.points,self.points[1:])):
            subdivide(i,0.,1.,a,b,0)
        return out


@lru_cache(maxsize=64)
def _sample_template(points,scale):
    # Cache immutable geometry, not IK or execution plans. The full key includes
    # all pressure/feed control points and scale, so edited templates invalidate.
    return tuple(tuple(p) for p in BrushCurve(points).sample(scale))


def sample(points,scale=1.):
    # Return independent lists: a caller cannot corrupt a later request's curve.
    return [list(p) for p in _sample_template(tuple(tuple(p) for p in points),scale)]
