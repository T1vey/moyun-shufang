#include "controller_test_support.hpp"
using namespace controller_test;

static void untouched_after(const Invocation& c,unsigned first,unsigned count) {
    for(unsigned row=first;row<count;row++)for(unsigned w=0;w<16;w++)
        require(c.output[16*row+w]==UINT64_C(0xa5a5a5a5a5a5a5a5),"wrote speculative output after terminating prefix");
}
static void partial(const Fixture& f,const std::vector<Point>& p,Invocation& c,unsigned expected_first) {
    c.run(IK_CHAIN,unsigned(p.size()));c.header_identity(IK_CHAIN,unsigned(p.size()));
    require(hi(c.header[0])==PARTIAL,"expected PARTIAL");
    const unsigned done=hi(c.header[3]);
    require(done==expected_first+1&&lo(c.header[4])==expected_first,"wrong PARTIAL prefix");
    for(unsigned row=0;row<done;row++) {
        const uint64_t* out=c.output+16*row;
        require(hi(out[10])==1000+row,"partial row identity");
        require(out[11]==pair(c.generation,42),"partial generation/context");
        require(lo(out[10])==(row==expected_first?1u:0u),"failure must terminate successful prefix");
        for(unsigned k=0;k<10;k++)require(std::isfinite(unpack(out[k])),"nonfinite failure output");
        for(unsigned k=7;k<10;k++)require(unpack(out[k])>=0,"negative failure statistics");
        for(unsigned k=12;k<16;k++)require(out[k]==0,"nonzero reserved output");
        if(row<expected_first) {
            Joints q;for(int k=0;k<7;k++)q[k]=unpack(out[k]);
            Pose pose=fk(f,q);
            require(position_error(pose,p[row])<=f.options[0],"bad committed position before failure");
            require(angle_error(pose,f.rotation)<=f.options[1],"bad committed angle before failure");
        }
    }
    untouched_after(c,done,unsigned(p.size()));
}
int main() {
    try {
        Fixture f;std::vector<Point> points=line64(f);points.resize(8);
        {Invocation c(f);c.points(points);c.run(IK_CHAIN,8);verify_chain("srs_contract_normal",f,points,c,true);}
        // Producer failure in the middle must drain a full, bounded FIFO, keep
        // exactly three verified rows, and never write the later speculation.
        {Invocation c(f);c.points(points);c.input[4*3]=pack(std::numeric_limits<double>::quiet_NaN());partial(f,points,c,3);}
        {Invocation c(f);c.points(points);c.input[4*3]=pack(10.);partial(f,points,c,3);}
        // General 7R inputs remain valid ABI inputs, but this SRS-only IK kernel
        // must hand an unsupported fixed transform back to the CPU explicitly.
        {Fixture other=f;other.model[21+3]=.001;Invocation c(other);c.points(points);partial(other,points,c,0);}
        // Force the consumer's independent FK verifier to reject, even though
        // the producer can generate many finite candidates ahead of it.
        {Fixture strict=f;strict.options[0]=1e-25;strict.options[1]=1e-25;
         Invocation c(strict);c.points(points);partial(strict,points,c,0);}
        {Invocation c(f);c.points(points);c.cancel[0]=pair(c.generation,c.job);c.run(IK_CHAIN,8);
         c.header_identity(IK_CHAIN,8);require(hi(c.header[0])==CANCELLED&&hi(c.header[3])==0&&lo(c.header[4])==0,"cancel prefix");
         untouched_after(c,0,8);}
        {Invocation c(f);c.points(points);c.cancel[0]=pair(c.generation-1,c.job);c.run(IK_CHAIN,8);
         verify_chain("srs_contract_stale_cancel",f,points,c,true);}
        {Invocation c(f);c.points(points);c.config[0]^=1;c.run(IK_CHAIN,8);require(hi(c.header[0])==BAD_ABI&&hi(c.header[3])==0,"bad ABI");untouched_after(c,0,8);}
        {Invocation c(f);c.points(points);c.run(IK_CHAIN,8,7);require(hi(c.header[0])==BAD_INPUT&&hi(c.header[3])==0,"capacity guard");untouched_after(c,0,8);}
        {Invocation c(f);for(int k=0;k<7;k++)c.input[k]=pack(f.seed[k]);c.input[7]=99;c.run(FK_ROWS,1);
         require(hi(c.header[0])==OK&&hi(c.header[3])==1&&c.output[16]==pair(99,0),"FK mode preserved");
         const Pose expected=fk(f,f.seed);for(int n=0;n<16;n++)require(std::abs(unpack(c.output[n])-expected[n])<1e-9,"FK oracle mismatch");}
        std::cout<<"SRS CONTRACT PASS: ordered prefixes, producer and consumer rejection, cancellation, untouched discarded outputs, ABI/capacity and FK.\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;}
}
