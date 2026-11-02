#pragma once
// Experimental 100 MHz seven-axis core. FP64 and original acceptance limits.
// Parallelism is inside one IK point; CHAIN rows still depend on prior solutions.
#include <cmath>
#include <algorithm>
#include <cstdint>
#include "parallel_direction.hpp"
#include "parallel_compose_sparse.hpp"

// IEEE-754 finite test is a bit test, not a floating-point comparison. This
// also handles both infinities, quiet/signalling NaNs and signed zero.
static bool finite64(double value) {
#pragma HLS INLINE
    union { double d; uint64_t u; } bits;
    bits.d=value;
    return (bits.u & UINT64_C(0x7ff0000000000000)) != UINT64_C(0x7ff0000000000000);
}

static bool finite(const double *p,int n) {
    for(int i=0;i<n;i++) {
#pragma HLS PIPELINE II=1
        if(!finite64(p[i])) return false;
    }
    return true;
}

namespace parallel7 {
static const double S[6]={-1.66666666666666324348e-01,8.33333333332248946124e-03,
 -1.98412698298579493134e-04,2.75573137070700676789e-06,-2.50507602534068634195e-08,1.58969099521155010221e-10};
static const double C[6]={4.16666666666666019037e-02,-1.38888888888741095749e-03,
 2.48015872894767294178e-05,-2.75573143513906633035e-07,2.08757232129817482790e-09,-1.13596475577881948265e-11};
}

static void parallel_sincos7(const double q[7],double s[7],double c[7]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=q complete
#pragma HLS ARRAY_PARTITION variable=s complete
#pragma HLS ARRAY_PARTITION variable=c complete
#pragma HLS ALLOCATION operation instances=dmul limit=2
#pragma HLS ALLOCATION operation instances=dadd limit=2
    double r[7],z[7],acc[14];int quad[7];
#pragma HLS ARRAY_PARTITION variable=r complete
#pragma HLS ARRAY_PARTITION variable=z complete
#pragma HLS ARRAY_PARTITION variable=acc complete
#pragma HLS ARRAY_PARTITION variable=quad complete
    TRIG_REDUCE: for(int k=0;k<7;k++) {
#pragma HLS PIPELINE II=1
        double fn=std::floor(q[k]*6.36619772367581382433e-01+.5);
        quad[k]=int(fn)&3;
        r[k]=(q[k]-fn*1.57079632673412561417e+00)-fn*6.07710050650619224932e-11;
        z[k]=r[k]*r[k];acc[k]=parallel7::S[5];acc[k+7]=parallel7::C[5];
    }
    TRIG_ORDER: for(int step=4;step>=0;step--) {
        TRIG_PAIR: for(int k=0;k<7;k++) {
#pragma HLS PIPELINE II=1
            // Independent sine/cosine lanes; the true recurrence is across orders.
            acc[k]=acc[k]*z[k]+parallel7::S[step];
            acc[k+7]=acc[k+7]*z[k]+parallel7::C[step];
        }
    }
    TRIG_FINISH: for(int k=0;k<7;k++) {
#pragma HLS PIPELINE II=1
        double sr=r[k]+r[k]*z[k]*acc[k];
        double cr=1.-(.5*z[k]-z[k]*z[k]*acc[k+7]);int d=quad[k];
        s[k]=d==0?sr:d==1?cr:d==2?-sr:-cr;
        c[k]=d==0?cr:d==1?-sr:d==2?-cr:sr;
    }
}

static void parallel_compose(const double a[12],const double b[12],double c[12]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=a complete
#pragma HLS ARRAY_PARTITION variable=b complete
#pragma HLS ARRAY_PARTITION variable=c complete
    // Two outputs in parallel, each with three independent products. Summation
    // order remains the FP64 reference order. No cross-point speculation.
    COMPOSE_PAIRS: for(int n=0;n<6;n++) {
#pragma HLS PIPELINE II=1
        COMPOSE_LANES: for(int lane=0;lane<2;lane++) {
#pragma HLS UNROLL
            int index=2*n+lane,r=index/4,k=index%4;
            double v=a[4*r]*b[k]+a[4*r+1]*b[4+k]+a[4*r+2]*b[8+k];
            c[index]=k==3?v+a[4*r+3]:v;
        }
    }
}

static void parallel_geometry7(const double m[147],const double q[7],const double tool[16],
                               const bool sparse[8],double pose[16],double j[6][7]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=q complete
#pragma HLS ARRAY_PARTITION variable=tool complete
#pragma HLS ARRAY_PARTITION variable=pose complete
#pragma HLS ARRAY_PARTITION variable=j complete dim=1
#pragma HLS ARRAY_PARTITION variable=sparse complete
#pragma HLS ALLOCATION operation instances=dmul limit=6
#pragma HLS ALLOCATION operation instances=dadd limit=3
#pragma HLS ALLOCATION operation instances=dsub limit=3
    double sn[7],cs[7];
#pragma HLS ARRAY_PARTITION variable=sn complete
#pragma HLS ARRAY_PARTITION variable=cs complete
    parallel_sincos7(q,sn,cs);
    double t[12]={1,0,0,0,0,1,0,0,0,0,1,0},origins[7][3],axes[7][3];
#pragma HLS ARRAY_PARTITION variable=t complete
#pragma HLS ARRAY_PARTITION variable=origins complete dim=2
#pragma HLS ARRAY_PARTITION variable=axes complete dim=2
    FK_LINK_CHAIN: for(int joint=0;joint<8;joint++) {
        double local[12],next[12];
#pragma HLS ARRAY_PARTITION variable=local complete
#pragma HLS ARRAY_PARTITION variable=next complete
        FK_LOAD: for(int n=0;n<12;n++) {
#pragma HLS PIPELINE II=1
            local[n]=joint<7?m[joint*21+n]:tool[n];
        }
        if(joint==0) {
            for(int n=0;n<12;n++) {
#pragma HLS UNROLL
                next[n]=local[n];
            }
        } else if(sparse[joint]) parallel_compose_rx_z(t,local,next);
        else parallel_compose(t,local,next);
        if(joint<7) {
            double sign=m[joint*21+18],s=sn[joint]*sign,c=cs[joint];
            FK_ROTATE_ROWS: for(int r=0;r<3;r++) {
#pragma HLS UNROLL
                origins[joint][r]=next[4*r+3];axes[joint][r]=next[4*r+2]*sign;
                double x=next[4*r],y=next[4*r+1];
                next[4*r]=c*x+s*y;next[4*r+1]=-s*x+c*y;
            }
        }
        for(int n=0;n<12;n++) {
#pragma HLS UNROLL
            t[n]=next[n];
        }
    }
    for(int n=0;n<12;n++) {
#pragma HLS UNROLL
        pose[n]=t[n];
    }
    pose[12]=0;pose[13]=0;pose[14]=0;pose[15]=1;
    JACOBIAN_COLUMNS: for(int k=0;k<7;k++) {
#pragma HLS PIPELINE II=1
        JACOBIAN_XYZ: for(int r=0;r<3;r++) {
#pragma HLS UNROLL
            int a=(r+1)%3,b=(r+2)%3;
            j[r][k]=axes[k][a]*(t[4*b+3]-origins[k][b])-axes[k][b]*(t[4*a+3]-origins[k][a]);
            j[r+3][k]=axes[k][r];
        }
    }
}

static int run_row7(bool fk_only,const double m[147],const double tool[16],
                    const bool sparse[8],
                    const double target[16],const double seed[7],const double reference[7],
                    const double o[7],double out[7],double stats[3],double pose[16]) {
#pragma HLS INLINE off
#pragma HLS ALLOCATION function instances=parallel_geometry7 limit=1
#pragma HLS ALLOCATION operation instances=dmul limit=3
#pragma HLS ALLOCATION operation instances=dadd limit=2
#pragma HLS ALLOCATION operation instances=dsub limit=2
#pragma HLS ALLOCATION operation instances=ddiv limit=1
#pragma HLS ALLOCATION operation instances=dsqrt limit=1
#pragma HLS ARRAY_PARTITION variable=target complete
#pragma HLS ARRAY_PARTITION variable=seed complete
#pragma HLS ARRAY_PARTITION variable=reference complete
#pragma HLS ARRAY_PARTITION variable=o complete
#pragma HLS ARRAY_PARTITION variable=out complete
#pragma HLS ARRAY_PARTITION variable=pose complete
#pragma HLS ARRAY_PARTITION variable=sparse complete
    double q[7],trial[7],dq[7]={0},gain=1,previous_cost=0;
#pragma HLS ARRAY_PARTITION variable=q complete
#pragma HLS ARRAY_PARTITION variable=trial complete
#pragma HLS ARRAY_PARTITION variable=dq complete
    bool searching=false;int iteration=0,backtrack=0;
    for(int k=0;k<7;k++) {
#pragma HLS UNROLL
        q[k]=seed[k];trial[k]=seed[k];out[k]=seed[k];
    }
    IK_EVALUATIONS: for(int evaluation=0;evaluation<17001;evaluation++) {
        double current[7],j[6][7],error[6],relative[9];
#pragma HLS ARRAY_PARTITION variable=current complete
#pragma HLS ARRAY_PARTITION variable=j complete dim=1
#pragma HLS ARRAY_PARTITION variable=error complete
#pragma HLS ARRAY_PARTITION variable=relative complete
        for(int k=0;k<7;k++) {
#pragma HLS UNROLL
            current[k]=searching?trial[k]:q[k];
        }
        parallel_geometry7(m,current,tool,sparse,pose,j);
        if(fk_only)return finite(pose,16)?0:2;
        RELATIVE_ROTATION: for(int n=0;n<9;n++) {
#pragma HLS PIPELINE II=1
            int r=n/3,c=n%3;
            relative[n]=target[4*r]*pose[4*c]+target[4*r+1]*pose[4*c+1]+target[4*r+2]*pose[4*c+2];
        }
        if(relative[0]+relative[4]+relative[8]<2.9975)return 2;
        error[3]=.5*(relative[7]-relative[5]);
        error[4]=.5*(relative[2]-relative[6]);
        error[5]=.5*(relative[3]-relative[1]);
        double ep[3],ea[3];
#pragma HLS ARRAY_PARTITION variable=ep complete
#pragma HLS ARRAY_PARTITION variable=ea complete
        for(int r=0;r<3;r++) {
#pragma HLS PIPELINE II=1
            error[r]=target[4*r+3]-pose[4*r+3];
            ep[r]=error[r]*error[r];ea[r]=error[r+3]*error[r+3];
        }
        // Two independent reductions, preserving the original FP64 sum order.
        double pe2=(ep[0]+ep[1])+ep[2],ae2=(ea[0]+ea[1])+ea[2];
        double cost=pe2+o[4]*o[4]*ae2;
        if(!finite64(cost))return 2;
        bool accepted=!searching;
        if(searching) {
            if(cost<previous_cost) {
                for(int k=0;k<7;k++) {
#pragma HLS UNROLL
                    q[k]=trial[k];out[k]=q[k];
                }
                searching=false;iteration++;accepted=true;
            } else {
                backtrack++;gain*=.5;if(backtrack>=16)return 2;
            }
        }
        if(accepted) {
            // Reuse the accepted trial's FK, Jacobian and error. The old core
            // recomputed exactly this same pose at the next evaluation.
            stats[0]=std::sqrt(pe2);stats[1]=std::sqrt(ae2);stats[2]=iteration;
            if(stats[0]<=o[0]&&stats[1]<=o[1])return 0;
            if(iteration>=int(o[2]))return 1;
            if(!parallel_direction7(j,error,q,reference,o,dq))return 2;
            double largest=0;
            for(int k=0;k<7;k++)largest=std::max(largest,std::abs(dq[k]));
            gain=largest>o[3]?o[3]/largest:1.;previous_cost=cost;backtrack=0;searching=true;
        }
        if(searching) {
            UPDATE_JOINTS: for(int k=0;k<7;k++) {
#pragma HLS PIPELINE II=1
                trial[k]=std::max(m[21*k+19],std::min(m[21*k+20],q[k]+gain*dq[k]));
            }
        }
    }
    return 1;
}
