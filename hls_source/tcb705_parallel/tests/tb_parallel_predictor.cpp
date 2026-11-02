#include "parallel_test_support.hpp"
using namespace parallel_test;

// Independent black-box check of the documented target-history guard. An
// ineligible target must keep the original clipped linear initial guess. A
// zero-iteration output must equal that initial guess exactly: an unverified
// extrapolation is never counted as successful without the FP64 pose checks.
static bool eligible(const std::vector<Point>& p,unsigned n) {
    if(n<3)return false;
    double a2=0,b2=0,c2=0,ab=0,bc=0;
    for(int k=0;k<3;k++) {
        const double a=p[n][k]-p[n-1][k],b=p[n-1][k]-p[n-2][k],c=p[n-2][k]-p[n-3][k];
        a2+=a*a;b2+=b*b;c2+=c*c;ab+=a*b;bc+=b*c;
    }
    return b2>1e-18&&c2>1e-18&&std::abs(a2-b2)<.05*b2&&std::abs(b2-c2)<.05*c2
        &&ab>.98*std::max(a2,b2)&&bc>.98*std::max(b2,c2);
}
static void check(const char* name,const Fixture& f,const std::vector<Point>& p,bool all=true) {
    Invocation c(f);c.points(p);c.run(IK_CHAIN,unsigned(p.size()));
    verify_chain(name,f,p,c,all);
    Joints last=f.seed,previous=f.seed,older=f.seed;
    unsigned target_allowed=0,linear_guarded=0,quadratic_joints=0,zero_output_checked=0;
    for(unsigned n=0;n<hi(c.header[3]);n++) {
        const uint64_t* out=c.output+16*n;if(lo(out[10]))break;
        const bool allow=eligible(p,n);target_allowed+=allow;
        if(n>=3&&!allow)linear_guarded++;
        Joints q;for(int k=0;k<7;k++) {
            q[k]=unpack(out[k]);double guess=n?2*last[k]-previous[k]:last[k];
#ifndef TCB_TEST_BASELINE
            if(allow) {
                const double second=(last[k]-previous[k])-(previous[k]-older[k]),proposed=guess+second;
                if(std::abs(second)<=.25*std::max(std::abs(last[k]-previous[k]),1e-6)
                   &&std::abs(proposed-last[k])<=f.options[3]
                   &&proposed>=f.model[21*k+19]&&proposed<=f.model[21*k+20]) {
                    guess=proposed;quadratic_joints++;
                }
            }
#endif
            guess=std::max(f.model[21*k+19],std::min(f.model[21*k+20],guess));
            if(unpack(out[9])==0)require(q[k]==guess,std::string("zero-iteration initial guess mismatch: ")+name);
        }
        if(unpack(out[9])==0)zero_output_checked++;
        older=previous;previous=last;last=q;
    }
    std::cout<<"PREDICTOR_GUARD "<<name<<" target_allowed="<<target_allowed<<" linear_guarded="<<linear_guarded
        <<" quadratic_joint_guesses="<<quadratic_joints<<" zero_output_checked="<<zero_output_checked<<'\n';
}
int main() {
    try {
        Fixture f;const Point o=origin(f);
        std::vector<Point> corner,reverse,repeated,variable,zigzag,jump;
        for(int i=1;i<=8;i++) {
            const Point p={{o[0]+i*.0005,o[1],o[2]}};
            corner.push_back(p);reverse.push_back(p);repeated.push_back(p);jump.push_back(p);
        }
        for(int i=1;i<=8;i++) {
            corner.push_back(Point{{o[0]+.004,o[1]+i*.0005,o[2]}});
            reverse.push_back(Point{{o[0]+.004-i*.0005,o[1],o[2]}});
        }
        for(int i=0;i<4;i++)repeated.push_back(repeated.back());
        for(int i=1;i<=8;i++)repeated.push_back(Point{{o[0]+.004,o[1]+i*.0005,o[2]}});
        double offset=0;Point z=o;
        for(int i=0;i<24;i++) {
            offset+=(i%2)?.0008:.0002;variable.push_back(Point{{o[0]+offset,o[1],o[2]}});
            z[i%2]+=.0004;zigzag.push_back(z);
        }
        for(int i=1;i<=8;i++)jump.push_back(Point{{o[0]+.009+i*.0005,o[1],o[2]}});
        check("corner90",f,corner);check("reverse180",f,reverse);check("duplicate_then_turn",f,repeated);
        check("variable_step_0p2_0p8mm",f,variable);check("zigzag90",f,zigzag);check("step_jump5mm",f,jump);
        // Changes immediately around the direction/length smoothness threshold.
        for(int test=0;test<2;test++) {
            std::vector<Point> p;double position=0,step=.0005;const double ratio=test?1.025:1.019;
            for(int i=0;i<16;i++){position+=step;p.push_back(Point{{o[0]+position,o[1],o[2]}});step*=ratio;}
            check(test?"spacing_guard_outside":"spacing_guard_inside",f,p);
        }
        {std::vector<Point> p=line64(f);p.resize(9);p[8][0]=std::numeric_limits<double>::quiet_NaN();
         Invocation c(f);c.points(p);c.run(IK_CHAIN,9);verify_chain("NaN_after_smooth_prefix",f,p,c);
         require(hi(c.header[0])==PARTIAL&&lo(c.header[4])==8&&hi(c.header[3])==9,"invalid tail corrupted accepted prefix");}
        std::cout<<"PREDICTOR GUARDS PASS. Zero iterations still underwent independent strict FP64 pose validation.\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;}
}
