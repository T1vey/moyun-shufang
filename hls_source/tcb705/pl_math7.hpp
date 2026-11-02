#pragma once
// Seven-axis IK/FK math for the PL, v2 (2026-10-18): same algorithm and ABI as
// v1 (pl_math7_v1.hpp), restructured for latency:
//  * sin/cos: own fdlibm-kernel polynomials + Cody-Waite reduction, all 14 values
//    in one interleaved pipelined loop on one multiplier (replaces the 85-DSP
//    library sin_or_cos and its 7 serial calls);
//  * link transforms: rigid 3x4 products (36 instead of 64 multiplies), 12
//    outputs pipelined at II=1;
//  * Jacobian, 7x7 normal matrix, Cholesky and triangular solves: pipelined loops,
//    reciprocal diagonal (7 divisions instead of 28).
// Every result is still verified by the PS in FP64 (planning_batches.PLChain).
#include <cmath>
#include <algorithm>
static bool finite(const double*p,int n){for(int i=0;i<n;i++)if(!std::isfinite(p[i]))return false;return true;}

namespace pl7 {
// fdlibm __kernel_sin / __kernel_cos coefficients (|r| <= pi/4, < 1 ulp)
static const double S[6]={-1.66666666666666324348e-01,8.33333333332248946124e-03,-1.98412698298579493134e-04,
                          2.75573137070700676789e-06,-2.50507602534068634195e-08,1.58969099521155010221e-10};
static const double C[6]={4.16666666666666019037e-02,-1.38888888888741095749e-03,2.48015872894767294178e-05,
                          -2.75573143513906633035e-07,2.08757232129817482790e-09,-1.13596475577881948265e-11};
static const double INVPIO2=6.36619772367581382433e-01, PIO2_1=1.57079632673412561417e+00, PIO2_1T=6.07710050650619224932e-11;
}

// sin and cos of 7 joint angles (|q| < ~1e5; joint limits are within +/- 4.1 rad).
static void sincos7(const double q[7],double s[7],double c[7]){
#pragma HLS INLINE off
#pragma HLS ALLOCATION operation instances=dmul limit=1
#pragma HLS ALLOCATION operation instances=dadd limit=1
    double r[7],z[7],acc[14];int quad[7];
#pragma HLS ARRAY_PARTITION variable=acc complete
    for(int k=0;k<7;k++){
#pragma HLS PIPELINE II=1
        double fn=std::floor(q[k]*pl7::INVPIO2+.5);
        quad[k]=int(fn)&3;r[k]=(q[k]-fn*pl7::PIO2_1)-fn*pl7::PIO2_1T;z[k]=r[k]*r[k];
        acc[k]=pl7::S[5];acc[k+7]=pl7::C[5];
    }
    // Horner, 14 independent chains interleaved: dependence distance 14 > dmul+dadd latency
    for(int step=4;step>=0;step--){
        for(int v=0;v<14;v++){
#pragma HLS PIPELINE II=1
#pragma HLS DEPENDENCE variable=acc inter false
            acc[v]=acc[v]*z[v<7?v:v-7]+(v<7?pl7::S[step]:pl7::C[step]);
        }
    }
    for(int k=0;k<7;k++){
#pragma HLS PIPELINE II=1
        double rk=r[k],zk=z[k];
        double sr=rk+rk*zk*acc[k];                 // x + x^3 * S(z)
        double cr=1.-(.5*zk-zk*zk*acc[k+7]);       // 1 - (z/2 - z^2 * C(z))
        int qd=quad[k];
        s[k]=qd==0?sr:qd==1?cr:qd==2?-sr:-cr;
        c[k]=qd==0?cr:qd==1?-sr:qd==2?-cr:sr;
    }
}

// c = a*b for rigid transforms stored as the top 3 rows (row-major 3x4); row 3 is 0 0 0 1.
static void compose(const double a[12],const double b[12],double c[12]){
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=a complete
#pragma HLS ARRAY_PARTITION variable=b complete
    for(int n=0;n<12;n++){
#pragma HLS PIPELINE II=1
        int i=n>>2,j=n&3;
        double v=a[4*i]*b[j]+a[4*i+1]*b[4+j]+a[4*i+2]*b[8+j];
        c[n]=j==3?v+a[4*i+3]:v;
    }
}

static void geometry7(const double*m,const double*q,const double*tool,double*pose,double j[6][7]){
#pragma HLS INLINE off
#pragma HLS ALLOCATION operation instances=dmul limit=4
#pragma HLS ALLOCATION operation instances=dadd limit=3
#pragma HLS ALLOCATION operation instances=dsub limit=2
    double sn[7],cs[7];sincos7(q,sn,cs);
    double t[12]={1,0,0,0,0,1,0,0,0,0,1,0},origins[7][3],axes[7][3];
#pragma HLS ARRAY_PARTITION variable=t complete
#pragma HLS ARRAY_PARTITION variable=origins complete dim=2
#pragma HLS ARRAY_PARTITION variable=axes complete dim=2
    for(int joint=0;joint<8;joint++){
        double local[12],next[12];
#pragma HLS ARRAY_PARTITION variable=local complete
#pragma HLS ARRAY_PARTITION variable=next complete
        for(int i=0;i<12;i++){
#pragma HLS PIPELINE II=1
            local[i]=joint<7?m[joint*21+i]:tool[i];
        }
        compose(t,local,next);
        if(joint<7){
            double sign=m[joint*21+18],c=cs[joint],s=sn[joint]*sign;
            for(int r=0;r<3;r++){
#pragma HLS PIPELINE II=1
                origins[joint][r]=next[r*4+3];axes[joint][r]=next[r*4+2]*sign;
                double x=next[r*4],y=next[r*4+1];next[r*4]=c*x+s*y;next[r*4+1]=-s*x+c*y;
            }
        }
        for(int i=0;i<12;i++){
#pragma HLS UNROLL
            t[i]=next[i];
        }
    }
    for(int i=0;i<12;i++){
#pragma HLS PIPELINE II=1
        pose[i]=t[i];
    }
    pose[12]=0;pose[13]=0;pose[14]=0;pose[15]=1;
    for(int n=0;n<21;n++){
#pragma HLS PIPELINE II=1
        int k=n/3,r=n%3,a=(r+1)%3,b=(r+2)%3;
        j[r][k]=axes[k][a]*(t[b*4+3]-origins[k][b])-axes[k][b]*(t[a*4+3]-origins[k][a]);
        j[r+3][k]=axes[k][r];
    }
}

static bool direction7(double j[6][7],const double*e,const double*q,const double*reference,const double*o,double*dq){
#pragma HLS INLINE off
// LUT budget (fused design): one multiplier/adder stream; every loop below is either
// pipelined with a dependence distance >= the adder latency or short (<= 6 terms).
#pragma HLS ALLOCATION operation instances=dmul limit=2
#pragma HLS ALLOCATION operation instances=dadd limit=1
#pragma HLS ALLOCATION operation instances=dsub limit=1
#pragma HLS ALLOCATION operation instances=ddiv limit=1
#pragma HLS ALLOCATION operation instances=dsqrt limit=1
    static const unsigned char TI[28]={0,1,1,2,2,2,3,3,3,3,4,4,4,4,4,5,5,5,5,5,5,6,6,6,6,6,6,6};
    static const unsigned char TK[28]={0,0,1,0,1,2,0,1,2,3,0,1,2,3,4,0,1,2,3,4,5,0,1,2,3,4,5,6};
    double w2=o[4]*o[4],damp=o[5]*o[5]+o[6];
    double jw[6][7],a[28],lower[28],inv[7],b[7],rhs[7],y[7];   // lower: packed, index i*(i+1)/2+k
    for(int i=0;i<7;i++){
#pragma HLS PIPELINE II=1
        rhs[i]=0;
    }
    for(int n=0;n<28;n++){
#pragma HLS PIPELINE II=1
        a[n]=0;
    }
    for(int r=0;r<6;r++){
        for(int i=0;i<7;i++){
#pragma HLS PIPELINE II=1
#pragma HLS DEPENDENCE variable=rhs inter false
            double v=r<3?j[r][i]:j[r][i]*w2;jw[r][i]=v;rhs[i]+=v*e[r];
        }
    }
    for(int i=0;i<7;i++){
#pragma HLS PIPELINE II=1
        b[i]=rhs[i]+o[6]*(reference[i]-q[i]);
    }
    for(int r=0;r<6;r++){    // J^T W J, lower triangle; each entry is revisited every 28 cycles
        for(int n=0;n<28;n++){
#pragma HLS PIPELINE II=1
#pragma HLS DEPENDENCE variable=a inter false
            a[n]+=jw[r][TI[n]]*j[r][TK[n]];
        }
    }
    for(int k=0;k<7;k++){    // Cholesky, column by column
        int kk=k*(k+1)/2;double d=a[kk+k]+damp;
        for(int r=0;r<k;r++){
#pragma HLS LOOP_TRIPCOUNT max=6
            d-=lower[kk+r]*lower[kk+r];
        }
        if(!(d>0))return false;
        double l=std::sqrt(d);lower[kk+k]=l;inv[k]=1./l;
        for(int i=k+1;i<7;i++){
#pragma HLS LOOP_TRIPCOUNT max=6
            int ii=i*(i+1)/2;double v=a[ii+k];
            for(int r=0;r<k;r++){
#pragma HLS LOOP_TRIPCOUNT max=6
                v-=lower[ii+r]*lower[kk+r];
            }
            lower[ii+k]=v*inv[k];
        }
    }
    for(int i=0;i<7;i++){
        int ii=i*(i+1)/2;double v=b[i];
        for(int k=0;k<i;k++){
#pragma HLS LOOP_TRIPCOUNT max=6
            v-=lower[ii+k]*y[k];
        }
        y[i]=v*inv[i];
    }
    for(int reverse=0;reverse<7;reverse++){
        int i=6-reverse;double v=y[i];
        for(int k=i+1;k<7;k++){
#pragma HLS LOOP_TRIPCOUNT max=6
            v-=lower[k*(k+1)/2+i]*dq[k];
        }
        dq[i]=v*inv[i];
    }
    return finite(dq,7);
}

// start: initial guess (extrapolated along the path); reference: previous solution (continuity term)
static int run_row7(bool fk_only,const double*m,const double*tool,const double*target,const double*seed,const double*reference,const double*o,double*out,double*stats,double*pose){
#pragma HLS INLINE off
#pragma HLS ALLOCATION function instances=geometry7 limit=1
#pragma HLS ALLOCATION operation instances=dmul limit=3
#pragma HLS ALLOCATION operation instances=dadd limit=2
#pragma HLS ALLOCATION operation instances=dsub limit=1
#pragma HLS ALLOCATION operation instances=ddiv limit=1
#pragma HLS ALLOCATION operation instances=dsqrt limit=1
#pragma HLS ALLOCATION operation instances=dcmp limit=2
    double q[7],trial[7],dq[7]={0},gain=1,previous_cost=0;
#pragma HLS ARRAY_PARTITION variable=q complete
#pragma HLS ARRAY_PARTITION variable=trial complete
#pragma HLS ARRAY_PARTITION variable=dq complete
    bool searching=false;int iteration=0,backtrack=0;
    for(int k=0;k<7;k++){q[k]=seed[k];trial[k]=seed[k];out[k]=seed[k];}
    for(int evaluation=0;evaluation<17001;evaluation++){
        double current[7],j[6][7],error[6];
        for(int k=0;k<7;k++){
#pragma HLS UNROLL
            current[k]=searching?trial[k]:q[k];
        }
        geometry7(m,current,tool,pose,j); // sole geometry call site, including FK_ROWS
        if(fk_only)return finite(pose,16)?0:2;
        double relative[9];
#pragma HLS ARRAY_PARTITION variable=relative complete
        for(int n=0;n<9;n++){
#pragma HLS PIPELINE II=1
            int r=n/3,c=n%3;
            relative[n]=target[r*4]*pose[c*4]+target[r*4+1]*pose[c*4+1]+target[r*4+2]*pose[c*4+2];
        }
        // First-attempt local solver only. Large orientation changes are handed
        // back to the full CPU SO(3) solver, never accepted using a small-angle model.
        if(relative[0]+relative[4]+relative[8]<2.9975)return 2;
        error[3]=.5*(relative[7]-relative[5]);error[4]=.5*(relative[2]-relative[6]);error[5]=.5*(relative[3]-relative[1]);
        double pe2=0,ae2=0;
        for(int r=0;r<3;r++){error[r]=target[r*4+3]-pose[r*4+3];pe2+=error[r]*error[r];ae2+=error[r+3]*error[r+3];}
        double cost=pe2+o[4]*o[4]*ae2;
        if(!std::isfinite(cost))return 2;
        if(searching){
            if(cost<previous_cost){for(int k=0;k<7;k++){q[k]=trial[k];out[k]=q[k];}searching=false;iteration++;}
            else{backtrack++;gain*=.5;if(backtrack>=16)return 2;}
        }else{
            stats[0]=std::sqrt(pe2);stats[1]=std::sqrt(ae2);stats[2]=iteration;
            if(stats[0]<=o[0]&&stats[1]<=o[1])return 0;
            if(iteration>=int(o[2]))return 1;
            if(!direction7(j,error,q,reference,o,dq))return 2;
            double largest=0;for(int k=0;k<7;k++)largest=std::max(largest,std::abs(dq[k]));
            gain=largest>o[3]?o[3]/largest:1;previous_cost=cost;backtrack=0;searching=true;
        }
        if(searching)for(int k=0;k<7;k++){
#pragma HLS PIPELINE II=1
            trial[k]=std::max(m[21*k+19],std::min(m[21*k+20],q[k]+gain*dq[k]));
        }
    }
    return 1;
}
