#pragma once
#include <cstdint>
namespace tcb_atan2_fp32_detail {
static const int32_t PI_FIXED=843314857;
static const float PI=3.14159265358979323846f;
static uint32_t bits(float f) {
#pragma HLS INLINE
    union {float f;uint32_t u;}v;v.f=f;return v.u;
}
static float from_bits(uint32_t u) {
#pragma HLS INLINE
    union {float f;uint32_t u;}v;v.u=u;return v.f;
}
static_assert((-1>>1)==-1,"CORDIC requires arithmetic signed right shift");
static bool prepare(float y,float x,int32_t& vx,int32_t& vy,int32_t& va,float& special) {
#pragma HLS INLINE
    const uint32_t xb=bits(x),yb=bits(y);const unsigned ex=(xb>>23)&255U,ey=(yb>>23)&255U;
    const uint32_t xm=(xb&0x007fffffU)|(ex?0x00800000U:0U),ym=(yb&0x007fffffU)|(ey?0x00800000U:0U);
    const bool sx=(xb>>31)!=0,sy=(yb>>31)!=0;vx=vy=va=0;special=from_bits(0x7fc00000U);
    if(ex==255||ey==255||(xm==0&&ym==0))return false;
    if(ym==0){special=sx?(sy?-PI:PI):y;return false;}
    if(xm==0){special=sy?-PI*0.5f:PI*0.5f;return false;}
    uint32_t ux,uy;
    if(ex==0&&ey==0){const uint32_t maximum=xm>ym?xm:ym;unsigned highest=0;
        for(unsigned b=0;b<23;b++) {
#pragma HLS UNROLL
            if((maximum>>b)&1U)highest=b;
        }
        ux=xm<<(27-highest);uy=ym<<(27-highest);
    } else {
        const unsigned a=ex?ex:1,b=ey?ey:1,maximum=a>b?a:b,dx=maximum-a,dy=maximum-b;
        ux=dx<32?(xm<<4)>>dx:0U;uy=dy<32?(ym<<4)>>dy:0U;
    }
    vx=sx?-int32_t(ux):int32_t(ux);vy=sy?-int32_t(uy):int32_t(uy);
    if(sx){vx=-vx;vy=-vy;va=sy?-PI_FIXED:PI_FIXED;}
    return true;
}
static float scale(int32_t value) {
#pragma HLS INLINE
    if(value==0)return 0.0f;
    // int32->float rounding, followed by exact power-of-two exponent change.
    return from_bits(bits(float(value))-(28U<<23));
}
// SRS-private contract: the caller already rejects singular angle pairs with
// norm < 1e-5. Therefore both components cannot be subnormal. Keep the general
// prepare() above for standalone callers, and explicitly reject that domain
// here rather than paying for its leading-zero/left-shift hardware three times.
static bool prepare_guarded(float y,float x,int32_t& vx,int32_t& vy,int32_t& va,float& special) {
#pragma HLS INLINE
    const uint32_t xb=bits(x),yb=bits(y);const unsigned ex=(xb>>23)&255U,ey=(yb>>23)&255U;
    const uint32_t xm=(xb&0x007fffffU)|(ex?0x00800000U:0U),ym=(yb&0x007fffffU)|(ey?0x00800000U:0U);
    const bool sx=(xb>>31)!=0,sy=(yb>>31)!=0;vx=vy=va=0;special=from_bits(0x7fc00000U);
    if(ex==255||ey==255||(ex==0&&ey==0))return false;
    if(ym==0){special=sx?(sy?-PI:PI):y;return false;}
    if(xm==0){special=sy?-PI*0.5f:PI*0.5f;return false;}
    const unsigned a=ex?ex:1,b=ey?ey:1,maximum=a>b?a:b,dx=maximum-a,dy=maximum-b;
    const uint32_t ux=dx<32?(xm<<4)>>dx:0U,uy=dy<32?(ym<<4)>>dy:0U;
    vx=sx?-int32_t(ux):int32_t(ux);vy=sy?-int32_t(uy):int32_t(uy);
    if(sx){vx=-vx;vy=-vy;va=sy?-PI_FIXED:PI_FIXED;}
    return true;
}
}
// Three lanes, 28 vectoring steps, Q3.28 in signed32. Coordinate bound<2.33,
// angle accumulator bound<4.89: both fit the signed carrier range [-8,8).
// Input finite/nonzero vectors are normalized by shared IEEE exponent. Invalid
// vectors return NaN; axes preserve signed zero. No float atan2 IP is used.
static void srs_atan2_7_fp32(const float y[7],const float x[7],float angles[7]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=y complete
#pragma HLS ARRAY_PARTITION variable=x complete
#pragma HLS ARRAY_PARTITION variable=angles complete
    static const int32_t table[28]={210828714,124459457,65760959,33381290,16755422,8385879,4193963,2097109,1048571,524287,262144,131072,65536,32768,16384,8192,4096,2048,1024,512,256,128,64,32,16,8,4,2};
#pragma HLS BIND_STORAGE variable=table type=rom_1p impl=lutram
    int32_t vx[3],vy[3],va[3];float special[3];bool enabled[3];
#pragma HLS ARRAY_PARTITION variable=vx complete
#pragma HLS ARRAY_PARTITION variable=vy complete
#pragma HLS ARRAY_PARTITION variable=va complete
#pragma HLS ARRAY_PARTITION variable=special complete
#pragma HLS ARRAY_PARTITION variable=enabled complete
    F32_ATAN_GROUP: for(int group=0;group<3;group++) {
        for(int lane=0;lane<3;lane++) {
#pragma HLS UNROLL
            const int n=3*group+lane;
            enabled[lane]=tcb_atan2_fp32_detail::prepare(n<7?y[n]:0.0f,n<7?x[n]:1.0f,vx[lane],vy[lane],va[lane],special[lane]);
        }
        F32_ATAN_STEPS: for(unsigned step=0;step<28;step++) {
#pragma HLS PIPELINE II=1
            const int32_t delta=table[step];
            for(int lane=0;lane<3;lane++) {
#pragma HLS UNROLL
                if(enabled[lane]){const int32_t xs=vx[lane]>>step,ys=vy[lane]>>step;
                    if(vy[lane]>0){vx[lane]+=ys;vy[lane]-=xs;va[lane]+=delta;}
                    else if(vy[lane]<0){vx[lane]-=ys;vy[lane]+=xs;va[lane]-=delta;}
                }
            }
        }
        for(int lane=0;lane<3;lane++) {
#pragma HLS UNROLL
            const int n=3*group+lane;int32_t angle=va[lane];
            if(angle>tcb_atan2_fp32_detail::PI_FIXED)angle=tcb_atan2_fp32_detail::PI_FIXED;
            if(angle<-tcb_atan2_fp32_detail::PI_FIXED)angle=-tcb_atan2_fp32_detail::PI_FIXED;
            if(n<7)angles[n]=enabled[lane]?tcb_atan2_fp32_detail::scale(angle):special[lane];
        }
    }
}

// Private SRS entry point; see prepare_guarded() contract above.
static void srs_atan2_7_fp32_guarded(const float y[7],const float x[7],float angles[7]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=y complete
#pragma HLS ARRAY_PARTITION variable=x complete
#pragma HLS ARRAY_PARTITION variable=angles complete
    static const int32_t table[28]={210828714,124459457,65760959,33381290,16755422,8385879,4193963,2097109,1048571,524287,262144,131072,65536,32768,16384,8192,4096,2048,1024,512,256,128,64,32,16,8,4,2};
#pragma HLS BIND_STORAGE variable=table type=rom_1p impl=lutram
    int32_t vx[1],vy[1],va[1];float special[1];bool enabled[1];
#pragma HLS ARRAY_PARTITION variable=vx complete
#pragma HLS ARRAY_PARTITION variable=vy complete
#pragma HLS ARRAY_PARTITION variable=va complete
#pragma HLS ARRAY_PARTITION variable=special complete
#pragma HLS ARRAY_PARTITION variable=enabled complete
    F32_GUARDED_ATAN_GROUP: for(int group=0;group<7;group++) {
        for(int lane=0;lane<1;lane++) {
#pragma HLS UNROLL
            const int n=group+lane;
            enabled[lane]=tcb_atan2_fp32_detail::prepare_guarded(n<7?y[n]:0.0f,n<7?x[n]:1.0f,vx[lane],vy[lane],va[lane],special[lane]);
        }
        F32_GUARDED_ATAN_STEPS: for(unsigned step=0;step<28;step++) {
#pragma HLS PIPELINE II=1
            const int32_t delta=table[step];
            for(int lane=0;lane<1;lane++) {
#pragma HLS UNROLL
                if(enabled[lane]){const int32_t xs=vx[lane]>>step,ys=vy[lane]>>step;
                    if(vy[lane]>0){vx[lane]+=ys;vy[lane]-=xs;va[lane]+=delta;}
                    else if(vy[lane]<0){vx[lane]-=ys;vy[lane]+=xs;va[lane]-=delta;}
                }
            }
        }
        for(int lane=0;lane<1;lane++) {
#pragma HLS UNROLL
            const int n=group+lane;int32_t angle=va[lane];
            if(angle>tcb_atan2_fp32_detail::PI_FIXED)angle=tcb_atan2_fp32_detail::PI_FIXED;
            if(angle<-tcb_atan2_fp32_detail::PI_FIXED)angle=-tcb_atan2_fp32_detail::PI_FIXED;
            if(n<7)angles[n]=enabled[lane]?tcb_atan2_fp32_detail::scale(angle):special[lane];
        }
    }
}
