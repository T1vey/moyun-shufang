#include "ik_step.h"
#include "ik_math.h"

extern "C" int z20_ik_step(
    const float q[5], const float target_position[3], const float target_axis[3],
    const float weights[6], const float scales[6], const float tool[3],
    const float tool_axis[3], const float limits[10], float mu, float max_step,
    int mode, float dq[5], float q_next[5], float error[6],
    float *position_error, float *tilt_error, unsigned int *abi_version) {
#pragma HLS INTERFACE s_axilite port=q bundle=control
#pragma HLS INTERFACE s_axilite port=target_position bundle=control
#pragma HLS INTERFACE s_axilite port=target_axis bundle=control
#pragma HLS INTERFACE s_axilite port=weights bundle=control
#pragma HLS INTERFACE s_axilite port=scales bundle=control
#pragma HLS INTERFACE s_axilite port=tool bundle=control
#pragma HLS INTERFACE s_axilite port=tool_axis bundle=control
#pragma HLS INTERFACE s_axilite port=limits bundle=control
#pragma HLS INTERFACE s_axilite port=abi_version bundle=control
#pragma HLS INTERFACE s_axilite port=mu bundle=control
#pragma HLS INTERFACE s_axilite port=max_step bundle=control
#pragma HLS INTERFACE s_axilite port=mode bundle=control
#pragma HLS INTERFACE s_axilite port=dq bundle=control
#pragma HLS INTERFACE s_axilite port=q_next bundle=control
#pragma HLS INTERFACE s_axilite port=error bundle=control
#pragma HLS INTERFACE s_axilite port=position_error bundle=control
#pragma HLS INTERFACE s_axilite port=tilt_error bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    *abi_version=0x534F0202u;
    for (int i=0;i<5;++i) { dq[i]=0; q_next[i]=finite_value(q[i])?q[i]:0; }
    for (int i=0;i<6;++i) error[i]=0;
    *position_error=0; *tilt_error=0;
    if (!finite_value(mu) || mu<=0 || !finite_value(max_step) || max_step<=0 ||
        (mode!=0 && mode!=1)) return 1;
    float axis_norm=0;
    for (int i=0;i<3;++i) axis_norm += target_axis[i]*target_axis[i];
    axis_norm=std::sqrt(axis_norm);
    if (!finite_value(axis_norm) || axis_norm<0.999f || axis_norm>1.001f) return 1;
    for (int i=0;i<5;++i) if (!finite_value(q[i]) || !finite_value(limits[2*i]) ||
        !finite_value(limits[2*i+1]) || limits[2*i]>=limits[2*i+1] ||
        q[i]<limits[2*i] || q[i]>limits[2*i+1]) return 1;
    for (int i=0;i<6;++i) if (!finite_value(weights[i]) || weights[i]<0 || !finite_value(scales[i]) || scales[i]<=0) return 1;
    for (int i=0;i<3;++i) if (!finite_value(target_position[i]) || !finite_value(target_axis[i]) ||
        !finite_value(tool[i]) || !finite_value(tool_axis[i])) return 1;
    if(std::fabs(dot3(tool_axis,tool_axis)-1)>1e-5f ||
        std::fabs(dot3(target_axis,target_axis)-1)>1e-5f) return 1;

    float tip[3], current_axis[3], geometric[6][5];
#pragma HLS ARRAY_PARTITION variable=tip complete
#pragma HLS ARRAY_PARTITION variable=current_axis complete
#pragma HLS ARRAY_PARTITION variable=geometric complete dim=0
    task_geometry(q,tool,tool_axis,tip,current_axis,geometric);
    float cross_axis[3]; cross3(target_axis,current_axis,cross_axis);
#pragma HLS ARRAY_PARTITION variable=cross_axis complete
    *position_error=0;
    for (int i=0;i<3;++i) { error[i]=target_position[i]-tip[i]; *position_error += error[i]*error[i]; }
    *position_error=std::sqrt(*position_error);
    for (int i=0;i<3;++i) error[i+3]=target_axis[i]-current_axis[i];
    *tilt_error=std::atan2(std::sqrt(dot3(cross_axis,cross_axis)),dot3(target_axis,current_axis));
    float j[6][5], a[5][5]={{0}}, b[5]={0};
    double js[6][5], es[6];
#pragma HLS ARRAY_PARTITION variable=j complete dim=0
#pragma HLS ARRAY_PARTITION variable=js complete dim=0
#pragma HLS ARRAY_PARTITION variable=es complete
#pragma HLS ARRAY_PARTITION variable=a complete dim=0
#pragma HLS ARRAY_PARTITION variable=b complete
    if(!finite_value(*position_error)||!finite_value(*tilt_error)) return 2;
    for (int r=0;r<6;++r) { es[r]=double(error[r])*scales[r]; for (int c=0;c<5;++c) { j[r][c]=geometric[r][c]; js[r][c]=double(j[r][c])*scales[r]; } }
    for (int i=0;i<5;++i) for (int k=0;k<=i;++k) {
        double acc=0;
        for (int r=0;r<6;++r) acc += js[r][i]*(mode==0?weights[r]:1.0f)*js[r][k];
        if (i==k) acc += mu;
        if(!(acc<=FLT_MAX && acc>=-FLT_MAX)) return 2;
        a[i][k]=float(acc); a[k][i]=float(acc);
    }
    for (int i=0;i<5;++i) { double rhs=0; for (int r=0;r<6;++r) rhs += js[r][i]*(weights[r]*es[r]);
        if(!(rhs<=FLT_MAX && rhs>=-FLT_MAX)) return 2; b[i]=float(rhs); }
    int status=solve5(a,b,dq); if (status) { for (int i=0;i<5;++i) dq[i]=0; return status; }
    float largest=0; for (int i=0;i<5;++i) if (std::fabs(dq[i])>largest) largest=std::fabs(dq[i]);
    float gain=largest>max_step?max_step/largest:1.0f;
    for (int i=0;i<5;++i) { dq[i]*=gain; q_next[i]=q[i]+dq[i]; if (q_next[i]<limits[2*i]) q_next[i]=limits[2*i]; if (q_next[i]>limits[2*i+1]) q_next[i]=limits[2*i+1]; dq[i]=q_next[i]-q[i]; }
    return 0;
}
