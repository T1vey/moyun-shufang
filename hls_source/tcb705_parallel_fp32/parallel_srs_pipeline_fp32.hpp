#pragma once
#include <hls_stream.h>
#include "tcb_planner_parallel.h"
#include "parallel_math_fp32.hpp"
#include "parallel_srs_fp32.hpp"

// FP32 compute with the existing packed-FP64 wire ABI. Double appears only
// at input/output conversion boundaries; geometry and acceptance use float.
// Geometry and angle candidates may run ahead. The third stage publishes an
// ordered prefix after finite/joint-limit/step checks. Runtime FK residual checks
// are deliberately disabled; independent FP64 checks remain in the testbench.
// Every invocation exchanges exactly count packets, including after failure
// or cancellation, so a depth-two FIFO cannot leave a blocked producer behind.
namespace parallel_srs_pipeline_fp32 {
struct Packet {
    float q[7];
    float position[3];
    uint32_t id;
    uint32_t failed;
};
struct GeometryPacket {
    float angle_y[7];
    float angle_x[7];
    float position[3];
    uint32_t id;
    uint32_t failed;
};
static uint64_t pair(uint32_t low,uint32_t high) {
#pragma HLS INLINE
    return uint64_t(low)|(uint64_t(high)<<32);
}
static float decode(uint64_t word) {
#pragma HLS INLINE
    union {uint64_t u;double d;} v;v.u=word;return float(v.d);
}
static uint64_t encode(float value) {
#pragma HLS INLINE
    union {uint64_t u;double d;} v;v.d=double(value);return v.u;
}

static void produce_geometry(const uint64_t* input_words,unsigned count,bool supported,
    const float parameters[parallel_srs_fp32::PARAM_COUNT],const float rotation[9],
    float initial_elbow_angle,const float initial_elbow[3],
    hls::stream<GeometryPacket>& packets) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=parameters complete
#pragma HLS ARRAY_PARTITION variable=rotation complete
#pragma HLS ARRAY_PARTITION variable=initial_elbow complete
    // input_words uses the dedicated read-only target AXI bundle. The consumer
    // uses separate control and output bundles, so the stages can overlap.
    float previous_elbow[3];
#pragma HLS ARRAY_PARTITION variable=previous_elbow complete
    for(int r=0;r<3;r++)previous_elbow[r]=initial_elbow[r];
    bool blocked=false;
    SRS_GEOMETRY_ROWS: for(unsigned row=0;row<count;row++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=64
        GeometryPacket packet;
        packet.id=0;packet.failed=1;
        for(int k=0;k<7;k++){packet.angle_y[k]=0.f;packet.angle_x[k]=0.f;}
        for(int r=0;r<3;r++)packet.position[r]=0.f;
        if(!blocked) {
            uint64_t words[4];
            for(int k=0;k<4;k++) {
#pragma HLS PIPELINE II=1
                words[k]=input_words[4*row+k];
            }
            packet.id=uint32_t(words[3]);
            float target[16]={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
            float angle_y[7],angle_x[7],next_elbow[3];
#pragma HLS ARRAY_PARTITION variable=target complete
#pragma HLS ARRAY_PARTITION variable=angle_y complete
#pragma HLS ARRAY_PARTITION variable=angle_x complete
#pragma HLS ARRAY_PARTITION variable=next_elbow complete
            for(int r=0;r<3;r++) {
                packet.position[r]=decode(words[r]);
                target[4*r+3]=packet.position[r];
                next_elbow[r]=previous_elbow[r];
                for(int c=0;c<3;c++)target[4*r+c]=rotation[3*r+c];
            }
            bool available=supported&&!(words[3]>>32)&&finite_fp32(target,16);
            if(available)available=parallel_srs_fp32::geometry_pairs(parameters,target,
                initial_elbow_angle,previous_elbow,angle_y,angle_x,next_elbow)==0;
            if(available)available=finite_fp32(angle_y,7)&&finite_fp32(angle_x,7)&&finite_fp32(next_elbow,3);
            if(available) {
                packet.failed=0;
                // Only elbow geometry recurs in this stage. The signed elbow
                // branch cannot change along an accepted, nonsingular prefix.
                // Stage two retains the precise previous-q3 guard; stages two
                // and three flush all later speculation after their first error.
                for(int k=0;k<7;k++){packet.angle_y[k]=angle_y[k];packet.angle_x[k]=angle_x[k];}
                for(int r=0;r<3;r++)previous_elbow[r]=next_elbow[r];
            } else blocked=true;
        }
        packets.write(packet);
    }
}

static void produce_angles(hls::stream<GeometryPacket>& geometry,unsigned count,
    const float limits[14],const float initial_q[7],float maximum_step,
    hls::stream<Packet>& packets) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=initial_q complete
    float previous_q[7];
#pragma HLS ARRAY_PARTITION variable=previous_q complete
    for(int k=0;k<7;k++)previous_q[k]=initial_q[k];
    bool blocked=false;
    SRS_ANGLE_ROWS: for(unsigned row=0;row<count;row++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=64
        const GeometryPacket source=geometry.read();Packet packet;
        packet.id=source.id;packet.failed=1;
        for(int k=0;k<7;k++)packet.q[k]=previous_q[k];
        for(int r=0;r<3;r++)packet.position[r]=source.position[r];
        if(!blocked) {
            // Keep the original next-row guard even if CORDIC rounding near
            // the threshold makes abs(q3) slightly smaller than the conditioning threshold. Geometry
            // may already be in flight, but it will never be accepted here.
            bool available=!source.failed&&finite32(previous_q[3])&&std::abs(previous_q[3])>=parallel_srs_fp32::MIN_CONDITION_SINE;
            float ys[7],xs[7],angles[7],candidate_q[7];
#pragma HLS ARRAY_PARTITION variable=ys complete
#pragma HLS ARRAY_PARTITION variable=xs complete
#pragma HLS ARRAY_PARTITION variable=angles complete
#pragma HLS ARRAY_PARTITION variable=candidate_q complete
            for(int k=0;k<7;k++){ys[k]=source.angle_y[k];xs[k]=source.angle_x[k];candidate_q[k]=previous_q[k];}
            if(available) {
                srs_atan2_7_fp32_guarded(ys,xs,angles);
                available=parallel_srs_fp32::select_branch(angles,limits,previous_q,maximum_step,candidate_q)==0;
            }
            if(available)available=finite_fp32(candidate_q,7);
            if(available) {
                packet.failed=0;
                for(int k=0;k<7;k++)packet.q[k]=previous_q[k]=candidate_q[k];
            } else blocked=true;
        }
        packets.write(packet);
    }
}

static bool legal_candidate(const float model[147],const float options[7],
    const float previous_q[7],const Packet& packet) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=options complete
#pragma HLS ARRAY_PARTITION variable=previous_q complete
    bool legal=true;
    for(int k=0;k<7;k++) {
#pragma HLS PIPELINE II=1
        const float q=packet.q[k];
        if(!finite32(q)||q<model[21*k+19]||q>model[21*k+20]||
           std::abs(q-previous_q[k])>options[3])legal=false;
    }
    for(int r=0;r<3;r++)if(!finite32(packet.position[r]))legal=false;
    return legal;
}

static void consume(hls::stream<Packet>& packets,unsigned count,
    const float model[147],const float options[7],const float initial_q[7],
    uint64_t* output_words,volatile uint64_t* cancel_words,
    uint32_t job_id,uint32_t generation,uint32_t context_id,
    uint32_t completion[3]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=options complete
#pragma HLS ARRAY_PARTITION variable=initial_q complete
    uint32_t status=tcb_pl::OK,done=0,first=tcb_pl::NONE;
    float committed_q[7];
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
                bool accepted=!packet.failed;
                if(accepted)accepted=legal_candidate(model,options,committed_q,packet);
                // Recheck immediately before publishing the row.
                const uint64_t cancel_after=cancel_words[0];
                if(cancel_after==pair(generation,job_id)) {
                    status=tcb_pl::CANCELLED;first=done;
                } else {
                    uint64_t output[16]={0};
                    for(int k=0;k<7;k++)output[k]=encode(accepted?packet.q[k]:committed_q[k]);
                    // No FK error was measured. Successful rows carry an
                    // explicit quiet NaN sentinel, never a fabricated zero.
                    // Failed rows retain finite zeros and row status=1.
                    const uint64_t unmeasured=UINT64_C(0x7ff8000000000000);
                    output[7]=accepted?unmeasured:encode(0.f);
                    output[8]=accepted?unmeasured:encode(0.f);
                    output[9]=encode(0.f); // analytic: no numerical iterations
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
    const float parameters[parallel_srs_fp32::PARAM_COUNT],const float limits[14],
    const float producer_rotation[9],const float producer_seed[7],
    const float initial_elbow[3],float maximum_step,
    const float model[147],const float tool[16],const bool sparse[8],
    const float consumer_rotation[9],const float options[7],
    const float consumer_seed[7],uint32_t job_id,uint32_t generation,
    uint32_t context_id,uint32_t completion[3]) {
#pragma HLS INLINE off
#pragma HLS DATAFLOW
    hls::stream<GeometryPacket> geometry("srs_geometry_candidates");
#pragma HLS STREAM variable=geometry depth=2
    hls::stream<Packet> packets("srs_ordered_prefix");
#pragma HLS STREAM variable=packets depth=2
    const float initial_elbow_angle=producer_seed[3];
    produce_geometry(input_words,count,supported,parameters,producer_rotation,
        initial_elbow_angle,initial_elbow,geometry);
    produce_angles(geometry,count,limits,producer_seed,maximum_step,packets);
    consume(packets,count,model,options,consumer_seed,
        output_words,cancel_words,job_id,generation,context_id,completion);
}
} // namespace parallel_srs_pipeline_fp32
