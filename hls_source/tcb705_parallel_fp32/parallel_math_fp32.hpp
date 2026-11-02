#pragma once
#include <cmath>
#include <cstdint>

// All geometry arithmetic is IEEE binary32. No hidden double constants and no
// Jacobian/LDLT machinery. Inline helpers let one consuming stage share FP units.
static bool finite32(float x) {
#pragma HLS INLINE
    union {float f;uint32_t u;} v;v.f=x;
    return (v.u&0x7f800000U)!=0x7f800000U;
}
static bool finite_fp32(const float* x,int n) {
    for(int i=0;i<n;i++) {
#pragma HLS PIPELINE II=1
        if(!finite32(x[i]))return false;
    }
    return true;
}
static float quiet_nan_fp32() {
#pragma HLS INLINE
    union {float f;uint32_t u;} v;v.u=0x7fc00000U;return v.f;
}

// Initialization needs only the shoulder's first two joint angles. The SRS
// caller validates its limits before this function. Invalid/out-of-range inputs
// still produce NaN, rather than entering an undefined float-to-int conversion.
// Eight-cycle adds avoid the short default FP32 adder's 8.6 ns output path.
// Validated HLS configuration uses syn.op=op:fmul impl:fulldsp latency:5.
static float seed_add_fp32(float a,float b) {
#pragma HLS INLINE
    float sum=a+b;
#pragma HLS BIND_OP variable=sum op=fadd impl=fulldsp latency=8
    return sum;
}
static float seed_sub_fp32(float a,float b) {
#pragma HLS INLINE
    float difference=a-b;
#pragma HLS BIND_OP variable=difference op=fsub impl=fulldsp latency=8
    return difference;
}
static void parallel_seed_sincos2_fp32(const float q[7],float s[7],float c[7]) {
#pragma HLS INLINE
#pragma HLS ARRAY_PARTITION variable=q complete
#pragma HLS ARRAY_PARTITION variable=s complete
#pragma HLS ARRAY_PARTITION variable=c complete
    F32_SEED_UNUSED: for(int k=2;k<7;k++) {
#pragma HLS UNROLL
        s[k]=0.0f;c[k]=1.0f;
    }
    F32_SEED_ANGLES: for(int k=0;k<2;k++) {
        const float a=std::abs(q[k]);
        const bool valid=finite32(q[k])&&a<=3.1415927410125732421875f;
        // Selection is exactly equivalent to five intervals bounded by
        // -3pi/4, -pi/4, pi/4, 3pi/4. No floor or int32 converter is needed.
        const int quadrant=a>2.35619449019234492885f?2:(a>0.785398163397448309616f?1:0);
        const float hi=quadrant==2?3.140625f:(quadrant==1?1.5703125f:0.0f);
        const float mid=quadrant==2?0.000967502593994140625f:(quadrant==1?0.0004837512969970703125f:0.0f);
        const float lo=quadrant==2?1.50995788317231927067e-7f:(quadrant==1?7.54978941586159635335e-8f:0.0f);
        const float r=seed_sub_fp32(seed_sub_fp32(seed_sub_fp32(a,hi),mid),lo);
        const float z=r*r;
        // On |r|<=pi/4 these four terms have truncation error <2e-9.
        float sp=seed_add_fp32(-1.98412698298579493134e-4f,z*2.75573137070700676789e-6f);
        sp=seed_add_fp32(8.33333333332248946124e-3f,z*sp);
        sp=seed_add_fp32(-1.66666666666666324348e-1f,z*sp);
        float cp=seed_add_fp32(2.48015872894767294178e-5f,z*(-2.75573143513906633035e-7f));
        cp=seed_add_fp32(-1.38888888888741095749e-3f,z*cp);
        cp=seed_add_fp32(4.16666666666666019037e-2f,z*cp);
        const float sr=seed_add_fp32(r,(r*z)*sp);
        const float cr=seed_sub_fp32(1.0f,seed_sub_fp32(0.5f*z,(z*z)*cp));
        const float sa=quadrant==0?sr:(quadrant==1?cr:-sr);
        const float ca=quadrant==0?cr:(quadrant==1?-sr:-cr);
        s[k]=valid?(q[k]<0.0f?-sa:sa):quiet_nan_fp32();
        c[k]=valid?ca:quiet_nan_fp32();
    }
}

static void parallel_sincos7_fp32(const float q[7],float s[7],float c[7]) {
#pragma HLS INLINE
#pragma HLS ARRAY_PARTITION variable=q complete
#pragma HLS ARRAY_PARTITION variable=s complete
#pragma HLS ARRAY_PARTITION variable=c complete
    const float S[6]={-1.66666666666666324348e-1f,8.33333333332248946124e-3f,
        -1.98412698298579493134e-4f,2.75573137070700676789e-6f,-2.50507602534068634195e-8f,1.58969099521155010221e-10f};
    const float C[6]={4.16666666666666019037e-2f,-1.38888888888741095749e-3f,
        2.48015872894767294178e-5f,-2.75573143513906633035e-7f,2.08757232129817482790e-9f,-1.13596475577881948265e-11f};
#pragma HLS ARRAY_PARTITION variable=S complete
#pragma HLS ARRAY_PARTITION variable=C complete
    float r[7],z[7],acc[14];int quad[7];bool valid[7];
#pragma HLS ARRAY_PARTITION variable=r complete
#pragma HLS ARRAY_PARTITION variable=z complete
#pragma HLS ARRAY_PARTITION variable=acc complete
#pragma HLS ARRAY_PARTITION variable=quad complete
#pragma HLS ARRAY_PARTITION variable=valid complete
    F32_TRIG_REDUCE: for(int k=0;k<7;k++) {
#pragma HLS PIPELINE II=1
        const float input=finite32(q[k])?q[k]:0.0f;
        float fn=std::floor(input*0.636619772367581382433f+0.5f);
        valid[k]=finite32(q[k])&&fn<2147483648.0f&&fn>=-2147483648.0f;
        if(!valid[k])fn=0.0f;
        quad[k]=int(fn)&3;
        // Three exactly representable/correctly rounded float pieces of pi/2
        // improve reduction near +/-pi over casting the old double high piece.
        r[k]=((input-fn*1.5703125f)-fn*0.0004837512969970703125f)-fn*7.54978941586159635335e-8f;
        z[k]=r[k]*r[k];acc[k]=S[5];acc[k+7]=C[5];
    }
    F32_TRIG_ORDER: for(int step=4;step>=0;step--) {
        F32_TRIG_PAIR: for(int k=0;k<7;k++) {
#pragma HLS PIPELINE II=1
            acc[k]=acc[k]*z[k]+S[step];
            acc[k+7]=acc[k+7]*z[k]+C[step];
        }
    }
    F32_TRIG_FINISH: for(int k=0;k<7;k++) {
#pragma HLS PIPELINE II=1
        const float sr=r[k]+r[k]*z[k]*acc[k];
        const float cr=1.0f-(0.5f*z[k]-z[k]*z[k]*acc[k+7]);const int d=quad[k];
        s[k]=valid[k]?(d==0?sr:d==1?cr:d==2?-sr:-cr):quiet_nan_fp32();
        c[k]=valid[k]?(d==0?cr:d==1?-sr:d==2?-cr:sr):quiet_nan_fp32();
    }
}

static bool parallel_compose_is_rx_z_fp32(const float b[12]) {
#pragma HLS INLINE
#pragma HLS ARRAY_PARTITION variable=b complete
    if(b[0]!=1.0f||b[1]!=0.0f||b[2]!=0.0f||b[3]!=0.0f||b[4]!=0.0f||b[7]!=0.0f||b[8]!=0.0f||
       b[5]!=b[10]||b[6]!=-b[9]||!finite32(b[11]))return false;
    return (b[5]==1.0f&&b[9]==0.0f)||((b[9]==1.0f||b[9]==-1.0f)&&finite32(b[5])&&std::abs(b[5])<=1e-12f);
}
static void parallel_compose_fp32(const float a[12],const float b[12],float c[12]) {
#pragma HLS INLINE
#pragma HLS ARRAY_PARTITION variable=a complete
#pragma HLS ARRAY_PARTITION variable=b complete
#pragma HLS ARRAY_PARTITION variable=c complete
    F32_COMPOSE_PAIRS: for(int n=0;n<6;n++) {
#pragma HLS PIPELINE II=1
        for(int lane=0;lane<2;lane++) {
#pragma HLS UNROLL
            const int index=2*n+lane,r=index/4,k=index%4;
            const float v=(a[4*r]*b[k]+a[4*r+1]*b[4+k])+a[4*r+2]*b[8+k];
            c[index]=k==3?v+a[4*r+3]:v;
        }
    }
}
static void parallel_compose_rx_z_fp32(const float a[12],const float b[12],float c[12]) {
#pragma HLS INLINE
#pragma HLS ARRAY_PARTITION variable=a complete
#pragma HLS ARRAY_PARTITION variable=b complete
#pragma HLS ARRAY_PARTITION variable=c complete
    const float cosine=b[5],sine=b[9],distance=b[11];
    F32_SPARSE_ROWS: for(int row=0;row<3;row++) {
#pragma HLS PIPELINE II=1
        const float x=a[4*row],y=a[4*row+1],z=a[4*row+2];c[4*row]=x;
        if(sine==0.0f){c[4*row+1]=y;c[4*row+2]=z;}
        else {c[4*row+1]=y*cosine+(sine>0.0f?z:-z);c[4*row+2]=(sine>0.0f?-y:y)+z*cosine;}
        c[4*row+3]=z*distance+a[4*row+3];
    }
}
static void parallel_geometry7_fp32(const float m[147],const float q[7],const float tool[16],
    const bool sparse[8],float pose[16]) {
#pragma HLS INLINE
#pragma HLS ARRAY_PARTITION variable=q complete
#pragma HLS ARRAY_PARTITION variable=tool complete
#pragma HLS ARRAY_PARTITION variable=sparse complete
#pragma HLS ARRAY_PARTITION variable=pose complete
    float sn[7],cs[7],t[12]={1.0f,0.0f,0.0f,0.0f,0.0f,1.0f,0.0f,0.0f,0.0f,0.0f,1.0f,0.0f};
#pragma HLS ARRAY_PARTITION variable=sn complete
#pragma HLS ARRAY_PARTITION variable=cs complete
#pragma HLS ARRAY_PARTITION variable=t complete
    parallel_sincos7_fp32(q,sn,cs);
    F32_LINK_CHAIN: for(int joint=0;joint<8;joint++) {
        float local[12],next[12];
#pragma HLS ARRAY_PARTITION variable=local complete
#pragma HLS ARRAY_PARTITION variable=next complete
        F32_LINK_LOAD: for(int n=0;n<12;n++) {
#pragma HLS PIPELINE II=1
            local[n]=joint<7?m[joint*21+n]:tool[n];
        }
        if(joint==0){for(int n=0;n<12;n++) {
#pragma HLS UNROLL
            next[n]=local[n];
        }} else if(sparse[joint])parallel_compose_rx_z_fp32(t,local,next);
        else parallel_compose_fp32(t,local,next);
        if(joint<7) {
            const float s=sn[joint]*m[joint*21+18],c=cs[joint];
            for(int r=0;r<3;r++) {
#pragma HLS UNROLL
                const float x=next[4*r],y=next[4*r+1];
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
    pose[12]=0.0f;pose[13]=0.0f;pose[14]=0.0f;pose[15]=1.0f;
}
