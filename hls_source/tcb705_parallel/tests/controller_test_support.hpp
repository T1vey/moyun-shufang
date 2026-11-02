#pragma once
// Generated standalone support: no original fixture/test file modified.
#include "controller_dh_fixture.hpp"
// Test-only, independent FP64 pose oracle. Never linked into synthesized logic.
#ifdef TCB_TEST_BASELINE
#include "../../tcb705/tcb_planner_accel.h"
#else
#include "../tcb_planner_parallel.h"
#endif
#include "../../tcb705/pl_math7.hpp"
#include <array>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

extern "C" void tcb_planner_parallel(const uint64_t*, const uint64_t*,
    uint64_t*, uint64_t*, volatile uint64_t*, uint32_t, uint32_t,
    uint32_t, uint32_t, uint32_t);

namespace controller_test {
using namespace tcb_pl;
typedef std::array<double, 3> Point;
typedef std::array<double, 7> Joints;
typedef std::array<double, 16> Pose;
inline void require(bool ok,const std::string& message) {
    if (!ok) throw std::runtime_error(message);
}
inline uint64_t pack(double v) { uint64_t w;std::memcpy(&w,&v,8);return w; }
inline double unpack(uint64_t w) { double v;std::memcpy(&v,&w,8);return v; }
inline uint32_t lo(uint64_t w) { return uint32_t(w); }
inline uint32_t hi(uint64_t w) { return uint32_t(w>>32); }
inline uint64_t pair(uint32_t a,uint32_t b) { return uint64_t(a)|(uint64_t(b)<<32); }

struct Fixture {
    double model[147], tool[16], options[7], rotation[9], positions[6], expected[14], poses[32];
    Joints seed;
    Fixture() {
        namespace d=controller_dh_fixture;
        for(int i=0;i<147;i++)model[i]=d::MODEL[i];
        for(int i=0;i<16;i++)tool[i]=d::TOOL[i];
        for(int i=0;i<7;i++){options[i]=d::OPTIONS[i];seed[i]=d::PREFIX_Q[0][i];}
        for(int i=0;i<9;i++)rotation[i]=d::ROTATION[i];
        for(int i=0;i<6;i++)positions[i]=d::PREFIX_POSITION[i/3+1][i%3];
        for(int i=0;i<14;i++)expected[i]=d::PREFIX_Q[i/7+1][i%7];
        for(int i=0;i<32;i++)poses[i]=0;
    }
};

inline Pose multiply(const Pose&a,const Pose&b) {
    Pose out={{0}};
    for(int r=0;r<4;r++)for(int c=0;c<4;c++)for(int k=0;k<4;k++)
        out[4*r+c]+=a[4*r+k]*b[4*k+c];
    return out;
}

// Intentionally uses full 4x4 matrix multiplication and standard-library FP64
// trigonometry, not the candidate's polynomial or its geometry implementation.
inline Pose fk(const Fixture& f,const Joints&q) {
    Pose t={{1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1}};
    for(int j=0;j<7;j++) {
        Pose fixed;for(int n=0;n<16;n++)fixed[n]=f.model[21*j+n];
        t=multiply(t,fixed);
        const double a=q[j]*f.model[21*j+18],c=std::cos(a),s=std::sin(a);
        const Pose rz={{c,-s,0,0,s,c,0,0,0,0,1,0,0,0,0,1}};
        t=multiply(t,rz);
    }
    Pose tool;for(int n=0;n<16;n++)tool[n]=f.tool[n];
    return multiply(t,tool);
}
inline double position_error(const Pose& actual,const Point& target) {
    double e=0;for(int r=0;r<3;r++){double d=actual[4*r+3]-target[r];e+=d*d;}
    return std::sqrt(e);
}
inline double angle_error(const Pose& actual,const double* rotation) {
    double dot=0;for(int r=0;r<3;r++)for(int c=0;c<3;c++)dot+=actual[4*r+c]*rotation[3*r+c];
    return std::acos(std::max(-1.,std::min(1.,(dot-1.)*.5)));
}
inline Point origin(const Fixture& f) {const Pose p=fk(f,f.seed);return Point{{p[3],p[7],p[11]}};}

struct Invocation {
    uint64_t config[256],input[8192],output[24576],header[8],cancel[8];
    uint32_t job,generation;
    Invocation(const Fixture& f):job(701),generation(29) {
        std::memset(config,0,sizeof(config));std::memset(input,0,sizeof(input));
        std::memset(output,0xA5,sizeof(output));std::memset(header,0,sizeof(header));
        std::memset(cancel,0,sizeof(cancel));
        config[0]=pair(ABI,MODEL);config[1]=42;
        for(int i=0;i<147;i++)config[2+i]=pack(f.model[i]);
        for(int i=0;i<16;i++)config[149+i]=pack(f.tool[i]);
        for(int i=0;i<7;i++){config[165+i]=pack(f.options[i]);config[172+i]=pack(f.seed[i]);}
        for(int i=0;i<9;i++)config[179+i]=pack(f.rotation[i]);
    }
    void points(const std::vector<Point>& p) {
        for(size_t i=0;i<p.size();i++) {
            for(int k=0;k<3;k++)input[4*i+k]=pack(p[i][k]);
            input[4*i+3]=uint32_t(1000+i);
        }
    }
    void run(uint32_t mode,uint32_t count,uint32_t capacity=0) {
        tcb_planner_parallel(config,input,output,header,cancel,mode,count,capacity?capacity:count,job,generation);
    }
    void header_identity(uint32_t mode,uint32_t count)const {
        require(lo(header[0])==ABI,"header ABI");
        require(header[1]==pair(job,generation),"header job/generation identity");
        require(header[2]==pair(lo(config[1]),mode),"header context/mode identity");
        require(lo(header[3])==count && hi(header[3])<=count,"header counts");
        for(int i=5;i<8;i++)require(header[i]==0,"header reserved words");
    }
};

struct Reference {std::vector<Joints> rows;int failed;unsigned iterations;};
inline Reference old_reference(const Fixture& f,const std::vector<Point>& targets) {
    Reference ref;ref.failed=-1;ref.iterations=0;Joints seed=f.seed,previous=f.seed;
    bool have_previous=false;
    for(size_t n=0;n<targets.size();n++) {
        Pose target={{1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1}};
        for(int r=0;r<3;r++){for(int c=0;c<3;c++)target[4*r+c]=f.rotation[3*r+c];target[4*r+3]=targets[n][r];}
        Joints start,q;
        for(int k=0;k<7;k++)start[k]=std::max(f.model[21*k+19],std::min(f.model[21*k+20],have_previous?2*seed[k]-previous[k]:seed[k]));
        double stats[3]={},pose[16]={};
        const int status=run_row7(false,f.model,f.tool,target.data(),start.data(),seed.data(),f.options,q.data(),stats,pose);
        ref.iterations+=unsigned(stats[2]);
        if(status){ref.failed=int(n);break;}
        ref.rows.push_back(q);previous=seed;seed=q;have_previous=true;
    }
    return ref;
}

struct ChainSummary {
    unsigned requested,reported_ok,verified_ok,legacy_ok,first_rejected;
    unsigned zero_iterations,one_iteration,multiple_iterations,accepted_iterations,failed_iterations;
    double max_position,max_angle,max_joint_step,max_delta_old;
    ChainSummary():requested(0),reported_ok(0),verified_ok(0),legacy_ok(0),first_rejected(NONE),
        zero_iterations(0),one_iteration(0),multiple_iterations(0),accepted_iterations(0),failed_iterations(0),
        max_position(0),max_angle(0),max_joint_step(0),max_delta_old(0){}
};

inline ChainSummary verify_chain(const std::string& name,const Fixture& f,const std::vector<Point>& targets,
                                const Invocation& call,bool require_all=false) {
    call.header_identity(IK_CHAIN,uint32_t(targets.size()));
    require(hi(call.header[0])==OK || hi(call.header[0])==PARTIAL,"unexpected chain status: "+name);
    const Reference ref=old_reference(f,targets);
    ChainSummary s;s.requested=unsigned(targets.size());s.legacy_ok=unsigned(ref.rows.size());
    s.first_rejected=lo(call.header[4]);Joints previous=f.seed;
    bool rejected=false;
    for(unsigned row=0;row<hi(call.header[3]);row++) {
        const uint64_t* w=call.output+16*row;
        require(hi(w[10])==1000+row,"IK row ID");
        require(w[11]==pair(call.generation,42),"IK generation/context");
        for(int k=12;k<16;k++)require(w[k]==0,"IK reserved output");
        const double iterations=unpack(w[9]);
        require(std::isfinite(iterations)&&iterations>=0&&iterations<=f.options[2]&&std::floor(iterations)==iterations,"invalid row iteration count");
        if(lo(w[10])!=0){require(row+1==hi(call.header[3]),"failed row is not prefix tail");s.failed_iterations+=unsigned(iterations);rejected=true;continue;}
        require(!rejected,"valid output after rejected row");s.reported_ok++;
        s.accepted_iterations+=unsigned(iterations);
        if(iterations==0)s.zero_iterations++;else if(iterations==1)s.one_iteration++;else s.multiple_iterations++;
        Joints q;bool valid=true;
        for(int k=0;k<7;k++) {
            q[k]=unpack(w[k]);valid=valid&&std::isfinite(q[k])&&q[k]>=f.model[21*k+19]&&q[k]<=f.model[21*k+20];
            s.max_joint_step=std::max(s.max_joint_step,std::abs(q[k]-previous[k]));
            if(row<ref.rows.size())s.max_delta_old=std::max(s.max_delta_old,std::abs(q[k]-ref.rows[row][k]));
        }
        const Pose actual=fk(f,q);
        const double pe=position_error(actual,targets[row]),ae=angle_error(actual,f.rotation);
        s.max_position=std::max(s.max_position,pe);s.max_angle=std::max(s.max_angle,ae);
        valid=valid&&std::isfinite(pe)&&std::isfinite(ae)&&pe<=f.options[0]&&ae<=f.options[1];
        if(valid)s.verified_ok++;
        previous=q;
    }
    if(hi(call.header[0])==OK)require(!rejected&&hi(call.header[3])==targets.size()&&s.first_rejected==NONE,"OK prefix semantics");
    if(hi(call.header[0])==PARTIAL)require(rejected&&s.first_rejected+1==hi(call.header[3]),"PARTIAL prefix semantics");
    require(s.accepted_iterations+s.failed_iterations==hi(call.header[4]),"row/header iteration sum mismatch");
    std::cout<<std::setprecision(12)<<"CHAIN "<<name<<" requested="<<s.requested<<" reported_ok="<<s.reported_ok
        <<" verified_ok="<<s.verified_ok<<" old_ok="<<s.legacy_ok<<" status="<<hi(call.header[0])
        <<" first_rejected="<<s.first_rejected<<" iterations="<<hi(call.header[4])
        <<" zero_iterations="<<s.zero_iterations<<" one_iteration="<<s.one_iteration<<" multiple_iterations="<<s.multiple_iterations
        <<" accepted_iterations="<<s.accepted_iterations<<" failed_iterations="<<s.failed_iterations
        <<" max_position_m="<<s.max_position<<" max_angle_rad="<<s.max_angle
        <<" max_joint_step_rad="<<s.max_joint_step<<" max_delta_old_rad="<<s.max_delta_old<<'\n';
    require(s.verified_ok==s.reported_ok,"candidate reported OK but independent FP64 check rejects: "+name);
    require(s.max_joint_step<=0.12,"candidate branch discontinuity exceeds production max_joint_step_rad: "+name);
    if(require_all)require(s.verified_ok==targets.size(),"throughput target cannot count fallback rows: "+name);
    return s;
}

inline std::vector<Point> line64(const Fixture& f) {
    const Point o=origin(f);std::vector<Point> points;
    for(int i=1;i<=64;i++)points.push_back(Point{{o[0]+i*0.0005,o[1],o[2]}});
    return points;
}
inline std::vector<Point> arc32(const Fixture& f) {
    const Point o=origin(f);std::vector<Point> points;
    // Radius 12 mm and 0.4 mm arc-length increments, genuinely changing targets.
    for(int i=1;i<=32;i++){double a=i*(0.0004/0.012);points.push_back(Point{{o[0]+.012*std::sin(a),o[1]+.012*(1-std::cos(a)),o[2]}});}
    return points;
}
inline ChainSummary run_chain(const std::string& name,const Fixture& f,const std::vector<Point>& p,bool all=false) {
    Invocation call(f);call.points(p);call.run(IK_CHAIN,uint32_t(p.size()));return verify_chain(name,f,p,call,all);
}
}
