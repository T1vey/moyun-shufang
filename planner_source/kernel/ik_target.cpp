#include "ik_target.h"
#define SO101_TARGET_CORE
#include "ik_math.h"

static int evaluate_target(const float q[5], const float p[3], const float axis[3],
    const float tool[3], const float tool_axis[3], float error[6], float j[6][5],
    float *pe, float *te) {
#pragma HLS INLINE off
    float tip[3], current[3], cross_axis[3];
    task_geometry(q,tool,tool_axis,tip,current,j);
    float squared=0;
    for(int i=0;i<3;++i) {
        error[i]=p[i]-tip[i]; error[i+3]=axis[i]-current[i];
        squared+=error[i]*error[i];
    }
    cross3(axis,current,cross_axis);
    *pe=std::sqrt(squared);
    *te=std::atan2(std::sqrt(dot3(cross_axis,cross_axis)),dot3(axis,current));
    for(int i=0;i<6;++i) if(!finite_value(error[i])) return 2;
    return finite_value(*pe)&&finite_value(*te)?0:2;
}

static double task_cost(const float error[6], const float w[6], const float s[6]) {
    double cost=0;
    for(int r=0;r<6;++r) { double v=double(s[r])*error[r]; cost+=double(w[r])*v*v; }
    return .5*cost;
}

static int direction(const float j[6][5],const float error[6],const float w[6],
    const float s[6],float mu,float max_step,int mode,float dq[5]) {
#pragma HLS INLINE off
    float a[5][5],b[5];
    for(int i=0;i<5;++i) {
        for(int k=0;k<=i;++k) {
            double acc=0;
            for(int r=0;r<6;++r)
                acc+=(double(j[r][i])*s[r])*(mode==0?w[r]:1.0f)*(double(j[r][k])*s[r]);
            if(i==k) acc+=mu;
            if(!(acc<=FLT_MAX&&acc>=-FLT_MAX)) return 2;
            a[i][k]=float(acc); a[k][i]=float(acc);
        }
        double rhs=0;
        for(int r=0;r<6;++r) rhs+=(double(j[r][i])*s[r])*(w[r]*(double(error[r])*s[r]));
        if(!(rhs<=FLT_MAX&&rhs>=-FLT_MAX)) return 2;
        b[i]=float(rhs);
    }
    int status=solve5(a,b,dq); if(status) return status;
    float largest=0;
    for(int i=0;i<5;++i) if(std::fabs(dq[i])>largest) largest=std::fabs(dq[i]);
    float gain=largest>max_step?max_step/largest:1;
    for(int i=0;i<5;++i) dq[i]*=gain;
    return 0;
}

extern "C" int z20_ik_target(
    const float q_init[5], const float target_position[3], const float target_axis[3],
    const float weights[6], const float scales[6], const float tool[3],
    const float tool_axis[3], const float limits[10], float mu, float max_step,
    float position_tolerance, float tilt_tolerance, float stagnation_cost_change,
    int max_iterations, int line_search_trials, int stagnation_window, int mode,
    float q_result[5], float *position_error, float *tilt_error,
    int *iterations_used, int *evaluations_used, unsigned int *abi_version) {
#pragma HLS INTERFACE s_axilite port=q_init bundle=control
#pragma HLS INTERFACE s_axilite port=target_position bundle=control
#pragma HLS INTERFACE s_axilite port=target_axis bundle=control
#pragma HLS INTERFACE s_axilite port=weights bundle=control
#pragma HLS INTERFACE s_axilite port=scales bundle=control
#pragma HLS INTERFACE s_axilite port=tool bundle=control
#pragma HLS INTERFACE s_axilite port=tool_axis bundle=control
#pragma HLS INTERFACE s_axilite port=limits bundle=control
#pragma HLS INTERFACE s_axilite port=mu bundle=control
#pragma HLS INTERFACE s_axilite port=max_step bundle=control
#pragma HLS INTERFACE s_axilite port=position_tolerance bundle=control
#pragma HLS INTERFACE s_axilite port=tilt_tolerance bundle=control
#pragma HLS INTERFACE s_axilite port=stagnation_cost_change bundle=control
#pragma HLS INTERFACE s_axilite port=max_iterations bundle=control
#pragma HLS INTERFACE s_axilite port=line_search_trials bundle=control
#pragma HLS INTERFACE s_axilite port=stagnation_window bundle=control
#pragma HLS INTERFACE s_axilite port=mode bundle=control
#pragma HLS INTERFACE s_axilite port=q_result bundle=control
#pragma HLS INTERFACE s_axilite port=position_error bundle=control
#pragma HLS INTERFACE s_axilite port=tilt_error bundle=control
#pragma HLS INTERFACE s_axilite port=iterations_used bundle=control
#pragma HLS INTERFACE s_axilite port=evaluations_used bundle=control
#pragma HLS INTERFACE s_axilite port=abi_version bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS ALLOCATION function instances=evaluate_target limit=1
    *abi_version=0x534f0301u; *iterations_used=0; *evaluations_used=0;
    *position_error=0; *tilt_error=0;
    for(int i=0;i<5;++i) q_result[i]=0;
    if(!finite_value(mu)||mu<=0||!finite_value(max_step)||max_step<=0||
       !finite_value(position_tolerance)||position_tolerance<=0||
       !finite_value(tilt_tolerance)||tilt_tolerance<=0||
       !finite_value(stagnation_cost_change)||stagnation_cost_change<0||
       max_iterations<1||max_iterations>120||line_search_trials<1||line_search_trials>32||
       stagnation_window<1||stagnation_window>32||(mode!=0&&mode!=1)) return 1;
    for(int i=0;i<5;++i) if(!finite_value(q_init[i])||!finite_value(limits[2*i])||
        !finite_value(limits[2*i+1])||limits[2*i]>=limits[2*i+1]||
        q_init[i]<limits[2*i]||q_init[i]>limits[2*i+1]) return 1;
    for(int i=0;i<6;++i) if(!finite_value(weights[i])||weights[i]<0||
        !finite_value(scales[i])||scales[i]<=0) return 1;
    for(int i=0;i<3;++i) if(!finite_value(target_position[i])||!finite_value(target_axis[i])||
        !finite_value(tool[i])||!finite_value(tool_axis[i])) return 1;
    if(std::fabs(dot3(target_axis,target_axis)-1)>1e-5f||
        std::fabs(dot3(tool_axis,tool_axis)-1)>1e-5f) return 1;
    // One evaluation call site prevents HLS from cloning the FK engine for
    // the initial pose and trial poses. Output pointers are write-only.
    float q[5],probe[5],error[6],j[6][5],dq[5];
    double costs[32]={0},cost=0;
    int pending=0,iteration=0,trial=0,evaluations=0;
    bool probing=false,touched=false;
    float gain=1;
    for(int i=0;i<5;++i) {q[i]=q_init[i];probe[i]=q[i];q_result[i]=q[i];}
    for(int work=0;work<3841;++work) {
#pragma HLS PIPELINE off
        float evaluated_error[6],evaluated_j[6][5],pe=0,te=0;
        int status=evaluate_target(probe,target_position,target_axis,tool,tool_axis,
            evaluated_error,evaluated_j,&pe,&te);
        ++evaluations; *evaluations_used=evaluations;
        if(status) { *iterations_used=iteration+(probing?1:0);return status; }
        double evaluated_cost=task_cost(evaluated_error,weights,scales);
        if(!(evaluated_cost<=DBL_MAX&&evaluated_cost>=0)) return 2;
        bool accepted=!probing||evaluated_cost<cost;
        if(accepted) {
            if(probing) {
                ++iteration; *iterations_used=iteration;
                if(iteration>=stagnation_window&&
                    std::fabs(costs[(iteration-stagnation_window)%32]-evaluated_cost)<stagnation_cost_change) {
                    bool at_limit=false;
                    for(int i=0;i<5;++i) at_limit=at_limit||probe[i]==limits[2*i]||probe[i]==limits[2*i+1];
                    pending=at_limit?5:4;
                }
            }
            for(int i=0;i<5;++i) {q[i]=probe[i];q_result[i]=q[i];}
            for(int r=0;r<6;++r) {
                error[r]=evaluated_error[r];
                for(int c=0;c<5;++c) j[r][c]=evaluated_j[r][c];
            }
            *position_error=pe; *tilt_error=te; cost=evaluated_cost;
            if(pe<=position_tolerance&&te<=tilt_tolerance) return 0;
            if(pending) return pending;
            if(iteration==max_iterations) return 3;
            costs[iteration%32]=cost;
            status=direction(j,error,weights,scales,mu,max_step,mode,dq);
            if(status) return status;
            probing=true;trial=0;gain=1;touched=false;
        } else {
            ++trial;
            if(trial>=line_search_trials) { *iterations_used=iteration+1;return touched?5:4; }
            gain*=.5f;
        }
        for(int i=0;i<5;++i) {
            float proposed=q[i]+dq[i]*gain;
            probe[i]=proposed;
            if(probe[i]<limits[2*i]) probe[i]=limits[2*i];
            if(probe[i]>limits[2*i+1]) probe[i]=limits[2*i+1];
            touched=touched||(probe[i]!=proposed);
        }
    }
    return 3;
}
