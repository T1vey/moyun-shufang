#pragma once
// Experimental controller-DH SRS candidate generator. FP64 geometry throughout.
// This file neither accepts an IK point nor updates the execution/session state.
// The caller MUST run the original FK on the resulting seven actual angles and
// enforce its original position/orientation limits before committing q/elbow.
#include <cmath>
#include <cstdint>
#include "parallel_atan2.hpp"

namespace parallel_srs {
static const double PI=3.1415926535897932384626433832795;
static const double TWO_PI=6.283185307179586476925286766559;
static const double RIGHT_ANGLE_COS=6.123233995736766e-17;
enum Parameter {SHOULDER_Z,UPPER,FOREARM,TOOL_Z,UPPER2,FOREARM2,INV_UPPER,INV_FOREARM,INV_UL,PARAM_COUNT};

static bool finite(double x) {
#pragma HLS INLINE
    union {double d;uint64_t u;} v;v.d=x;
    return (v.u & UINT64_C(0x7ff0000000000000))!=UINT64_C(0x7ff0000000000000);
}

// Exact shape whitelist, evaluated once per loaded model. The tiny stored
// cos(pi/2) is allowed explicitly, never silently rounded in the original FK.
// Nonzero origin offsets, geometry corrections outside this SRS structure,
// rotated/off-axis tools, alternate joint axes, or wider angle conventions
// return false and retain the PS-side general numerical IK fallback.
static bool prepare(const double model[147],const double tool[16],
                    double p[PARAM_COUNT],double limits[14]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=p complete
    bool valid=true;
    SRS_SHAPE_JOINTS: for(int k=0;k<7;k++) {
        const int o=21*k;
        const bool identity=k==0;
        const bool positive=(k&1)!=0;
        SRS_SHAPE_MATRIX: for(int n=0;n<16;n++) {
#pragma HLS PIPELINE II=1
            const double value=model[o+n];double expected=0.;bool accepted=false;
            if(n==0||n==15)expected=1.;
            else if(n==5||n==10) {
                if(identity)expected=1.;
                else accepted=(value==0.||value==RIGHT_ANGLE_COS);
            } else if(n==6&&!identity)expected=positive?-1.:1.;
            else if(n==9&&!identity)expected=positive?1.:-1.;
            else if(n==11&&positive)accepted=finite(value)&&value>0.;
            if(!accepted&&value!=expected)valid=false;
        }
        if(model[o+16]!=0.||model[o+17]!=0.||model[o+18]!=1.)valid=false;
        if(positive&&(!finite(model[o+11])||model[o+11]<=0.))valid=false;
        const double lo=model[o+19],hi=model[o+20];
        if(!finite(lo)||!finite(hi)||lo>=hi||lo < -PI||hi > PI)valid=false;
        limits[2*k]=lo;limits[2*k+1]=hi;
    }
    SRS_TOOL_SHAPE: for(int n=0;n<16;n++) {
#pragma HLS PIPELINE II=1
        if(n==11){if(!finite(tool[n]))valid=false;}
        else if(tool[n]!=(n%5==0?1.:0.))valid=false;
    }
    if(!valid)return false;
    p[SHOULDER_Z]=model[21+11];p[UPPER]=model[3*21+11];
    p[FOREARM]=model[5*21+11];p[TOOL_Z]=tool[11];
    p[UPPER2]=p[UPPER]*p[UPPER];p[FOREARM2]=p[FOREARM]*p[FOREARM];
    p[INV_UPPER]=1./p[UPPER];p[INV_FOREARM]=1./p[FOREARM];
    p[INV_UL]=p[INV_UPPER]*p[INV_FOREARM];
    return true;
}

// Session initialization / successful-general-IK fallback only. Reuse the
// existing sincos7 result; no additional trigonometric IP is introduced here.
// Although the shoulder has three axes, its elbow position depends only on q0/q1.
static void seed_elbow_from_trig(const double p[PARAM_COUNT],const double sn[7],
                                 const double cs[7],double elbow[3]) {
#pragma HLS INLINE
    const double lateral=-p[UPPER]*sn[1];
    elbow[0]=lateral*cs[0];elbow[1]=lateral*sn[0];
    elbow[2]=p[SHOULDER_Z]+p[UPPER]*cs[1];
}

// Model limits are inside [-pi,pi]; generated branch angles are in [-pi,2pi].
// One wrap suffices, except that exact +/-pi have two allowed representations.
static bool legal_angle(double raw,double previous,double lo,double hi,double& chosen) {
#pragma HLS INLINE
    if(raw>PI)raw-=TWO_PI;else if(raw < -PI)raw+=TWO_PI;
    bool found=raw>=lo&&raw<=hi;chosen=raw;
    if(raw==PI||raw == -PI) {
        const double other=-raw;
        if(other>=lo&&other<=hi&&(!found||std::abs(other-previous)<std::abs(raw-previous))) {
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
static int geometry_pairs(const double p[PARAM_COUNT],const double target[16],
                     double previous_elbow_angle,const double previous_elbow[3],
                     double angle_y[7],double angle_x[7],double next_elbow[3]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=p complete
#pragma HLS ARRAY_PARTITION variable=target complete
#pragma HLS ARRAY_PARTITION variable=previous_elbow complete
#pragma HLS ARRAY_PARTITION variable=angle_y complete
#pragma HLS ARRAY_PARTITION variable=angle_x complete
#pragma HLS ARRAY_PARTITION variable=next_elbow complete
#pragma HLS ALLOCATION operation instances=dmul limit=4
#pragma HLS ALLOCATION operation instances=dadd limit=2
#pragma HLS ALLOCATION operation instances=dsub limit=2
#pragma HLS ALLOCATION operation instances=ddiv limit=1
#pragma HLS ALLOCATION operation instances=dsqrt limit=1
    if(!finite(previous_elbow_angle)||std::abs(previous_elbow_angle)<1e-5)return 1;
    double sw[3],u[3],old_e[3],v[3],z[3],x[3],y[3],rs[9];
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
        sw[r]=target[4*r+3]-p[TOOL_Z]*target[4*r+2]-(r==2?p[SHOULDER_Z]:0.);
        old_e[r]=previous_elbow[r]-(r==2?p[SHOULDER_Z]:0.);
    }
    const double D2=(sw[0]*sw[0]+sw[1]*sw[1])+sw[2]*sw[2];
    const double D=std::sqrt(D2),U=p[UPPER],L=p[FOREARM];
    if(!finite(D)||D<=std::abs(U-L)+1e-9||D>=U+L-1e-9)return 1;
    const double inverse_D=1./D;
    const double a=((p[UPPER2]-p[FOREARM2])+D2)*(.5*inverse_D);
    const double h2=p[UPPER2]-a*a;
    if(!finite(h2)||h2<=1e-16)return 1;
    const double h=std::sqrt(h2);
    const double c3=((D2-p[UPPER2])-p[FOREARM2])*(.5*p[INV_UL]);
    const double s3=(previous_elbow_angle>0.?1.:-1.)*(D*h)*p[INV_UL];
    if(!finite(s3)||std::abs(s3)<1e-5)return 1;
    SRS_DIRECTION: for(int r=0;r<3;r++) {
#pragma HLS PIPELINE II=1
        u[r]=sw[r]*inverse_D;
    }
    const double projection=(old_e[0]*u[0]+old_e[1]*u[1])+old_e[2]*u[2];
    SRS_PROJECT_ELBOW: for(int r=0;r<3;r++) {
#pragma HLS PIPELINE II=1
        v[r]=old_e[r]-u[r]*projection;
    }
    const double norm_v=std::sqrt((v[0]*v[0]+v[1]*v[1])+v[2]*v[2]);
    if(!finite(norm_v)||norm_v<1e-8)return 1;
    const double scale_v=h/norm_v,inverse_s3=1./s3;
    SRS_NEW_ELBOW: for(int r=0;r<3;r++) {
#pragma HLS PIPELINE II=1
        const double e=u[r]*a+v[r]*scale_v;
        next_elbow[r]=e+(r==2?p[SHOULDER_Z]:0.);
        z[r]=e*p[INV_UPPER];
        const double lower=(sw[r]-e)*p[INV_FOREARM];
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
    double xR[3],zR[3];
#pragma HLS ARRAY_PARTITION variable=xR complete
#pragma HLS ARRAY_PARTITION variable=zR complete
    SRS_WRIST_COLUMNS: for(int c=0;c<3;c++) {
#pragma HLS PIPELINE II=1
        xR[c]=(x[0]*target[c]+x[1]*target[4+c])+x[2]*target[8+c];
        zR[c]=(z[0]*target[c]+z[1]*target[4+c])+z[2]*target[8+c];
    }
    const double w02=c3*xR[2]+s3*zR[2];
    const double w12=(y[0]*target[2]+y[1]*target[6])+y[2]*target[10];
    const double w20=-s3*xR[0]+c3*zR[0];
    const double w21=-s3*xR[1]+c3*zR[1];
    const double w22=-s3*xR[2]+c3*zR[2];
    const double shoulder_sine=std::sqrt(rs[2]*rs[2]+rs[5]*rs[5]);
    const double wrist_sine=std::sqrt(w02*w02+w12*w12);
    if(!finite(shoulder_sine)||!finite(wrist_sine)||shoulder_sine<1e-5||wrist_sine<1e-5)return 1;
    angle_y[0]=rs[5];angle_y[1]=shoulder_sine;angle_y[2]=rs[7];angle_y[3]=s3;
    angle_y[4]=w12;angle_y[5]=wrist_sine;angle_y[6]=w21;
    angle_x[0]=rs[2];angle_x[1]=rs[8];angle_x[2]=-rs[6];angle_x[3]=c3;
    angle_x[4]=w02;angle_x[5]=w22;angle_x[6]=-w20;
    return 0;
}

static int select_branch(const double angles[7],const double limits[14],
                         const double previous[7],double maximum_joint_step,double q[7]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=angles complete
#pragma HLS ARRAY_PARTITION variable=previous complete
#pragma HLS ARRAY_PARTITION variable=q complete
#pragma HLS ALLOCATION operation instances=dmul limit=1
#pragma HLS ALLOCATION operation instances=dadd limit=1
#pragma HLS ALLOCATION operation instances=dsub limit=1
    if(!finite(maximum_joint_step)||maximum_joint_step<=0.)return 1;
    double angle[7];
#pragma HLS ARRAY_PARTITION variable=angle complete
    SRS_ANGLE_FINITE: for(int k=0;k<7;k++) {
#pragma HLS PIPELINE II=1
        angle[k]=(k==1||k==5)?-angles[k]:angles[k];
        if(!finite(angle[k]))return 1;
    }
    double elbow=0.;
    if(!legal_angle(angle[3],previous[3],limits[6],limits[7],elbow)||
       !finite(previous[3])||std::abs(elbow-previous[3])>maximum_joint_step)return 1;
    q[3]=elbow;
    // The four shoulder/wrist combinations have separable costs and independent
    // per-joint limits. Pick the best of two shoulder and two wrist branches:
    // exactly the same global minimum, with 13 rather than 28 joint checks.
    SRS_BRANCH_GROUPS: for(int group=0;group<2;group++) {
      const int first=group?4:0;bool found=false;double best=1e100;
      SRS_BRANCHES: for(int branch=0;branch<2;branch++) {
        double values[3];
#pragma HLS ARRAY_PARTITION variable=values complete
        bool legal=true;double cost=0.;
        SRS_BRANCH_JOINTS: for(int index=0;index<3;index++) {
            const int k=first+index;
            const double raw=index==1?(branch?-angle[k]:angle[k]):angle[k]+branch*PI;
            double chosen=0.;
            if(!legal_angle(raw,previous[k],limits[2*k],limits[2*k+1],chosen))legal=false;
            values[index]=chosen;const double delta=chosen-previous[k];
            if(!finite(delta)||std::abs(delta)>maximum_joint_step)legal=false;
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
static int candidate(const double p[PARAM_COUNT],const double limits[14],
                     const double target[16],const double previous[7],
                     const double previous_elbow[3],double maximum_joint_step,
                     double q[7],double next_elbow[3]) {
#pragma HLS INLINE off
    double angle_y[7],angle_x[7],angles[7];
#pragma HLS ARRAY_PARTITION variable=angle_y complete
#pragma HLS ARRAY_PARTITION variable=angle_x complete
#pragma HLS ARRAY_PARTITION variable=angles complete
    if(geometry_pairs(p,target,previous[3],previous_elbow,angle_y,angle_x,next_elbow))return 1;
    srs_atan2_7(angle_y,angle_x,angles);
    return select_branch(angles,limits,previous,maximum_joint_step,q);
}
} // namespace parallel_srs
