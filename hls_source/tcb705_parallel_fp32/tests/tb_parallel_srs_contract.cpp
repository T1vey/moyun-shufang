#include "controller_test_support.hpp"
using namespace controller_test;

static void untouched_after(const Invocation& c,unsigned first,unsigned count) {
    for(unsigned row=first;row<count;row++)for(unsigned w=0;w<16;w++)
        require(c.output[16*row+w]==UINT64_C(0xa5a5a5a5a5a5a5a5),"wrote speculative output after terminating prefix");
}
static void partial(const Fixture& f,const std::vector<Point>& p,Invocation& c,unsigned first) {
    c.run(IK_CHAIN,unsigned(p.size()));c.header_identity(IK_CHAIN,unsigned(p.size()));
    require(hi(c.header[0])==PARTIAL,"expected PARTIAL");
    const unsigned done=hi(c.header[3]);
    require(done==first+1&&lo(c.header[4])==first,"wrong PARTIAL prefix");
    Joints previous=f.seed;
    for(unsigned row=0;row<done;row++) {
        const uint64_t* out=c.output+16*row;
        require(hi(out[10])==1000+row,"partial row identity");
        require(out[11]==pair(c.generation,42),"partial generation/context");
        require(lo(out[10])==(row==first?1u:0u),"failure must terminate successful prefix");
        for(unsigned k=0;k<7;k++)require(std::isfinite(unpack(out[k])),"nonfinite joint output");
        require(out[9]==pack(0.),"FP32 analytical iterations must be zero");
        for(unsigned k=12;k<16;k++)require(out[k]==0,"nonzero reserved output");
        if(row<first) {
            require(out[7]==UINT64_C(0x7ff8000000000000)&&out[8]==UINT64_C(0x7ff8000000000000),"success residual must be canonical unknown, not zero");
            Joints q;for(int k=0;k<7;k++)q[k]=unpack(out[k]);
            Pose pose=fk(f,q);
            require(position_error(pose,p[row])<=1e-5,"offline FP64 position audit");
            require(angle_error(pose,f.rotation)<=1e-4,"offline FP64 angle audit");
            for(int k=0;k<7;k++)require(q[k]>=f.model[21*k+19]&&q[k]<=f.model[21*k+20]&&std::abs(q[k]-previous[k])<=f.options[3],"committed joint guard");
            previous=q;
        } else {
            for(unsigned k=7;k<10;k++)require(out[k]==pack(0.),"failure statistics must be finite zeros with failed status");
            for(int k=0;k<7;k++)require(std::abs(unpack(out[k])-previous[k])<=2e-7,"failure output must retain preceding legal joint state");
        }
    }
    untouched_after(c,done,unsigned(p.size()));
}
int main() {
    try {
        Fixture f;std::vector<Point> points=line64(f);points.resize(8);unsigned transactions=0;
        {Invocation c(f);c.points(points);c.run(IK_CHAIN,8);verify_chain("fp32_contract_normal",f,points,c,true);transactions++;}
        {Invocation c(f);c.points(points);c.input[4*3]=pack(std::numeric_limits<double>::quiet_NaN());partial(f,points,c,3);transactions++;}
        {Invocation c(f);c.points(points);c.input[4*3]=pack(10.);partial(f,points,c,3);transactions++;}
        {Fixture other=f;other.model[21+3]=.001;Invocation c(other);c.points(points);partial(other,points,c,0);transactions++;}
        // The runtime precision gate has deliberately been removed. A tiny
        // requested tolerance cannot fabricate zero residuals or reject a
        // finite, legal SRS solution; its error is audited only by this TB.
        {Fixture strict=f;strict.options[0]=1e-25;strict.options[1]=1e-25;
         Invocation c(strict);c.points(points);c.run(IK_CHAIN,8);verify_chain("fp32_contract_no_runtime_fk",strict,points,c,true);transactions++;}
        {Invocation c(f);c.points(points);c.cancel[0]=pair(c.generation,c.job);c.run(IK_CHAIN,8);
         c.header_identity(IK_CHAIN,8);require(hi(c.header[0])==CANCELLED&&hi(c.header[3])==0&&lo(c.header[4])==0,"cancel prefix");
         untouched_after(c,0,8);transactions++;}
        {Invocation c(f);c.points(points);c.cancel[0]=pair(c.generation-1,c.job);c.run(IK_CHAIN,8);
         verify_chain("fp32_contract_stale_cancel",f,points,c,true);transactions++;}
        {Invocation c(f);c.points(points);c.config[0]^=1;c.run(IK_CHAIN,8);c.header_identity(IK_CHAIN,8);
         require(hi(c.header[0])==BAD_ABI&&hi(c.header[3])==0,"bad ABI");untouched_after(c,0,8);transactions++;}
        {Invocation c(f);c.points(points);c.run(IK_CHAIN,8,7);c.header_identity(IK_CHAIN,8);
         require(hi(c.header[0])==BAD_INPUT&&hi(c.header[3])==0,"capacity guard");untouched_after(c,0,8);transactions++;}
        {Invocation c(f);for(int k=0;k<7;k++)c.input[k]=pack(f.seed[k]);c.input[7]=99;c.run(FK_ROWS,1);c.header_identity(FK_ROWS,1);
         require(hi(c.header[0])==BAD_INPUT&&hi(c.header[3])==0,"new FP32 core must reject unsupported FK_ROWS");
         for(unsigned n=0;n<24;n++)require(c.output[n]==UINT64_C(0xa5a5a5a5a5a5a5a5),"unsupported mode wrote output");transactions++;}
        {Fixture tight=f;tight.options[3]=1e-9;Invocation c(tight);c.points(points);partial(tight,points,c,0);transactions++;}
        {Invocation normal(f);normal.points(points);normal.run(IK_CHAIN,8);Fixture limited=f;bool found=false;
         for(int k=0;k<7;k++) {
             const double next=unpack(normal.output[k]),delta=next-f.seed[k];
             if(std::abs(delta)>1e-5) {limited.model[21*k+(delta>0?20:19)]=.5*(next+f.seed[k]);found=true;break;}
         }
         require(found,"limit fixture must change at least one joint");Invocation c(limited);c.points(points);partial(limited,points,c,0);transactions+=2;}
        std::cout<<"FP32 SRS CONTRACT PASS: "<<transactions<<" transactions; capabilities, canonical unknown residuals, ordered prefixes, fixed-count drain, joint guards, cancellation and unsupported FK. No robot motion.\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;}
}
