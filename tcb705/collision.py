"""Conservative capsule checks. Verification status stays separate from results."""
import numpy as np

def segment_distance(a,b,c,d):
    # Closest points on finite segments, including degenerate segments.
    u,v,w=b-a,d-c,a-c
    aa,bb,cc,dd,ee=u@u,u@v,v@v,u@w,v@w
    if aa<1e-16 and cc<1e-16:return np.linalg.norm(a-c)
    if aa<1e-16:return np.linalg.norm(a-(c+np.clip(ee/cc,0,1)*v))
    if cc<1e-16:return np.linalg.norm((a+np.clip(-dd/aa,0,1)*u)-c)
    denom=aa*cc-bb*bb
    s=np.clip((bb*ee-cc*dd)/denom,0,1) if denom>1e-16 else 0.
    t=(bb*s+ee)/cc
    if t<0:t=0;s=np.clip(-dd/aa,0,1)
    elif t>1:t=1;s=np.clip((bb-dd)/aa,0,1)
    return float(np.linalg.norm(w+s*u-t*v))

def segment_box(a,b,low,high):
    lo,hi=0.,1.
    for k in range(3):
        delta=b[k]-a[k]
        if abs(delta)<1e-14:
            if a[k]<low[k] or a[k]>high[k]:return False
        else:
            t0,t1=(low[k]-a[k])/delta,(high[k]-a[k])/delta
            lo=max(lo,min(t0,t1));hi=min(hi,max(t0,t1))
            if lo>hi:return False
    return True

def frame_points_batch(model,Q):
    """Joint-frame origins + TCP for many configurations at once (numpy, no ctypes per row).
    Same chain as the native core: frame_k = frame_{k-1} @ origin_k @ Rot(axis_k, q_k);
    returns (N, 9, 3) in the controller frame, matching model.evaluate()'s frames + pose."""
    Q=np.atleast_2d(np.asarray(Q,dtype=float));n=len(Q)
    origins=model.data[:,:16].reshape(7,4,4);axes=model.data[:,16:19]
    T=np.tile(model.base,(n,1,1));pts=np.empty((n,9,3));pts[:,0]=T[:,:3,3]
    for j in range(7):
        x,y,z=axes[j];k=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
        s=np.sin(Q[:,j])[:,None,None];c=np.cos(Q[:,j])[:,None,None]
        R=np.eye(3)+s*k+(1-c)*(k@k)
        A=np.einsum('nij,jk->nik',T,origins[j])
        T=A.copy();T[:,:3,:3]=A[:,:3,:3]@R
        pts[:,j+1]=T[:,:3,3]
    pts[:,8]=(T@model.tool)[:,:3,3]
    return pts

def _segment_distance_batch(a,b,c,d):
    u,v,w=b-a,d-c,a-c
    aa=np.einsum('ij,ij->i',u,u);bb=np.einsum('ij,ij->i',u,v);cc=np.einsum('ij,ij->i',v,v)
    dd=np.einsum('ij,ij->i',u,w);ee=np.einsum('ij,ij->i',v,w)
    sa=np.where(aa<1e-16,1.,aa);sc=np.where(cc<1e-16,1.,cc)
    denom=aa*cc-bb*bb
    s=np.where(denom>1e-16,np.clip((bb*ee-cc*dd)/np.where(denom>1e-16,denom,1.),0,1),0.)
    t=(bb*s+ee)/sc
    lo,hi=t<0,t>1
    s=np.where(lo,np.clip(-dd/sa,0,1),np.where(hi,np.clip((bb-dd)/sa,0,1),s));t=np.clip(t,0,1)
    # degenerate segments, exactly as segment_distance()
    s=np.where(aa<1e-16,0.,s);t=np.where(aa<1e-16,np.clip(ee/sc,0,1),t)
    s=np.where((cc<1e-16)&(aa>=1e-16),np.clip(-dd/sa,0,1),s);t=np.where(cc<1e-16,0.,t)
    return np.linalg.norm(w+s[:,None]*u-t[:,None]*v,axis=1)

def check_batch(model,Q):
    """Vectorised check(): raises on the first colliding row (same rules and messages)."""
    cfg=model.config['collision']
    if not cfg['self_check'] and not cfg['boxes']:return
    radius=cfg['link_radius_m']
    excluded={tuple(sorted(p)) for p in cfg['excluded_pairs']};bad=None
    pairs=[(i,j) for i in range(8) for j in range(i+2,8) if (i,j) not in excluded]
    if cfg['self_check'] and pairs and getattr(model,'native_collision',False):
        # Native core: same frame points and closest-point rules, first row then first pair.
        found=model.self_collision_batch(np.atleast_2d(Q),pairs,2*radius)
        if found is not None:bad=(found[0],'SELF_COLLISION: capsules %d and %d'%pairs[found[1]])
    elif cfg['self_check'] and pairs:
        # Every capsule pair in one call; rows are processed in bounded chunks and
        # the first colliding row (then the first pair in loop order) is reported.
        pts=frame_points_batch(model,Q)
        I=np.array([p[0] for p in pairs]);J=np.array([p[1] for p in pairs])
        for first in range(0,len(pts),2048):
            chunk=pts[first:first+2048];n=len(chunk)
            seg=lambda k:chunk[:,k].transpose(1,0,2).reshape(-1,3)
            hit=(_segment_distance_batch(seg(I),seg(I+1),seg(J),seg(J+1))<2*radius).reshape(len(pairs),n)
            if hit.any():
                rows=np.where(hit.any(axis=1),hit.argmax(axis=1),n);p=int(np.argmin(rows))
                bad=(first+int(rows[p]),'SELF_COLLISION: capsules %d and %d'%pairs[p]);break
    if bad is not None:
        # report exactly what the scalar check reports for that row
        check(model,np.atleast_2d(Q)[bad[0]]);raise ValueError(bad[1])
    if cfg['boxes']:
        for row in np.atleast_2d(Q):check(model,row)

def check(model,q):
    cfg=model.config['collision']
    if not cfg['self_check'] and not cfg['boxes']:return
    pose,_,frames=model.evaluate(q);points=np.vstack((frames[:,:3,3],pose[:3,3]))
    radius=cfg['link_radius_m'];excluded={tuple(sorted(p)) for p in cfg['excluded_pairs']}
    if cfg['self_check']:
        for i in range(len(points)-1):
            for j in range(i+2,len(points)-1):
                if (i,j) in excluded:continue
                if segment_distance(points[i],points[i+1],points[j],points[j+1])<2*radius:
                    raise ValueError('SELF_COLLISION: capsules %d and %d'%(i,j))
    for box in cfg['boxes']:
        low=np.asarray(box['min_m'])-radius;high=np.asarray(box['max_m'])+radius
        for a,b in zip(points[:-1],points[1:]):
            if segment_box(a,b,low,high):raise ValueError('OBSTACLE_COLLISION: '+box.get('name','box'))
