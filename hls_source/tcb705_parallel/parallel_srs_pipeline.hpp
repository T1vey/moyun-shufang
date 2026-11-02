#pragma once
#include <hls_stream.h>
#include "tcb_planner_parallel.h"
#include "pl_math7_parallel.hpp"
#include "parallel_srs.hpp"

// Two ordered stages. The producer may run ahead, but only the consumer can
// publish a successful row after evaluating the original FK and tolerances.
// Every invocation exchanges exactly count packets, including after failure
// or cancellation, so a depth-two FIFO cannot leave a blocked producer behind.
namespace parallel_srs_pipeline {
struct Packet {
    double q[7];
    double position[3];
    uint32_t id;
    uint32_t failed;
};
static uint64_t pair(uint32_t low,uint32_t high) {
#pragma HLS INLINE
    return uint64_t(low)|(uint64_t(high)<<32);
}
static double decode(uint64_t word) {
#pragma HLS INLINE
    union {uint64_t u;double d;} v;v.u=word;return v.d;
}
static uint64_t encode(double value) {
#pragma HLS INLINE
    union {uint64_t u;double d;} v;v.d=value;return v.u;
}

static void produce(const uint64_t* input_words,unsigned count,bool supported,
    const double parameters[parallel_srs::PARAM_COUNT],const double limits[14],
    const double rotation[9],const double initial_q[7],
    const double initial_elbow[3],double maximum_step,
    hls::stream<Packet>& packets) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=parameters complete
#pragma HLS ARRAY_PARTITION variable=rotation complete
#pragma HLS ARRAY_PARTITION variable=initial_q complete
#pragma HLS ARRAY_PARTITION variable=initial_elbow complete
    // input_words points to the top-level bounded BRAM prefetch, not gmem.
    // The consumer therefore owns the only external read channel in DATAFLOW.
    double previous_q[7],previous_elbow[3];
#pragma HLS ARRAY_PARTITION variable=previous_q complete
#pragma HLS ARRAY_PARTITION variable=previous_elbow complete
    for(int k=0;k<7;k++)previous_q[k]=initial_q[k];
    for(int r=0;r<3;r++)previous_elbow[r]=initial_elbow[r];
    bool blocked=false;
    SRS_PRODUCE_ROWS: for(unsigned row=0;row<count;row++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=64
        Packet packet;
        packet.id=0;packet.failed=1;
        for(int k=0;k<7;k++)packet.q[k]=previous_q[k];
        for(int r=0;r<3;r++)packet.position[r]=0.;
        if(!blocked) {
            uint64_t words[4];
            for(int k=0;k<4;k++) {
#pragma HLS PIPELINE II=1
                words[k]=input_words[4*row+k];
            }
            packet.id=uint32_t(words[3]);
            double target[16]={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
            double candidate_q[7],next_elbow[3];
#pragma HLS ARRAY_PARTITION variable=target complete
#pragma HLS ARRAY_PARTITION variable=candidate_q complete
#pragma HLS ARRAY_PARTITION variable=next_elbow complete
            for(int k=0;k<7;k++)candidate_q[k]=previous_q[k];
            for(int r=0;r<3;r++) {
                packet.position[r]=decode(words[r]);
                target[4*r+3]=packet.position[r];
                next_elbow[r]=previous_elbow[r];
                for(int c=0;c<3;c++)target[4*r+c]=rotation[3*r+c];
            }
            bool available=supported&&!(words[3]>>32)&&finite(target,16);
            if(available)available=parallel_srs::candidate(parameters,limits,target,
                previous_q,previous_elbow,maximum_step,candidate_q,next_elbow)==0;
            if(available)available=finite(candidate_q,7)&&finite(next_elbow,3);
            if(available) {
                packet.failed=0;
                // These are speculative producer-local states. A rejected FK
                // in the consumer discards this row and all following rows.
                for(int k=0;k<7;k++)packet.q[k]=previous_q[k]=candidate_q[k];
                for(int r=0;r<3;r++)previous_elbow[r]=next_elbow[r];
            } else blocked=true;
        }
        packets.write(packet);
    }
}

static bool verified_pose(const double model[147],const double tool[16],
    const bool sparse[8],const double rotation[9],const double options[7],
    const double previous_q[7],const Packet& packet,double& position_error,
    double& orientation_error) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=tool complete
#pragma HLS ARRAY_PARTITION variable=sparse complete
#pragma HLS ARRAY_PARTITION variable=rotation complete
#pragma HLS ARRAY_PARTITION variable=options complete
#pragma HLS ARRAY_PARTITION variable=previous_q complete
#pragma HLS ALLOCATION operation instances=dmul limit=3
#pragma HLS ALLOCATION operation instances=dadd limit=2
#pragma HLS ALLOCATION operation instances=dsub limit=2
#pragma HLS ALLOCATION operation instances=dsqrt limit=1
    position_error=0.;orientation_error=0.;
    double q[7],pose[16],jacobian[6][7],relative[9],ep[3],ea[3];
#pragma HLS ARRAY_PARTITION variable=q complete
#pragma HLS ARRAY_PARTITION variable=pose complete
#pragma HLS ARRAY_PARTITION variable=jacobian complete dim=1
#pragma HLS ARRAY_PARTITION variable=relative complete
#pragma HLS ARRAY_PARTITION variable=ep complete
#pragma HLS ARRAY_PARTITION variable=ea complete
    bool legal=true;
    for(int k=0;k<7;k++) {
#pragma HLS PIPELINE II=1
        q[k]=packet.q[k];
        if(!finite64(q[k])||q[k]<model[21*k+19]||q[k]>model[21*k+20]||
           std::abs(q[k]-previous_q[k])>options[3])legal=false;
    }
    for(int r=0;r<3;r++)if(!finite64(packet.position[r]))legal=false;
    if(!legal)return false;
    parallel_geometry7(model,q,tool,sparse,pose,jacobian);
    if(!finite(pose,16))return false;
    for(int n=0;n<9;n++) {
#pragma HLS PIPELINE II=1
        const int r=n/3,c=n%3;
        relative[n]=(rotation[3*r]*pose[4*c]+rotation[3*r+1]*pose[4*c+1])+
            rotation[3*r+2]*pose[4*c+2];
    }
    // Preserve the original small-angle branch guard as well as the strict
    // position and skew-vector orientation norms; no tolerance is relaxed.
    if(relative[0]+relative[4]+relative[8]<2.9975)return false;
    const double e0=.5*(relative[7]-relative[5]);
    const double e1=.5*(relative[2]-relative[6]);
    const double e2=.5*(relative[3]-relative[1]);
    ea[0]=e0*e0;ea[1]=e1*e1;ea[2]=e2*e2;
    for(int r=0;r<3;r++) {
#pragma HLS PIPELINE II=1
        const double difference=packet.position[r]-pose[4*r+3];
        ep[r]=difference*difference;
    }
    const double pe2=(ep[0]+ep[1])+ep[2],ae2=(ea[0]+ea[1])+ea[2];
    const double cost=pe2+options[4]*options[4]*ae2;
    if(!finite64(cost)||!finite64(pe2)||!finite64(ae2))return false;
    position_error=std::sqrt(pe2);orientation_error=std::sqrt(ae2);
    return finite64(position_error)&&finite64(orientation_error)&&
        position_error<=options[0]&&orientation_error<=options[1];
}

static void consume(hls::stream<Packet>& packets,unsigned count,
    const double model[147],const double tool[16],const bool sparse[8],
    const double rotation[9],const double options[7],const double initial_q[7],
    uint64_t* output_words,volatile uint64_t* cancel_words,
    uint32_t job_id,uint32_t generation,uint32_t context_id,
    uint32_t completion[3]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=tool complete
#pragma HLS ARRAY_PARTITION variable=sparse complete
#pragma HLS ARRAY_PARTITION variable=rotation complete
#pragma HLS ARRAY_PARTITION variable=options complete
#pragma HLS ARRAY_PARTITION variable=initial_q complete
    uint32_t status=tcb_pl::OK,done=0,first=tcb_pl::NONE;
    double committed_q[7];
#pragma HLS ARRAY_PARTITION variable=committed_q complete
    for(int k=0;k<7;k++)committed_q[k]=initial_q[k];
    SRS_CONSUME_ROWS: for(unsigned row=0;row<count;row++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=64
        const Packet packet=packets.read();
        // The first terminal outcome is latched. Subsequent packets are only
        // drained; neither cancellation nor speculative results can replace it.
        if(status==tcb_pl::OK) {
            const uint64_t cancel_before=cancel_words[0];
            if(cancel_before==pair(generation,job_id)) {
                status=tcb_pl::CANCELLED;first=done;
            } else {
                double pe=0.,ae=0.;
                bool accepted=!packet.failed;
                if(accepted)accepted=verified_pose(model,tool,sparse,rotation,options,
                    committed_q,packet,pe,ae);
                // Recheck after FK, immediately before publishing the row.
                const uint64_t cancel_after=cancel_words[0];
                if(cancel_after==pair(generation,job_id)) {
                    status=tcb_pl::CANCELLED;first=done;
                } else {
                    uint64_t output[16]={0};
                    for(int k=0;k<7;k++)output[k]=encode(accepted?packet.q[k]:committed_q[k]);
                    // Unknown failure residuals are finite zeros, with row
                    // status=1. They never represent an accepted zero-error IK.
                    output[7]=encode(accepted?pe:0.);
                    output[8]=encode(accepted?ae:0.);
                    output[9]=encode(0.); // analytic: no numerical iterations
                    output[10]=pair(accepted?0u:1u,packet.id);
                    output[11]=pair(generation,context_id);
                    for(int k=0;k<16;k++) {
#pragma HLS PIPELINE II=1
                        output_words[16*row+k]=output[k];
                    }
                    done++;
                    if(accepted)for(int k=0;k<7;k++)committed_q[k]=packet.q[k];
                    else {status=tcb_pl::PARTIAL;first=row;}
                }
            }
        }
    }
    completion[0]=status;completion[1]=done;completion[2]=first;
}

static void chain(const uint64_t* input_words,uint64_t* output_words,
    volatile uint64_t* cancel_words,unsigned count,bool supported,
    const double parameters[parallel_srs::PARAM_COUNT],const double limits[14],
    const double producer_rotation[9],const double producer_seed[7],
    const double initial_elbow[3],double maximum_step,
    const double model[147],const double tool[16],const bool sparse[8],
    const double consumer_rotation[9],const double options[7],
    const double consumer_seed[7],uint32_t job_id,uint32_t generation,
    uint32_t context_id,uint32_t completion[3]) {
#pragma HLS INLINE off
#pragma HLS DATAFLOW
    hls::stream<Packet> packets("srs_verified_prefix");
#pragma HLS STREAM variable=packets depth=2
    produce(input_words,count,supported,parameters,limits,producer_rotation,
        producer_seed,initial_elbow,maximum_step,packets);
    consume(packets,count,model,tool,sparse,consumer_rotation,options,consumer_seed,
        output_words,cancel_words,job_id,generation,context_id,completion);
}
} // namespace parallel_srs_pipeline
