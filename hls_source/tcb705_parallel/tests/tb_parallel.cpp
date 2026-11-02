#include "parallel_test_support.hpp"
using namespace parallel_test;

static void reject_header(const char* name,Invocation& c,unsigned mode,unsigned count,unsigned expected,unsigned capacity=0) {
    c.run(mode,count,capacity);c.header_identity(mode,count);
    require(hi(c.header[0])==expected&&hi(c.header[3])==0,std::string("guard failed: ")+name);
    std::cout<<"GUARD "<<name<<" PASS status="<<expected<<'\n';
}
static void guards(const Fixture& f) {
    {Invocation c(f);c.config[0]^=1;reject_header("ABI",c,IK_CHAIN,1,BAD_ABI);}
    {Invocation c(f);c.config[0]^=uint64_t(1)<<32;reject_header("MODEL",c,IK_CHAIN,1,BAD_MODEL);}
    {Invocation c(f);c.config[1]=0;reject_header("zero_context",c,IK_CHAIN,1,BAD_INPUT);}
    {Invocation c(f);c.config[255]=1;reject_header("reserved_config",c,IK_CHAIN,1,BAD_INPUT);}
    {Invocation c(f);reject_header("IK_capacity65",c,IK_CHAIN,65,BAD_INPUT);}
    {Invocation c(f);reject_header("output_capacity",c,IK_CHAIN,2,BAD_INPUT,1);}
    {Invocation c(f);reject_header("zero_count",c,IK_CHAIN,0,BAD_INPUT);}
    {Invocation c(f);reject_header("invalid_mode",c,77,1,BAD_INPUT);}
    {Invocation c(f);c.config[165]=pack(0);reject_header("zero_tolerance",c,IK_CHAIN,1,BAD_INPUT);}
    {Invocation c(f);c.config[172]=pack(std::numeric_limits<double>::quiet_NaN());reject_header("NaN_seed",c,IK_CHAIN,1,BAD_INPUT);}
    {Invocation c(f);c.config[172]=pack(f.model[20]+1);reject_header("seed_out_of_limit",c,IK_CHAIN,1,BAD_INPUT);}
    {Invocation c(f);c.config[2+16]=pack(1);reject_header("unsupported_joint_axis",c,IK_CHAIN,1,BAD_MODEL);}
    {Invocation c(f);c.cancel[0]=pair(c.generation,c.job);reject_header("cancel_generation",c,IK_CHAIN,1,CANCELLED);}
    {Invocation c(f);std::vector<Point>p(1,origin(f));c.points(p);c.cancel[0]=pair(c.generation-1,c.job);c.run(IK_CHAIN,1);verify_chain("stale_cancel_ignored",f,p,c);require(hi(c.header[0])!=CANCELLED,"stale cancel latched");}
    {Invocation c(f);std::vector<Point>p(1,origin(f));c.points(p);c.input[0]=pack(std::numeric_limits<double>::quiet_NaN());c.run(IK_CHAIN,1);
     require(hi(c.header[0])==PARTIAL&&hi(c.header[3])==1&&lo(c.output[10])!=0,"NaN target not rejected");std::cout<<"GUARD NaN_target PASS\n";}
    {Invocation c(f);std::vector<Point>p(1,origin(f));c.points(p);c.input[3]|=uint64_t(1)<<32;c.run(IK_CHAIN,1);
     require(hi(c.header[0])==PARTIAL&&lo(c.output[10])!=0,"oversize target ID not rejected");std::cout<<"GUARD bad_target_id PASS\n";}
    {Invocation c(f);for(int k=0;k<7;k++)c.input[k]=pack(f.seed[k]);c.input[0]=pack(std::numeric_limits<double>::infinity());c.run(FK_ROWS,1);
     require(hi(c.header[0])==PARTIAL&&hi(c.output[16])!=0,"infinite FK joint not rejected");std::cout<<"GUARD infinite_FK_joint PASS\n";}
    {Fixture limited=f;limited.options[2]=3;Invocation c(limited);std::vector<Point>p(1,Point{{10,10,10}});c.points(p);c.run(IK_CHAIN,1);
     require(hi(c.header[0])==PARTIAL&&lo(c.output[10])!=0,"unreachable target not rejected");std::cout<<"GUARD unreachable_target PASS\n";}
}

static void fk_random(const Fixture& f) {
    Invocation c(f);std::vector<Joints> qs;uint32_t rng=0x7020705;
    for(unsigned row=0;row<32;row++) {
        Joints q;for(int k=0;k<7;k++){rng=rng*1664525u+1013904223u;const double u=double(rng)/4294967295.;
            q[k]=f.model[21*k+19]+(f.model[21*k+20]-f.model[21*k+19])*u;c.input[row*8+k]=pack(q[k]);}
        c.input[row*8+7]=3000+row;qs.push_back(q);
    }
    c.run(FK_ROWS,32);c.header_identity(FK_ROWS,32);require(hi(c.header[0])==OK&&hi(c.header[3])==32,"random FK batch failed");
    double max_position=0,max_rotation_entry=0;
    for(unsigned row=0;row<32;row++) {
        const Pose expected=fk(f,qs[row]);Pose got;for(int n=0;n<16;n++){got[n]=unpack(c.output[row*24+n]);require(std::isfinite(got[n]),"nonfinite FK output");}
        require(c.output[row*24+16]==pair(3000+row,0),"FK row identity/status");
        for(int n=17;n<24;n++)require(c.output[row*24+n]==0,"FK reserved words");
        max_position=std::max(max_position,position_error(got,Point{{expected[3],expected[7],expected[11]}}));
        for(int r=0;r<3;r++)for(int col=0;col<3;col++)max_rotation_entry=std::max(max_rotation_entry,std::abs(got[4*r+col]-expected[4*r+col]));
        require(got[12]==0&&got[13]==0&&got[14]==0&&got[15]==1,"FK rigid bottom row");
    }
    std::cout<<std::setprecision(12)<<"FK_RANDOM rows=32 max_position_m="<<max_position<<" max_rotation_entry="<<max_rotation_entry<<'\n';
    require(max_position<=1e-9&&max_rotation_entry<=1e-9,"FP64 FK differs from independent oracle by >1e-9");
}

int main() {
    try {
        Fixture f;unsigned requested=0,verified=0;
        guards(f);fk_random(f);
        std::vector<Point> original;
        for(int r=0;r<2;r++)original.push_back(Point{{f.positions[3*r],f.positions[3*r+1],f.positions[3*r+2]}});
        ChainSummary s=run_chain("old_two_vectors",f,original);requested+=s.requested;verified+=s.verified_ok;
        s=run_chain("line64_0p5mm",f,line64(f));requested+=s.requested;verified+=s.verified_ok;
        s=run_chain("arc32_0p4mm",f,arc32(f));requested+=s.requested;verified+=s.verified_ok;
        const Point o=origin(f);std::vector<Point> lift;
        for(int n=1;n<=16;n++)lift.push_back(Point{{o[0],o[1],o[2]+n*.0005}});
        s=run_chain("vertical_lift16_0p5mm",f,lift);requested+=s.requested;verified+=s.verified_ok;
        std::cout<<"CONTRACT/NUMERICAL PASS requested="<<requested<<" verified="<<verified<<" fallback="<<requested-verified<<'\n';
        std::cout<<"PARTIAL is permitted for correctness; it does not meet a full-batch throughput claim.\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;}
}
