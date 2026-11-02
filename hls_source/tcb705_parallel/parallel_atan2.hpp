#pragma once
#include <cstdint>

// Three integer CORDIC lanes, shared by seven angles in three batches.
// Values use a signed int64_t carrier and 54 fractional bits. All coordinate
// and angle intermediates fit the Q4.54 range [-8,8); the wider carrier retains
// guard bits. No floating-point trig, division, or multiplication is required
// before the final exactly representable 2^-54 output scaling.
namespace tcb_atan2_detail {
static const int64_t kPi = 56593902016227522LL;
static const double kScale = 5.5511151231257827021181583404541015625e-17;
static const double kPiDouble = 3.141592653589793238462643383279502884;

static uint64_t bits_of(double x) {
#pragma HLS INLINE
    union { double d; uint64_t u; } b;
    b.d=x; return b.u;
}
static double double_of(uint64_t x) {
#pragma HLS INLINE
    union { double d; uint64_t u; } b;
    b.u=x; return b.d;
}

// C++14 signed right shift is implementation-defined. Both the host compiler
// and Vitis HLS use arithmetic shift. Refuse unsupported compiler semantics
// rather than silently obtaining a different vectoring algorithm. The test
// independently compares this operation with defined mathematical floor(v/2^n).
static_assert((-1LL >> 1) == -1LL, "CORDIC requires arithmetic signed right shift");
static int64_t asr(int64_t x, unsigned int shift) {
#pragma HLS INLINE
    return x >> shift; // All callers use 0 <= shift < 48.
}

static uint64_t significand(uint64_t bits) {
#pragma HLS INLINE
    const uint64_t fraction=bits & 0x000fffffffffffffULL;
    return fraction | (((bits >> 52) & 2047ULL) ? 0x0010000000000000ULL : 0ULL);
}

static bool prepare(double y, double x, int64_t &fx, int64_t &fy,
                    int64_t &angle, double &special) {
#pragma HLS INLINE
    const uint64_t xb=bits_of(x), yb=bits_of(y);
    const unsigned ex=unsigned((xb >> 52) & 2047ULL);
    const unsigned ey=unsigned((yb >> 52) & 2047ULL);
    const uint64_t xm=significand(xb), ym=significand(yb);
    const bool sx=(xb >> 63)!=0, sy=(yb >> 63)!=0;
    fx=0; fy=0; angle=0;
    special=double_of(0x7ff8000000000000ULL);
    // Caller rejects NaNs, infinities, and tiny norms before IK. Retain an
    // explicit invalid result here, including the undefined atan2(0,0).
    if(ex==2047 || ey==2047 || (xm==0 && ym==0)) return false;
    if(ym==0) {
        special=sx ? (sy ? -kPiDouble : kPiDouble) : y;
        return false;
    }
    if(xm==0) {
        special=sy ? -kPiDouble*0.5 : kPiDouble*0.5;
        return false;
    }
    uint64_t ux,uy;
    if(ex==0 && ey==0) {
        // Also support subnormal pairs: move the largest significant bit to
        // bit 53. Values remain exact integers; no underflow or FP operations.
        const uint64_t maximum=xm>ym ? xm : ym;
        unsigned highest=0;
        SUBNORMAL_LEADING_BIT: for(unsigned b=0;b<52;++b) {
#pragma HLS UNROLL
            if((maximum >> b) & 1ULL) highest=b;
        }
        ux=xm << (53-highest); uy=ym << (53-highest);
    } else {
        // A normal double is mantissa * 2^(exponent-1075); subnormals use
        // effective exponent 1 without an implicit leading one. Common binary
        // scaling sets max(|fx|,|fy|) in [2^53,2^54). Quantization therefore
        // depends on direction, never on the original (possibly tiny) norm.
        const unsigned efx=ex ? ex : 1, efy=ey ? ey : 1;
        const unsigned maximum=efx>efy ? efx : efy;
        const unsigned dx=maximum-efx, dy=maximum-efy;
        ux=dx<64 ? (xm << 1) >> dx : 0;
        uy=dy<64 ? (ym << 1) >> dy : 0;
    }
    fx=sx ? -int64_t(ux) : int64_t(ux);
    fy=sy ? -int64_t(uy) : int64_t(uy);
    if(sx) {
        fx=-fx; fy=-fy;
        angle=sy ? -kPi : kPi;
    }
    return true;
}
// Exact power-of-two scaling after rounded int64-to-double conversion.
// Nonzero int64 magnitudes have binary exponent 0..63, encoded as 1023..1086.
// Subtracting 54 leaves encoded exponent 969..1032, always normal and finite.
// The angle-specific range is smaller: abs(integer) <= kPi < 2^56.
static double fixed_to_double(int64_t value) {
#pragma HLS INLINE
    if(value==0) return 0.0;
    const double integer=double(value);
    const uint64_t bits=bits_of(integer);
    return double_of(bits-(54ULL << 52));
}
} // namespace tcb_atan2_detail

// Contract: arbitrary finite, nonzero (x,y) is supported. NaN, infinity and
// (signed) double zero return quiet NaN. Exact axes preserve atan2 signed-zero
// conventions. The IK caller additionally applies its singularity/norm guard.
// Maximum coordinate magnitude after 48 vectoring steps is bounded by
// sqrt(2)*1.646761 < 2.33 plus <1e-14 quantization; angle magnitude before
// clamping is < pi + sum(atan(2^-i)) < 4.89. Thus no signed overflow is possible.
static void srs_atan2_7(const double y[7], const double x[7], double angles[7]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=y complete
#pragma HLS ARRAY_PARTITION variable=x complete
#pragma HLS ARRAY_PARTITION variable=angles complete
    static const int64_t table[48]={
        14148475504056881LL,8352332796509007LL,4413143263887471LL,2240180428409819LL,
        1124437317754813LL,562766808782690LL,281452073573269LL,140734625148650LL,
        70368386266999LL,35184327349692LL,17592180452014LL,8796092323157LL,
        4398046423723LL,2199023244629LL,1099511626411LL,549755813717LL,
        274877906923LL,137438953469LL,68719476736LL,34359738368LL,
        17179869184LL,8589934592LL,4294967296LL,2147483648LL,
        1073741824LL,536870912LL,268435456LL,134217728LL,
        67108864LL,33554432LL,16777216LL,8388608LL,
        4194304LL,2097152LL,1048576LL,524288LL,
        262144LL,131072LL,65536LL,32768LL,
        16384LL,8192LL,4096LL,2048LL,1024LL,512LL,256LL,128LL
    };
#pragma HLS BIND_STORAGE variable=table type=rom_1p impl=lutram
    int64_t vx[3],vy[3],va[3];
    double special[3];
    bool enabled[3];
#pragma HLS ARRAY_PARTITION variable=vx complete
#pragma HLS ARRAY_PARTITION variable=vy complete
#pragma HLS ARRAY_PARTITION variable=va complete
#pragma HLS ARRAY_PARTITION variable=special complete
#pragma HLS ARRAY_PARTITION variable=enabled complete
    ATAN_GROUP: for(int group=0;group<3;++group) {
        ATAN_PREPARE: for(int lane=0;lane<3;++lane) {
#pragma HLS UNROLL
            const int n=group*3+lane;
            enabled[lane]=tcb_atan2_detail::prepare(n<7 ? y[n] : 0.0,
                n<7 ? x[n] : 1.0,vx[lane],vy[lane],va[lane],special[lane]);
        }
        ATAN_ITERATE: for(unsigned step=0;step<48;++step) {
#pragma HLS PIPELINE II=1
            const int64_t delta=table[step];
            ATAN_LANE: for(int lane=0;lane<3;++lane) {
#pragma HLS UNROLL
                if(enabled[lane]) {
                    const int64_t xs=tcb_atan2_detail::asr(vx[lane],step);
                    const int64_t ys=tcb_atan2_detail::asr(vy[lane],step);
                    if(vy[lane]>0) {
                        vx[lane]+=ys; vy[lane]-=xs; va[lane]+=delta;
                    } else if(vy[lane]<0) {
                        vx[lane]-=ys; vy[lane]+=xs; va[lane]-=delta;
                    }
                }
            }
        }
        ATAN_OUTPUT: for(int lane=0;lane<3;++lane) {
#pragma HLS UNROLL
            const int n=group*3+lane;
            int64_t clipped=va[lane];
            // Preserve the input quadrant at the branch cut. Tiny rounding
            // overshoots must not turn +pi into -pi (or vice versa).
            if(clipped>tcb_atan2_detail::kPi) clipped=tcb_atan2_detail::kPi;
            if(clipped<-tcb_atan2_detail::kPi) clipped=-tcb_atan2_detail::kPi;
            if(n<7) angles[n]=enabled[lane] ? tcb_atan2_detail::fixed_to_double(clipped) : special[lane];
        }
    }
}
