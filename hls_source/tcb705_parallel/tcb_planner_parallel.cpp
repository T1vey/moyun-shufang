#include "tcb_planner_parallel.h"
#include "parallel_srs_pipeline.hpp"
using namespace tcb_pl;
static uint64_t pair32(uint32_t a,uint32_t b){return uint64_t(a)|(uint64_t(b)<<32);}
static double unpack(uint64_t u){union{uint64_t u;double d;}v;v.u=u;return v.d;}
static uint64_t pack(double d){union{uint64_t u;double d;}v;v.d=d;return v.u;}

// FK_ROWS retains the runtime general model path. No numerical IK or LDLT
// routine is called by this implementation; unsupported IK uses PS fallback.
static void fk_rows(const uint64_t* input_words,uint64_t* output_words,
    volatile uint64_t* cancel_words,unsigned count,const double model[147],
    const double tool[16],const bool sparse[8],uint32_t job_id,
    uint32_t generation,uint32_t completion[3]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=tool complete
#pragma HLS ARRAY_PARTITION variable=sparse complete
    uint32_t status=OK,done=0,first=NONE;
    FK_ROWS_LOOP: for(unsigned row=0;row<count;row++) {
#pragma HLS LOOP_TRIPCOUNT min=1 max=1024
        // Preserve the existing periodic FK cancellation contract.
        if((row&63u)==0&&cancel_words[0]==pair32(generation,job_id)) {
            status=CANCELLED;first=row;break;
        }
        uint64_t words[8],output[24]={0};
        for(int k=0;k<8;k++) {
#pragma HLS PIPELINE II=1
            words[k]=input_words[8*row+k];
        }
        double q[7],pose[16],jacobian[6][7];
#pragma HLS ARRAY_PARTITION variable=q complete
#pragma HLS ARRAY_PARTITION variable=pose complete
#pragma HLS ARRAY_PARTITION variable=jacobian complete dim=1
        bool accepted=!(words[7]>>32);
        for(int k=0;k<7;k++) {
#pragma HLS PIPELINE II=1
            q[k]=unpack(words[k]);
            if(!finite64(q[k])||q[k]<model[21*k+19]||q[k]>model[21*k+20])accepted=false;
        }
        if(accepted) {
            parallel_geometry7(model,q,tool,sparse,pose,jacobian);
            accepted=finite(pose,16);
        }
        if(accepted)for(int k=0;k<16;k++)output[k]=pack(pose[k]);
        output[16]=pair32(uint32_t(words[7]),accepted?0u:1u);
        for(int k=0;k<24;k++) {
#pragma HLS PIPELINE II=1
            output_words[24*row+k]=output[k];
        }
        done++;
        if(!accepted){status=PARTIAL;first=row;break;}
    }
    completion[0]=status;completion[1]=done;completion[2]=first;
}

extern "C" void tcb_planner_parallel(const uint64_t* config_words,
    const uint64_t* input_words,uint64_t* output_words,uint64_t* result_words,
    volatile uint64_t* cancel_words,uint32_t mode,uint32_t count,
    uint32_t output_capacity,uint32_t job_id,uint32_t generation){
#pragma HLS INTERFACE m_axi port=config_words offset=slave bundle=gmem depth=256 max_widen_bitwidth=64
#pragma HLS INTERFACE m_axi port=input_words offset=slave bundle=gmem depth=8192 max_widen_bitwidth=64
#pragma HLS INTERFACE m_axi port=output_words offset=slave bundle=gmem depth=24576 max_widen_bitwidth=64
#pragma HLS INTERFACE m_axi port=result_words offset=slave bundle=gmem depth=8 max_widen_bitwidth=64
#pragma HLS INTERFACE m_axi port=cancel_words offset=slave bundle=gmem depth=8 max_widen_bitwidth=64
#pragma HLS INTERFACE s_axilite port=config_words bundle=control
#pragma HLS INTERFACE s_axilite port=input_words bundle=control
#pragma HLS INTERFACE s_axilite port=output_words bundle=control
#pragma HLS INTERFACE s_axilite port=result_words bundle=control
#pragma HLS INTERFACE s_axilite port=cancel_words bundle=control
#pragma HLS INTERFACE s_axilite port=mode bundle=control
#pragma HLS INTERFACE s_axilite port=count bundle=control
#pragma HLS INTERFACE s_axilite port=output_capacity bundle=control
#pragma HLS INTERFACE s_axilite port=job_id bundle=control
#pragma HLS INTERFACE s_axilite port=generation bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS ALLOCATION operation instances=dmul limit=2
#pragma HLS ALLOCATION operation instances=dadd limit=2
#pragma HLS ALLOCATION operation instances=dsub limit=2
#pragma HLS ALLOCATION operation instances=ddiv limit=1
#pragma HLS ALLOCATION operation instances=dsqrt limit=1
    uint64_t c[256];
    for(int i=0;i<256;i++){
#pragma HLS PIPELINE II=1
        c[i]=config_words[i];
    }
    uint32_t context_id=uint32_t(c[1]),status=OK,done=0,first=NONE;
    double model[147],tool[16],opt[7],seed[7],rotation[9];
    bool sparse[8]={};
#pragma HLS ARRAY_PARTITION variable=sparse complete
#pragma HLS ARRAY_PARTITION variable=tool complete
#pragma HLS ARRAY_PARTITION variable=opt complete
#pragma HLS ARRAY_PARTITION variable=seed complete
#pragma HLS ARRAY_PARTITION variable=rotation complete
    for(int i=0;i<147;i++){
#pragma HLS PIPELINE II=1
        model[i]=unpack(c[2+i]);
    }
    for(int i=0;i<16;i++){
#pragma HLS PIPELINE II=1
        tool[i]=unpack(c[149+i]);
    }
    for(int i=0;i<7;i++){opt[i]=unpack(c[165+i]);seed[i]=unpack(c[172+i]);}
    for(int i=0;i<9;i++)rotation[i]=unpack(c[179+i]);
    if(uint32_t(c[0])!=ABI)status=BAD_ABI;
    else if(uint32_t(c[0]>>32)!=MODEL)status=BAD_MODEL;
    else if(c[1]>>32 || !context_id || !job_id || !generation || !count ||
        (mode!=IK_CHAIN&&mode!=FK_ROWS) || count>(mode==IK_CHAIN?64u:1024u) || output_capacity<count)status=BAD_INPUT;
    if(status==OK){
        if(!finite(model,147)||!finite(tool,16)||!finite(opt,7)||!finite(seed,7)||!finite(rotation,9)||
            opt[0]<=0||opt[1]<=0||opt[2]<1||opt[2]>1000||opt[3]<=0||opt[4]<=0||opt[5]<=0||opt[6]<0)status=BAD_INPUT;
        for(int i=0;i<7;i++)if(model[21*i+19]>=model[21*i+20]||seed[i]<model[21*i+19]||seed[i]>model[21*i+20])status=BAD_INPUT;
        for(int i=0;i<7;i++)if(model[21*i+16]!=0||model[21*i+17]!=0||std::abs(model[21*i+18])!=1)status=BAD_MODEL;
        for(int i=0;i<7;i++) {
            if(model[21*i+12]!=0||model[21*i+13]!=0||
               model[21*i+14]!=0||model[21*i+15]!=1)status=BAD_MODEL;
        }
        if(tool[12]!=0||tool[13]!=0||tool[14]!=0||tool[15]!=1)status=BAD_MODEL;
        for(int i=188;i<256;i++)if(c[i])status=BAD_INPUT;
    }
    if(status==OK)for(int link=0;link<8;link++) {
        double transform[12];
#pragma HLS ARRAY_PARTITION variable=transform complete
        for(int n=0;n<12;n++) {
#pragma HLS PIPELINE II=1
            transform[n]=link<7?model[21*link+n]:tool[n];
        }
        sparse[link]=parallel_compose_is_rx_z(transform);
    }
    if(status==OK) {
        uint32_t completion[3];
        if(mode==IK_CHAIN) {
            // Only the consumer accesses gmem while DATAFLOW is active. A
            // bounded 2 KiB prefetch keeps the single external AXI ABI and
            // allows producer calculation to overlap live cancellation/FK.
            uint64_t input_buffer[256];
#pragma HLS BIND_STORAGE variable=input_buffer type=ram_1p impl=bram
            PREFETCH_IK_INPUT: for(unsigned word=0;word<4*count;word++) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=4 max=256
                input_buffer[word]=input_words[word];
            }
            double parameters[parallel_srs::PARAM_COUNT]={0},limits[14]={0};
            double initial_elbow[3]={0},sn[7],cs[7];
            double producer_rotation[9],consumer_rotation[9];
            double producer_seed[7],consumer_seed[7];
#pragma HLS ARRAY_PARTITION variable=parameters complete
#pragma HLS ARRAY_PARTITION variable=initial_elbow complete
#pragma HLS ARRAY_PARTITION variable=sn complete
#pragma HLS ARRAY_PARTITION variable=cs complete
#pragma HLS ARRAY_PARTITION variable=producer_rotation complete
#pragma HLS ARRAY_PARTITION variable=consumer_rotation complete
#pragma HLS ARRAY_PARTITION variable=producer_seed complete
#pragma HLS ARRAY_PARTITION variable=consumer_seed complete
            const bool supported=parallel_srs::prepare(model,tool,parameters,limits);
            if(supported) {
                parallel_sincos7(seed,sn,cs);
                parallel_srs::seed_elbow_from_trig(parameters,sn,cs,initial_elbow);
            }
            // Distinct read-only copies give each DATAFLOW stage its own
            // constant inputs; there is no stream feedback from FK to SRS.
            for(int k=0;k<7;k++)producer_seed[k]=consumer_seed[k]=seed[k];
            for(int k=0;k<9;k++)producer_rotation[k]=consumer_rotation[k]=rotation[k];
            parallel_srs_pipeline::chain(input_buffer,output_words,cancel_words,count,
                supported,parameters,limits,producer_rotation,producer_seed,
                initial_elbow,opt[3],model,tool,sparse,consumer_rotation,opt,
                consumer_seed,job_id,generation,context_id,completion);
        } else fk_rows(input_words,output_words,cancel_words,count,model,tool,sparse,
            job_id,generation,completion);
        status=completion[0];done=completion[1];first=completion[2];
    }
    // IK is analytic; no numerical iteration count is reported. All metadata
    // fields and reserved-zero words retain the existing external ABI.
    uint64_t h[8]={pair32(ABI,status),pair32(job_id,generation),pair32(context_id,mode),
        pair32(count,done),pair32(first,0),0,0,0};
    for(int i=0;i<8;i++)result_words[i]=h[i];
}
