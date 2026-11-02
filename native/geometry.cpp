// FP64-only, bounded C ABI. Do not compile with fast-math or FP contraction.
#include <cmath>
#include <cstdint>
#include <cfloat>
#include <cfenv>
#ifdef __FAST_MATH__
#error "fast-math is incompatible with planning validation"
#endif
#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C" __attribute__((visibility("default")))
#endif
static const uint32_t ABI=0x534e0101u;
static bool finite(const double* p, uint32_t n) {
    if(!p)return false;
    for(uint32_t i=0;i<n;++i)if(!std::isfinite(p[i]))return false;
    return true;
}
API uint32_t so101_geometry_abi() { return ABI; }
API int so101_geometry_fp64() {
    return sizeof(double)==8 && DBL_MANT_DIG==53 && FLT_RADIX==2
        && std::fegetround()==FE_TONEAREST;
}
// Immutable model layout: offsets[5][3], axes[5][3], tool[3], tool_axis[3].
static void pose(const double* m,const double* q,double* out) {
    double r[9]={1,0,0,0,1,0,0,0,1},p[3]={0,0,0};
    for(int j=0;j<5;++j) {
        const double* off=m+3*j; const double* ax=m+15+3*j;
        for(int i=0;i<3;++i)p[i]+=r[3*i]*off[0]+r[3*i+1]*off[1]+r[3*i+2]*off[2];
        const double k[9]={0,-ax[2],ax[1],ax[2],0,-ax[0],-ax[1],ax[0],0};
        double local[9],next[9]; const double s=std::sin(q[j]),c=1-std::cos(q[j]);
        for(int i=0;i<3;++i)for(int t=0;t<3;++t) {
            const double square=k[3*i]*k[t]+k[3*i+1]*k[3+t]+k[3*i+2]*k[6+t];
            local[3*i+t]=((i==t?1.:0.)+s*k[3*i+t])+c*square;
        }
        for(int i=0;i<3;++i)for(int t=0;t<3;++t)
            next[3*i+t]=r[3*i]*local[t]+r[3*i+1]*local[3+t]+r[3*i+2]*local[6+t];
        for(int i=0;i<9;++i)r[i]=next[i];
    }
    for(int i=0;i<16;++i)out[i]=0;out[15]=1;
    for(int i=0;i<3;++i) {
        for(int t=0;t<3;++t)out[4*i+t]=r[3*i+t];
        out[4*i+3]=p[i]+r[3*i]*m[30]+r[3*i+1]*m[31]+r[3*i+2]*m[32];
    }
}
API int so101_pose_rows(const double* m,const double* q,uint32_t n,double* out) {
    if(!so101_geometry_fp64()||n>1024||!finite(m,36)||!finite(q,5*n)||!out)return 1;
    for(uint32_t i=0;i<n;++i)pose(m,q+5*i,out+16*i);
    return finite(out,16*n)?0:2;
}
API int so101_geometry_rows(const double* m,const double* q,const double* starts,
    const double* deltas,const double* desired,const double* axes,uint32_t n,double* out) {
    if(!so101_geometry_fp64()||n>1024||!finite(m,36)||!finite(q,5*n)
       ||!finite(starts,3*n)||!finite(deltas,3*n)||!finite(desired,3*n)
       ||!finite(axes,3*n)||!out)return 1;
    for(uint32_t i=0;i<n;++i) {
        double t[16],a[3],diff[3];pose(m,q+5*i,t);
        const double *p0=starts+3*i,*d=deltas+3*i,*wanted=desired+3*i,*axis=axes+3*i;
        double* row=out+6*i;double norm=0,dot=0;
        for(int k=0;k<3;++k) {
            row[k]=t[4*k+3];diff[k]=row[k]-p0[k];norm+=d[k]*d[k];dot+=diff[k]*d[k];
            a[k]=t[4*k]*m[33]+t[4*k+1]*m[34]+t[4*k+2]*m[35];
        }
        const double f=norm>1e-20?std::fmax(0.,std::fmin(1.,dot/norm)):0.;
        double path2=0,requested2=0;
        for(int k=0;k<3;++k) {
            const double path=row[k]-(p0[k]+f*d[k]),err=row[k]-wanted[k];
            path2+=path*path;requested2+=err*err;
        }
        const double cx=axis[1]*a[2]-axis[2]*a[1],cy=axis[2]*a[0]-axis[0]*a[2],cz=axis[0]*a[1]-axis[1]*a[0];
        row[3]=std::sqrt(path2);row[4]=std::sqrt(requested2);
        row[5]=std::atan2(std::sqrt(cx*cx+cy*cy+cz*cz),axis[0]*a[0]+axis[1]*a[1]+axis[2]*a[2]);
    }
    return finite(out,6*n)?0:2;
}
