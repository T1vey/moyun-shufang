#include "tcb_planner_parallel.h"
#include "parallel_srs_pipeline_fp32.hpp"
using namespace tcb_pl;
static uint64_t pair32(uint32_t a,uint32_t b){return uint64_t(a)|(uint64_t(b)<<32);}
static double unpack64(uint64_t u){union{uint64_t u;double d;}v;v.u=u;return v.d;}
static uint64_t pack32(float f){union{uint64_t u;double d;}v;v.d=double(f);return v.u;}
static bool finite64(double d){union{uint64_t u;double d;}v;v.d=d;return (v.u&UINT64_C(0x7ff0000000000000))!=UINT64_C(0x7ff0000000000000);}

// Dedicated IK core: FK_ROWS is explicitly rejected; the general CPU FK remains
// available to applications. No duplicate FK datapath consumes FPGA resources.
extern "C" void tcb_planner_parallel(const uint64_t* config_words,
    const uint64_t* input_words,uint64_t* output_words,uint64_t* result_words,
    volatile uint64_t* cancel_words,uint32_t mode,uint32_t count,
    uint32_t output_capacity,uint32_t job_id,uint32_t generation) {
// Independent memory masters allow target reads, result writes and live
// cancellation reads to proceed concurrently. Full-system BD connects them.
#pragma HLS INTERFACE m_axi port=config_words offset=slave bundle=gmem_control depth=256 max_widen_bitwidth=64
#pragma HLS INTERFACE m_axi port=cancel_words offset=slave bundle=gmem_control depth=8 max_widen_bitwidth=64
#pragma HLS INTERFACE m_axi port=input_words offset=slave bundle=gmem_input depth=8192 max_widen_bitwidth=64 num_read_outstanding=4 max_read_burst_length=64
#pragma HLS INTERFACE m_axi port=output_words offset=slave bundle=gmem_output depth=24576 max_widen_bitwidth=64 num_write_outstanding=4 max_write_burst_length=64
#pragma HLS INTERFACE m_axi port=result_words offset=slave bundle=gmem_output depth=8 max_widen_bitwidth=64
#pragma HLS INTERFACE s_axilite port=config_words bundle=control offset=0x10
#pragma HLS INTERFACE s_axilite port=input_words bundle=control offset=0x1c
#pragma HLS INTERFACE s_axilite port=output_words bundle=control offset=0x28
#pragma HLS INTERFACE s_axilite port=result_words bundle=control offset=0x34
#pragma HLS INTERFACE s_axilite port=cancel_words bundle=control offset=0x40
#pragma HLS INTERFACE s_axilite port=mode bundle=control offset=0x4c
#pragma HLS INTERFACE s_axilite port=count bundle=control offset=0x54
#pragma HLS INTERFACE s_axilite port=output_capacity bundle=control offset=0x5c
#pragma HLS INTERFACE s_axilite port=job_id bundle=control offset=0x64
#pragma HLS INTERFACE s_axilite port=generation bundle=control offset=0x6c
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS ALLOCATION operation instances=fmul limit=2
#pragma HLS ALLOCATION operation instances=fadd limit=2
#pragma HLS ALLOCATION operation instances=fsub limit=2
    uint64_t c[256];
    for(int i=0;i<256;i++) {
#pragma HLS PIPELINE II=1
        c[i]=config_words[i];
    }
    uint32_t context_id=uint32_t(c[1]),status=OK,done=0,first=NONE;
    // Double values below preserve/validate the original wire representation.
    // Geometry, trigonometry, division and branch cost use float throughout.
    double model64[147],tool64[16];
    float model[147],tool[16],opt[7],seed[7],rotation[9];bool sparse[8]={};
#pragma HLS ARRAY_PARTITION variable=tool complete
#pragma HLS ARRAY_PARTITION variable=opt complete
#pragma HLS ARRAY_PARTITION variable=seed complete
#pragma HLS ARRAY_PARTITION variable=rotation complete
#pragma HLS ARRAY_PARTITION variable=sparse complete
    bool wire_valid=true;
    for(int i=0;i<147;i++) {
#pragma HLS PIPELINE II=1
        model64[i]=unpack64(c[2+i]);model[i]=float(model64[i]);
        if(!finite64(model64[i])||!finite32(model[i]))wire_valid=false;
    }
    for(int i=0;i<16;i++) {
#pragma HLS PIPELINE II=1
        tool64[i]=unpack64(c[149+i]);tool[i]=float(tool64[i]);
        if(!finite64(tool64[i])||!finite32(tool[i]))wire_valid=false;
    }
    for(int i=0;i<7;i++){opt[i]=float(unpack64(c[165+i]));seed[i]=float(unpack64(c[172+i]));}
    for(int i=0;i<9;i++)rotation[i]=float(unpack64(c[179+i]));
    if(uint32_t(c[0])!=ABI)status=BAD_ABI;
    else if(uint32_t(c[0]>>32)!=MODEL)status=BAD_MODEL;
    else if(c[1]>>32||!context_id||!job_id||!generation||!count||
        mode!=IK_CHAIN||count>MAX_IK||output_capacity<count)status=BAD_INPUT;
    if(status==OK) {
        if(!wire_valid||!finite_fp32(opt,7)||!finite_fp32(seed,7)||!finite_fp32(rotation,9)||
            opt[0]<=0.0f||opt[1]<=0.0f||opt[2]<1.0f||opt[2]>1000.0f||opt[3]<=0.0f||
            opt[4]<=0.0f||opt[5]<=0.0f||opt[6]<0.0f)status=BAD_INPUT;
        for(int i=0;i<7;i++) {
            if(model[21*i+19]>=model[21*i+20]||seed[i]<model[21*i+19]||seed[i]>model[21*i+20])status=BAD_INPUT;
            if(model64[21*i+16]!=0.0||model64[21*i+17]!=0.0||std::abs(model64[21*i+18])!=1.0)status=BAD_MODEL;
            if(model64[21*i+12]!=0.0||model64[21*i+13]!=0.0||model64[21*i+14]!=0.0||model64[21*i+15]!=1.0)status=BAD_MODEL;
        }
        if(tool64[12]!=0.0||tool64[13]!=0.0||tool64[14]!=0.0||tool64[15]!=1.0)status=BAD_MODEL;
        for(int i=188;i<256;i++)if(c[i])status=BAD_INPUT;
    }
    if(status==OK)for(int link=0;link<8;link++) {
        float transform[12];
#pragma HLS ARRAY_PARTITION variable=transform complete
        for(int n=0;n<12;n++)transform[n]=link<7?model[21*link+n]:tool[n];
        sparse[link]=parallel_compose_is_rx_z_fp32(transform);
    }
    if(status==OK) {
        uint32_t completion[3];
        if(mode==IK_CHAIN) {
            float p[parallel_srs_fp32::PARAM_COUNT]={0},limits[14]={0},elbow[3]={0},sn[7],cs[7];
            float rprod[9],rwrite[9],qprod[7],qwrite[7];
#pragma HLS ARRAY_PARTITION variable=p complete
#pragma HLS ARRAY_PARTITION variable=elbow complete
#pragma HLS ARRAY_PARTITION variable=sn complete
#pragma HLS ARRAY_PARTITION variable=cs complete
#pragma HLS ARRAY_PARTITION variable=rprod complete
#pragma HLS ARRAY_PARTITION variable=rwrite complete
#pragma HLS ARRAY_PARTITION variable=qprod complete
#pragma HLS ARRAY_PARTITION variable=qwrite complete
            const bool supported=parallel_srs_fp32::prepare(model64,tool64,p,limits);
            if(supported){parallel_seed_sincos2_fp32(seed,sn,cs);parallel_srs_fp32::seed_elbow_from_trig(p,sn,cs,elbow);}
            for(int i=0;i<7;i++)qprod[i]=qwrite[i]=seed[i];
            for(int i=0;i<9;i++)rprod[i]=rwrite[i]=rotation[i];
            parallel_srs_pipeline_fp32::chain(input_words,output_words,cancel_words,count,
                supported,p,limits,rprod,qprod,elbow,opt[3],model,tool,sparse,rwrite,opt,
                qwrite,job_id,generation,context_id,completion);
        }
        status=completion[0];done=completion[1];first=completion[2];
    }
    uint64_t h[8]={pair32(ABI,status),pair32(job_id,generation),pair32(context_id,mode),
        pair32(count,done),pair32(first,0),pair32(0,CAP_FP32|CAP_RESIDUAL_NOT_EVALUATED),0,0};
    for(int i=0;i<8;i++)result_words[i]=h[i];
}
