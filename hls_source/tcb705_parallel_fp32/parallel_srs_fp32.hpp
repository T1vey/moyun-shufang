#pragma once
// Experimental controller-DH SRS candidate generator, single-precision geometry.
// The wire model remains FP64 for exact structural validation at load time.
// This generator does not accept motion. Keep independent FK and the original
// position/orientation/step/limit checks before publishing a successful prefix;
// an FP32 candidate that misses those checks must use the existing PS fallback.
#include <cmath>
#include <cstdint>
#include "parallel_atan2_fp32.hpp"

namespace parallel_srs_fp32 {
static const float PI=3.1415926535897932384626433832795f;
// FP32 conditioning guard, selected by offline FP64-oracle tests. This is
// a solver-domain restriction, not a relaxed pose acceptance tolerance.
// Near-singular configurations use the PS general numerical solver.
static const float MIN_CONDITION_SINE=0.05f;
static const float MIN_ELBOW_PROJECTION_RATIO=0.05f;
static const float TWO_PI=6.283185307179586476925286766559f;
static const double PI64=3.1415926535897932384626433832795;
static const double RIGHT_ANGLE_COS=6.123233995736766e-17;
enum Parameter {SHOULDER_Z,UPPER,FOREARM,TOOL_Z,UPPER2,FOREARM2,INV_UPPER,INV_FOREARM,INV_UL,PARAM_COUNT};

static bool finite(float x) {
#pragma HLS INLINE
    union {float f;uint32_t u;} v;v.f=x;
    return (v.u & UINT32_C(0x7f800000))!=UINT32_C(0x7f800000);
}
static bool finite_model(double x) {
#pragma HLS INLINE
    union {double d;uint64_t u;} v;v.d=x;
    return (v.u & UINT64_C(0x7ff0000000000000))!=UINT64_C(0x7ff0000000000000);
}

// Whitelist the original FP64 matrix exactly before narrowing any geometry.
// Unsupported axes, origins or tools are explicit CPU-fallback conditions.
static bool prepare(const double model[147],const double tool[16],
                    float p[PARAM_COUNT],float limits[14]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=p complete
    bool valid=true;
    SRS_SHAPE_JOINTS: for(int k=0;k<7;k++) {
        const int o=21*k;const bool identity=k==0,positive=(k&1)!=0;
        SRS_SHAPE_MATRIX: for(int n=0;n<16;n++) {
#pragma HLS PIPELINE II=1
            const double value=model[o+n];double expected=0.;bool accepted=false;
            if(n==0||n==15)expected=1.;
            else if(n==5||n==10) {
                if(identity)expected=1.;
                else accepted=(value==0.||value==RIGHT_ANGLE_COS);
            } else if(n==6&&!identity)expected=positive?-1.:1.;
            else if(n==9&&!identity)expected=positive?1.:-1.;
            else if(n==11&&positive)accepted=finite_model(value)&&value>0.;
            if(!accepted&&value!=expected)valid=false;
        }
        if(model[o+16]!=0.||model[o+17]!=0.||model[o+18]!=1.)valid=false;
        if(positive&&(!finite_model(model[o+11])||model[o+11]<=0.))valid=false;
        const double lo=model[o+19],hi=model[o+20];
        if(!finite_model(lo)||!finite_model(hi)||lo>=hi||lo < -PI64||hi > PI64)valid=false;
        limits[2*k]=static_cast<float>(lo);limits[2*k+1]=static_cast<float>(hi);
        if(!finite(limits[2*k])||!finite(limits[2*k+1])||limits[2*k]>=limits[2*k+1])valid=false;
    }
    SRS_TOOL_SHAPE: for(int n=0;n<16;n++) {
#pragma HLS PIPELINE II=1
        if(n==11){if(!finite_model(tool[n]))valid=false;}
        else if(tool[n]!=(n%5==0?1.:0.))valid=false;
    }
    if(!valid)return false;
    p[SHOULDER_Z]=static_cast<float>(model[21+11]);p[UPPER]=static_cast<float>(model[3*21+11]);
    p[FOREARM]=static_cast<float>(model[5*21+11]);p[TOOL_Z]=static_cast<float>(tool[11]);
    if(!finite(p[SHOULDER_Z])||!finite(p[UPPER])||!finite(p[FOREARM])||!finite(p[TOOL_Z])||
       p[SHOULDER_Z]<=0.0f||p[UPPER]<=0.0f||p[FOREARM]<=0.0f)return false;
    p[UPPER2]=p[UPPER]*p[UPPER];p[FOREARM2]=p[FOREARM]*p[FOREARM];
    p[INV_UPPER]=1.0f/p[UPPER];p[INV_FOREARM]=1.0f/p[FOREARM];
    p[INV_UL]=p[INV_UPPER]*p[INV_FOREARM];
    for(int k=0;k<PARAM_COUNT;k++)if(!finite(p[k]))return false;
    return true;
}

// Session initialization / successful-general-IK fallback only. Reuse the
// existing sincos7 result; no additional trigonometric IP is introduced here.
// Although the shoulder has three axes, its elbow position depends only on q0/q1.
static void seed_elbow_from_trig(const float p[PARAM_COUNT],const float sn[7],
                                 const float cs[7],float elbow[3]) {
#pragma HLS INLINE
    const float lateral=-p[UPPER]*sn[1];
    elbow[0]=lateral*cs[0];elbow[1]=lateral*sn[0];
    elbow[2]=p[SHOULDER_Z]+p[UPPER]*cs[1];
}

// Model limits are inside [-pi,pi]; generated branch angles are in [-pi,2pi].
// One wrap suffices, except that exact +/-pi have two allowed representations.
static bool legal_angle(float raw,float previous,float lo,float hi,float& chosen) {
#pragma HLS INLINE
    if(raw>PI)raw-=TWO_PI;else if(raw < -PI)raw+=TWO_PI;
    bool found=raw>=lo&&raw<=hi;chosen=raw;
    if(raw==PI||raw == -PI) {
        const float other=-raw;
        if(other>=lo&&other<=hi&&(!found||fabsf(other-previous)<fabsf(raw-previous))) {
            chosen=other;found=true;
        }
    }
    return found;
}

// Return 0: an unaccepted candidate is available; return 1: use general IK.
// previous_elbow belongs to the preceding candidate in this producer sequence,
// for this exact model. All such states remain speculative: only the consumer's
// independently verified prefix may be published. A rejected predecessor
// invalidates every later candidate; on return 1 no output may be committed.
static int geometry_pairs(const float p[PARAM_COUNT],const float target[16],
                     float previous_elbow_angle,const float previous_elbow[3],
                     float angle_y[7],float angle_x[7],float next_elbow[3]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=p complete
#pragma HLS ARRAY_PARTITION variable=target complete
#pragma HLS ARRAY_PARTITION variable=previous_elbow complete
#pragma HLS ARRAY_PARTITION variable=angle_y complete
#pragma HLS ARRAY_PARTITION variable=angle_x complete
#pragma HLS ARRAY_PARTITION variable=next_elbow complete
#pragma HLS ALLOCATION operation instances=fmul limit=4
#pragma HLS ALLOCATION operation instances=fadd limit=2
#pragma HLS ALLOCATION operation instances=fsub limit=2
#pragma HLS ALLOCATION operation instances=fdiv limit=1
#pragma HLS ALLOCATION operation instances=fsqrt limit=1
    if(!finite(previous_elbow_angle)||fabsf(previous_elbow_angle)<MIN_CONDITION_SINE)return 1;
    float sw[3],u[3],old_e[3],v[3],z[3],x[3],y[3],rs[9];
#pragma HLS ARRAY_PARTITION variable=sw complete
#pragma HLS ARRAY_PARTITION variable=u complete
#pragma HLS ARRAY_PARTITION variable=old_e complete
#pragma HLS ARRAY_PARTITION variable=v complete
#pragma HLS ARRAY_PARTITION variable=z complete
#pragma HLS ARRAY_PARTITION variable=x complete
#pragma HLS ARRAY_PARTITION variable=y complete
#pragma HLS ARRAY_PARTITION variable=rs complete
    SRS_INPUT: for(int r=0;r<3;r++) {
#pragma HLS PIPELINE II=1
        sw[r]=target[4*r+3]-p[TOOL_Z]*target[4*r+2]-(r==2?p[SHOULDER_Z]:0.f);
        old_e[r]=previous_elbow[r]-(r==2?p[SHOULDER_Z]:0.f);
    }
    const float D2=(sw[0]*sw[0]+sw[1]*sw[1])+sw[2]*sw[2];
    const float D=sqrtf(D2),U=p[UPPER],L=p[FOREARM];
    if(!finite(D)||D<=fabsf(U-L)+1e-9f||D>=U+L-1e-9f)return 1;
    const float inverse_D=1.f/D;
    const float a=((p[UPPER2]-p[FOREARM2])+D2)*(.5f*inverse_D);
    const float h2=p[UPPER2]-a*a;
    if(!finite(h2)||h2<=1e-16f)return 1;
    const float h=sqrtf(h2);
    const float c3=((D2-p[UPPER2])-p[FOREARM2])*(.5f*p[INV_UL]);
    const float s3=(previous_elbow_angle>0.f?1.f:-1.f)*(D*h)*p[INV_UL];
    if(!finite(s3)||fabsf(s3)<MIN_CONDITION_SINE)return 1;
    SRS_DIRECTION: for(int r=0;r<3;r++) {
#pragma HLS PIPELINE II=1
        u[r]=sw[r]*inverse_D;
    }
    const float projection=(old_e[0]*u[0]+old_e[1]*u[1])+old_e[2]*u[2];
    SRS_PROJECT_ELBOW: for(int r=0;r<3;r++) {
#pragma HLS PIPELINE II=1
        v[r]=old_e[r]-u[r]*projection;
    }
    const float norm_v=sqrtf((v[0]*v[0]+v[1]*v[1])+v[2]*v[2]);
    if(!finite(norm_v)||norm_v<MIN_ELBOW_PROJECTION_RATIO*p[UPPER])return 1;
    const float scale_v=h/norm_v,inverse_s3=1.f/s3;
    SRS_NEW_ELBOW: for(int r=0;r<3;r++) {
#pragma HLS PIPELINE II=1
        const float e=u[r]*a+v[r]*scale_v;
        next_elbow[r]=e+(r==2?p[SHOULDER_Z]:0.f);
        z[r]=e*p[INV_UPPER];
        const float lower=(sw[r]-e)*p[INV_FOREARM];
        x[r]=(c3*z[r]-lower)*inverse_s3;
    }
    SRS_SHOULDER_MATRIX: for(int r=0;r<3;r++) {
#pragma HLS PIPELINE II=1
        const int i=(r+1)%3,j=(r+2)%3;
        y[r]=z[i]*x[j]-z[j]*x[i];
        rs[3*r]=x[r];rs[3*r+1]=y[r];rs[3*r+2]=z[r];
    }
    // Only five wrist entries are required for ZYZ decomposition. Computing
    // these directly avoids forming two full 3x3 matrix products.
    float xR[3],zR[3];
#pragma HLS ARRAY_PARTITION variable=xR complete
#pragma HLS ARRAY_PARTITION variable=zR complete
    SRS_WRIST_COLUMNS: for(int c=0;c<3;c++) {
#pragma HLS PIPELINE II=1
        xR[c]=(x[0]*target[c]+x[1]*target[4+c])+x[2]*target[8+c];
        zR[c]=(z[0]*target[c]+z[1]*target[4+c])+z[2]*target[8+c];
    }
    const float w02=c3*xR[2]+s3*zR[2];
    const float w12=(y[0]*target[2]+y[1]*target[6])+y[2]*target[10];
    const float w20=-s3*xR[0]+c3*zR[0];
    const float w21=-s3*xR[1]+c3*zR[1];
    const float w22=-s3*xR[2]+c3*zR[2];
    const float shoulder_sine=sqrtf(rs[2]*rs[2]+rs[5]*rs[5]);
    const float wrist_sine=sqrtf(w02*w02+w12*w12);
    if(!finite(shoulder_sine)||!finite(wrist_sine)||shoulder_sine<MIN_CONDITION_SINE||wrist_sine<MIN_CONDITION_SINE)return 1;
    angle_y[0]=rs[5];angle_y[1]=shoulder_sine;angle_y[2]=rs[7];angle_y[3]=s3;
    angle_y[4]=w12;angle_y[5]=wrist_sine;angle_y[6]=w21;
    angle_x[0]=rs[2];angle_x[1]=rs[8];angle_x[2]=-rs[6];angle_x[3]=c3;
    angle_x[4]=w02;angle_x[5]=w22;angle_x[6]=-w20;
    return 0;
}

static int select_branch(const float angles[7],const float limits[14],
                         const float previous[7],float maximum_joint_step,float q[7]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=angles complete
#pragma HLS ARRAY_PARTITION variable=previous complete
#pragma HLS ARRAY_PARTITION variable=q complete
#pragma HLS ALLOCATION operation instances=fmul limit=1
#pragma HLS ALLOCATION operation instances=fadd limit=1
#pragma HLS ALLOCATION operation instances=fsub limit=1
    if(!finite(maximum_joint_step)||maximum_joint_step<=0.f)return 1;
    float angle[7];
#pragma HLS ARRAY_PARTITION variable=angle complete
    SRS_ANGLE_FINITE: for(int k=0;k<7;k++) {
#pragma HLS PIPELINE II=1
        angle[k]=(k==1||k==5)?-angles[k]:angles[k];
        if(!finite(angle[k]))return 1;
    }
    float elbow=0.f;
    if(!legal_angle(angle[3],previous[3],limits[6],limits[7],elbow)||
       !finite(previous[3])||fabsf(elbow-previous[3])>maximum_joint_step)return 1;
    q[3]=elbow;
    // The four shoulder/wrist combinations have separable costs and independent
    // per-joint limits. Pick the best of two shoulder and two wrist branches:
    // exactly the same global minimum, with 13 rather than 28 joint checks.
    SRS_BRANCH_GROUPS: for(int group=0;group<2;group++) {
      const int first=group?4:0;bool found=false;float best=1e30f;
      SRS_BRANCHES: for(int branch=0;branch<2;branch++) {
        float values[3];
#pragma HLS ARRAY_PARTITION variable=values complete
        bool legal=true;float cost=0.f;
        SRS_BRANCH_JOINTS: for(int index=0;index<3;index++) {
            const int k=first+index;
            const float raw=index==1?(branch?-angle[k]:angle[k]):angle[k]+branch*PI;
            float chosen=0.f;
            if(!legal_angle(raw,previous[k],limits[2*k],limits[2*k+1],chosen))legal=false;
            values[index]=chosen;const float delta=chosen-previous[k];
            if(!finite(delta)||fabsf(delta)>maximum_joint_step)legal=false;
            cost+=delta*delta;
        }
        if(legal&&cost<best) {
            found=true;best=cost;
            SRS_SAVE_BRANCH: for(int k=0;k<3;k++) {
#pragma HLS PIPELINE II=1
                q[first+k]=values[k];
            }
        }
      }
      if(!found)return 1;
    }
    return 0;
}

// Producer convenience wrapper. The surrounding DATAFLOW consumer validates
// and commits a prefix in order; this API alone does not accept a trajectory.
static int candidate(const float p[PARAM_COUNT],const float limits[14],
                     const float target[16],const float previous[7],
                     const float previous_elbow[3],float maximum_joint_step,
                     float q[7],float next_elbow[3]) {
#pragma HLS INLINE off
    float angle_y[7],angle_x[7],angles[7];
#pragma HLS ARRAY_PARTITION variable=angle_y complete
#pragma HLS ARRAY_PARTITION variable=angle_x complete
#pragma HLS ARRAY_PARTITION variable=angles complete
    if(geometry_pairs(p,target,previous[3],previous_elbow,angle_y,angle_x,next_elbow))return 1;
    srs_atan2_7_fp32(angle_y,angle_x,angles);
    return select_branch(angles,limits,previous,maximum_joint_step,q);
}
} // namespace parallel_srs_fp32
