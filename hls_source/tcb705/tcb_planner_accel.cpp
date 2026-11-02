#include "tcb_planner_accel.h"
#include "pl_math7.hpp"
using namespace tcb_pl;
static uint64_t pair32(uint32_t a,uint32_t b){return uint64_t(a)|(uint64_t(b)<<32);}
static double unpack(uint64_t u){union{uint64_t u;double d;}v;v.u=u;return v.d;}
static uint64_t pack(double d){union{uint64_t u;double d;}v;v.d=d;return v.u;}
extern "C" void tcb_planner_accel(const uint64_t* config_words,
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
#pragma HLS ALLOCATION function instances=run_row7 limit=1
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
    uint32_t context_id=uint32_t(c[1]),status=OK,done=0,first=NONE,iterations=0;
    double model[147],tool[16],opt[7],seed[7],rotation[9],previous[7]={0};bool have_previous=false;
    for(int i=0;i<147;i++)model[i]=unpack(c[2+i]);
    for(int i=0;i<16;i++)tool[i]=unpack(c[149+i]);
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
        // pl_math7 v2 composes rigid 3x4 transforms: the bottom rows must be exactly 0 0 0 1
        for(int i=0;i<8;i++){const double*t=i<7?model+21*i:tool;if(t[12]!=0||t[13]!=0||t[14]!=0||t[15]!=1)status=BAD_MODEL;}
        for(int i=188;i<256;i++)if(c[i])status=BAD_INPUT;
    }
    if(status==OK)for(unsigned row=0;row<1024;row++){
#pragma HLS PIPELINE off
        if(row>=count)break;
        // Same job/generation cancellation contract as 1013; no latched flag.
        if(mode==IK_CHAIN||(row&63u)==0){
            uint64_t request=cancel_words[0];
            if(request==pair32(generation,job_id)){status=CANCELLED;first=row;break;}
        }
        uint64_t in[8]={0},out[24]={0};
        unsigned is=mode==IK_CHAIN?4:8,os=mode==IK_CHAIN?16:24;
        for(unsigned i=0;i<is;i++)in[i]=input_words[row*is+i];
        int result=0;double q[7]={0},stats[3]={0},pose[16]={0};uint32_t id;
        double target[16]={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
        if(mode==IK_CHAIN){
            id=uint32_t(in[3]);
            for(int r=0;r<3;r++){for(int col=0;col<3;col++)target[4*r+col]=rotation[r*3+col];target[4*r+3]=unpack(in[r]);}
            if(in[3]>>32||!finite(target,16))result=-1;
        }else{
            id=uint32_t(in[7]);if(in[7]>>32)result=-1;
            for(int i=0;i<7;i++){seed[i]=unpack(in[i]);if(!std::isfinite(seed[i])||seed[i]<model[21*i+19]||seed[i]>model[21*i+20])result=-1;}
        }
        // IK_CHAIN start = linear extrapolation of the last two solutions (halves the
        // iterations on sampled paths); the continuity reference stays the previous solution.
        double start[7];
        for(int i=0;i<7;i++){
#pragma HLS PIPELINE II=1
            double guess=(mode==IK_CHAIN&&have_previous)?(seed[i]+seed[i])-previous[i]:seed[i];  // == 2s-p exactly
            start[i]=std::max(model[21*i+19],std::min(model[21*i+20],guess));
        }
        if(!result)result=run_row7(mode==FK_ROWS,model,tool,target,start,seed,opt,q,stats,pose);
        if(mode==IK_CHAIN){
            for(int i=0;i<7;i++)out[i]=pack(q[i]);
            for(int i=0;i<3;i++)out[7+i]=pack(stats[i]);
            out[10]=pair32(result?1u:0u,id);out[11]=pair32(generation,context_id);
            iterations+=uint32_t(stats[2]);
            if(!result){for(int i=0;i<7;i++){previous[i]=seed[i];seed[i]=q[i];}have_previous=true;}
        }else{
            if(!result)for(int i=0;i<16;i++)out[i]=pack(pose[i]);
            out[16]=pair32(id,result?1u:0u);
        }
        for(unsigned i=0;i<os;i++)output_words[row*os+i]=out[i];
        done++;
        if(result){status=PARTIAL;first=row;break;}
    }
    uint64_t h[8]={pair32(ABI,status),pair32(job_id,generation),pair32(context_id,mode),pair32(count,done),pair32(first,iterations),0,0,0};
    for(int i=0;i<8;i++)result_words[i]=h[i];
}
