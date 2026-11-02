// General 7R serial chain. SI units, row-major transforms, no vendor dependency.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C" __attribute__((visibility("default")))
#endif
#include "math7.hpp"
#include "extrema.hpp"
#if defined(__linux__) && defined(_REENTRANT)
#include <thread>
#define TCB_THREADS 1
#endif
// Rows are independent, so splitting them over the Zynq's two A9 cores changes no result.
template<class F> static void for_rows(int count,F fn){
#ifdef TCB_THREADS
    if(count>=2048){std::thread other([&]{fn(count/2,count);});fn(0,count/2);other.join();return;}
#endif
    fn(0,count);
}
API int tcb_abi_version(){return 2;}
API int tcb_extrema_batch(const double*c,double*out,int count){
    if(count<1||count>1024||!c||!out||!finite(c,count*42))return -1;
    for(int row=0;row<count;row++)for(int joint=0;joint<7;joint++){
        double d[6];for(int k=0;k<6;k++)d[k]=c[row*42+k*7+joint];
        for(int order=0;order<4;order++){
            double result[3];bounds(d,5-order,result);
            for(int k=0;k<3;k++)out[(row*4+order)*21+k*7+joint]=result[k];
            for(int k=0;k<5-order;k++)d[k]=(k+1)*d[k+1];
        }
    }
    return finite(out,count*84)?0:-1;
}
API int tcb_fk(const double*m,const double*q,const double*tool,double*out,double*j,double*frames){
    if(!m||!q||!tool||!out||!finite(m,147)||!finite(q,7)||!finite(tool,16))return -1;
    M t=fk(m,q,tool,j,frames);std::copy(t.begin(),t.end(),out);return 0;
}
// Pose-only FK for batch verification. Same chain, same summation order as
// mul()/rot(); the fixed bottom row [0 0 0 1] of rigid transforms is not
// multiplied out (those terms only add +-0), so results equal fk() up to the
// sign of exact zeros. Single-pose FK, Jacobian and IK keep math7.hpp.
static void mul_rigid(const double*a,const double*b,double*c){
    for(int i=0;i<3;i++){
        const double*r=a+i*4;
        for(int j=0;j<3;j++)c[i*4+j]=((0.+r[0]*b[j])+r[1]*b[4+j])+r[2]*b[8+j];
        c[i*4+3]=(((0.+r[0]*b[3])+r[1]*b[7])+r[2]*b[11])+r[3];
    }
    c[12]=c[13]=c[14]=0;c[15]=1;
}
static void mul_rotation(const double*a,const double*b,double*c){
    for(int i=0;i<3;i++){
        const double*r=a+i*4;
        for(int j=0;j<3;j++)c[i*4+j]=((0.+r[0]*b[j])+r[1]*b[4+j])+r[2]*b[8+j];
        c[i*4+3]=r[3];
    }
    c[12]=c[13]=c[14]=0;c[15]=1;
}
static void fk_pose(const double*m,const double*q,const double*tool,double*out){
    double t[16],u[16];M r;
    std::copy(m,m+16,t);
    for(int k=0;k<7;k++){
        if(k){mul_rigid(t,m+21*k,u);std::copy(u,u+16,t);}
        r=rot(V{{m[k*21+16],m[k*21+17],m[k*21+18]}},q[k]);mul_rotation(t,r.data(),u);std::copy(u,u+16,t);
    }
    mul_rigid(t,tool,out);
}
API int tcb_fk_batch(const double*m,const double*q,const double*tool,double*out,int count){
    if(count<0||count>1000000||!m||!q||!tool||!out||!finite(m,147)||!finite(tool,16)||!finite(q,count*7))return -1;
    auto rigid=[](const double*t){return t[12]==0&&t[13]==0&&t[14]==0&&t[15]==1;};
    bool exact=rigid(tool);for(int k=0;k<7;k++)exact=exact&&rigid(m+21*k);
    for_rows(count,[&](int lo,int hi){
        for(int i=lo;i<hi;i++){
            if(exact)fk_pose(m,q+i*7,tool,out+i*16);
            else{M t=fk(m,q+i*7,tool);std::copy(t.begin(),t.end(),out+i*16);}
        }
    });
    return 0;
}

// Execution preparation: the same greedy candidates and probes as web_executor.py,
// evaluated without allocating numpy arrays / crossing ctypes for every candidate.
// Inputs are model radians and controller-world millimetres. Never sends commands.
static void lerp_world(const double*m,const double*tool,const double*base,
                       const double*a,const double*b,double f,double*p){
    double q[7],pose[16];
    for(int k=0;k<7;k++)q[k]=a[k]*(1.-f)+b[k]*f;
    fk_pose(m,q,tool,pose);
    for(int k=0;k<3;k++)
        p[k]=(((base[k*4]*pose[3]+base[k*4+1]*pose[7])+base[k*4+2]*pose[11])+base[k*4+3])*1000.;
}
static double point_distance(const double*a,const double*b){
    double x=a[0]-b[0],y=a[1]-b[1],z=a[2]-b[2];
    return std::sqrt((x*x+y*y)+z*z);
}
static double poly_distance(const double*p,const double*mm,int a,int b){
    double best=std::numeric_limits<double>::infinity();
    for(int i=a;i<b;i++){
        const double*u=mm+i*3;const double*v=u+3;
        double d[3],r[3];for(int k=0;k<3;k++){d[k]=v[k]-u[k];r[k]=p[k]-u[k];}
        double n=std::max((d[0]*d[0]+d[1]*d[1])+d[2]*d[2],1e-18);
        double t=std::max(0.,std::min(1.,((r[0]*d[0]+r[1]*d[1])+r[2]*d[2])/n));
        double closest[3];for(int k=0;k<3;k++)closest[k]=u[k]+t*d[k];
        best=std::min(best,point_distance(p,closest));
    }
    return best;
}
static bool preparation_input(const double*m,const double*tool,const double*base,
                              const double*q,const double*mm,int n){
    return n>=2&&n<=1000000&&m&&tool&&base&&q&&mm&&
        finite(m,147)&&finite(tool,16)&&finite(base,16)&&finite(q,n*7)&&finite(mm,n*3);
}
API int tcb_joint_merge(const double*m,const double*tool,const double*base,const double*q,
                        const double*mm,const double*arc,const int*phase,const int*stops,
                        const int*near,int n,double near_tol,double air_tol,double max_mm,int*keep){
    if(!preparation_input(m,tool,base,q,mm,n)||!arc||!phase||!stops||!near||!keep||
       !finite(arc,n)||!std::isfinite(near_tol)||!std::isfinite(air_tol)||
       !std::isfinite(max_mm)||near_tol<0||air_tol<0||max_mm<=0)return -1;
    int count=1,a=0;keep[0]=0;
    while(a<n-1){
        double tol=near[a]?near_tol:air_tol;int j=a+1;
        while(j+1<n&&phase[j]==phase[a]&&!stops[j]&&arc[j+1]-arc[a]<=max_mm){
            int c=j+1;bool ok=true;double p[3];
            for(int i=a+1;i<c;i++){
                double f=(arc[i]-arc[a])/std::max(arc[c]-arc[a],1e-12);
                lerp_world(m,tool,base,q+a*7,q+c*7,f,p);
                if(point_distance(p,mm+i*3)>tol){ok=false;break;}
            }
            for(int k=1;k<8&&ok;k++){
                lerp_world(m,tool,base,q+a*7,q+c*7,k/8.,p);
                if(poly_distance(p,mm,a,c)>tol)ok=false;
            }
            if(!ok)break;
            j=c;
        }
        keep[count++]=j;a=j;
    }
    return count;
}
API int tcb_joint_block_error(const double*m,const double*tool,const double*base,const double*q,
                              const double*mm,const int*near,int n,const int*keep,int count,
                              int probes,double*out){
    if(!preparation_input(m,tool,base,q,mm,n)||!near||!keep||!out||
       count<2||count>n||probes<2||probes>4096||keep[0]!=0||keep[count-1]!=n-1)return -1;
    out[0]=out[1]=0.;
    for(int i=1;i<count;i++){
        int a=keep[i-1],b=keep[i];
        if(a<0||b>=n||b<=a)return -1;
        for(int k=1;k<probes;k++){
            double p[3];lerp_world(m,tool,base,q+a*7,q+b*7,k*(1./probes),p);
            double d=poly_distance(p,mm,a,b);int slot=near[a]?0:1;
            out[slot]=std::max(out[slot],d);
        }
    }
    return 0;
}

// Capsule self-collision for many configurations (collision.check_batch). Same frame points as
// collision.frame_points_batch (model frame; distances are invariant under the rigid base
// transform) and the same closest-point rules as collision._segment_distance_batch, including
// degenerate segments. Returns the first colliding row (then first pair in the given order),
// -1 when none collide, -2 on invalid input. Measured 2026-10-18: this check was 9.3 s of a
// 29 s plan on the board in numpy.
static double dot3(const double*a,const double*b){return (a[0]*b[0]+a[1]*b[1])+a[2]*b[2];}
static double clip01(double x){return x<0?0:(x>1?1:x);}
static double segment_distance(const double*a,const double*b,const double*c,const double*d){
    double u[3],v[3],w[3];
    for(int k=0;k<3;k++){u[k]=b[k]-a[k];v[k]=d[k]-c[k];w[k]=a[k]-c[k];}
    const double aa=dot3(u,u),bb=dot3(u,v),cc=dot3(v,v),dd=dot3(u,w),ee=dot3(v,w);
    const double sa=aa<1e-16?1.:aa,sc=cc<1e-16?1.:cc,denom=aa*cc-bb*bb;
    double s=denom>1e-16?clip01((bb*ee-cc*dd)/denom):0.;
    double t=(bb*s+ee)/sc;
    if(t<0)s=clip01(-dd/sa);else if(t>1)s=clip01((bb-dd)/sa);
    t=clip01(t);
    if(aa<1e-16){s=0.;t=clip01(ee/sc);}
    if(cc<1e-16&&aa>=1e-16)s=clip01(-dd/sa);
    if(cc<1e-16)t=0.;
    double r[3];for(int k=0;k<3;k++)r[k]=w[k]+s*u[k]-t*v[k];
    return std::sqrt(dot3(r,r));
}
API int tcb_self_collision_batch(const double*m,const double*q,const double*tool,const int*pi,const int*pj,
                                 int pairs,double limit,int count,int*hit_pair){
    if(count<0||count>1000000||pairs<0||pairs>64||!m||!q||!tool||!hit_pair||(pairs&&(!pi||!pj))||
       !finite(m,147)||!finite(tool,16)||!finite(q,count*7)||!std::isfinite(limit))return -2;
    for(int p=0;p<pairs;p++)if(pi[p]<0||pj[p]>7||pi[p]>=pj[p])return -2;
    auto rigid=[](const double*t){return t[12]==0&&t[13]==0&&t[14]==0&&t[15]==1;};
    bool exact=rigid(tool);for(int k=0;k<7;k++)exact=exact&&rigid(m+21*k);
    if(!exact)return -2;
    // first colliding row of each half; the earlier row (then its first pair) wins, as serially
    int found[2]={-1,-1},pair[2]={-1,-1};
    for_rows(count,[&](int lo,int hi){
    const int part=lo?1:0;
    double t[16],u[16],pts[9][3];M r;
    for(int row=lo;row<hi;row++){
        const double*qq=q+row*7;
        pts[0][0]=pts[0][1]=pts[0][2]=0;
        std::copy(m,m+16,t);
        for(int k=0;k<7;k++){
            if(k){mul_rigid(t,m+21*k,u);std::copy(u,u+16,t);}
            pts[k+1][0]=t[3];pts[k+1][1]=t[7];pts[k+1][2]=t[11];
            r=rot(V{{m[k*21+16],m[k*21+17],m[k*21+18]}},qq[k]);mul_rotation(t,r.data(),u);std::copy(u,u+16,t);
        }
        mul_rigid(t,tool,u);pts[8][0]=u[3];pts[8][1]=u[7];pts[8][2]=u[11];
        for(int p=0;p<pairs;p++){
            const int i=pi[p],j=pj[p];
            if(segment_distance(pts[i],pts[i+1],pts[j],pts[j+1])<limit){found[part]=row;pair[part]=p;return;}
        }
    }
    });
    for(int k=0;k<2;k++)if(found[k]>=0){*hit_pair=pair[k];return found[k];}
    return -1;
}

// Final 4 ms frames (planner): Horner evaluation of the C2 quintics, then the SDK float32
// rounding and back, with exactly numpy's operation order (separate multiply and add,
// -ffp-contract=off) so the plan stays bit-identical. coeff: (nseg,6,7); seg: int64 per row.
API int tcb_sample_rows(const double*coeff,int nseg,const long long*seg,const double*u,int count,
                        const int*order,const double*sign,const double*offset,float*sdk,double*rounded){
    if(count<0||count>1000000||nseg<1||!coeff||!seg||!u||!order||!sign||!offset||!sdk||!rounded)return -1;
    for(int k=0;k<7;k++)if(order[k]<0||order[k]>6)return -1;
    for(int row=0;row<count;row++)if(seg[row]<0||seg[row]>=nseg)return -1;
    const double pi=3.141592653589793;
    for_rows(count,[&](int lo,int hi){
        for(int row=lo;row<hi;row++){
            const double*c=coeff+seg[row]*42;const double uu=u[row];double s[7];
            for(int j=0;j<7;j++){double v=0.;for(int power=5;power>=0;power--){double prod=v*uu;v=prod+c[power*7+j];}s[j]=v;}
            for(int k=0;k<7;k++){
                double deg=(s[order[k]]-offset[k])*sign[k];deg=deg*180.;deg=deg/pi;
                const float f=static_cast<float>(deg);sdk[row*7+k]=f;
                double back=static_cast<double>(f)*pi;back=back/180.;back=back*sign[k];rounded[row*7+order[k]]=back+offset[k];
            }
        }
    });
    return 0;
}

API int tcb_ik(const double*m,const double*tool,const double*target,const double*seed,const double*reference,const double*opt,double*out,double*stats){
    if(!m||!tool||!target||!seed||!reference||!opt||!out||!stats)return -1;
    return solve7(m,tool,target,seed,reference,opt,out,stats);
}
// Sequential authoritative seeds, bounded like the 1013 IK_CHAIN contract.
API int tcb_ik_chain(const double*m,const double*tool,const double*targets,const double*seed,const double*opt,double*out,double*stats,int*status,int count){
    if(count<1||count>64||!targets||!out||!stats||!status)return -1;
    // Start = linear extrapolation of the last two solutions (same rule as the PL
    // core, halves iterations on sampled paths); reference = previous solution.
    const double*previous=seed;const double*before=nullptr;double start[7];
    for(int i=0;i<count;i++){
        for(int k=0;k<7;k++){
            double guess=before?2*previous[k]-before[k]:previous[k];
            start[k]=std::max(m[21*k+19],std::min(m[21*k+20],guess));
        }
        status[i]=solve7(m,tool,targets+16*i,start,previous,opt,out+7*i,stats+3*i);
        if(status[i])return i+1;
        before=previous;previous=out+7*i;
    }
    return count;
}
