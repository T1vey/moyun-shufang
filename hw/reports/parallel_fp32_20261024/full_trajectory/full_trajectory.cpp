#include "../src/tests/controller_test_support.hpp"
#include <algorithm>
#include <map>
#include <chrono>
using namespace controller_test;
struct Node {unsigned index;int phase,stroke;Point p;Joints q;};
static double rotation_error(const Pose& p,const double* r) {
    double a[9]={};for(int i=0;i<3;i++)for(int j=0;j<3;j++)for(int k=0;k<3;k++)a[3*i+j]+=r[3*k+i]*p[4*k+j];
    const double s0=a[7]-a[5],s1=a[2]-a[6],s2=a[3]-a[1];
    return std::atan2(.5*std::sqrt(s0*s0+s1*s1+s2*s2),.5*(a[0]+a[4]+a[8]-1));
}
static double step(const Joints&a,const Joints&b){double d=0;for(int k=0;k<7;k++)d=std::max(d,std::abs(a[k]-b[k]));return d;}
int main() {
 try {
    std::ifstream input("nodes.txt");require(bool(input),"missing nodes input");unsigned count;input>>count;
    std::vector<Node> nodes(count);for(auto& n:nodes){input>>n.index>>n.phase>>n.stroke;for(double&v:n.p)input>>v;for(double&v:n.q)input>>v;}require(bool(input),"incomplete nodes input");
    Fixture f;double record_pe=0,record_ae=0,record_step=0;unsigned record_strict=0;
    std::ofstream recorded("recorded_preflight.csv");recorded<<"index,position_m,orientation_rad,joint_step_rad,strict_ok\n"<<std::setprecision(17);
    for(unsigned i=0;i<count;i++) {
        const Pose pose=fk(f,nodes[i].q);const double pe=position_error(pose,nodes[i].p),ae=rotation_error(pose,f.rotation),js=i?step(nodes[i].q,nodes[i-1].q):0;
        const bool strict=pe<=f.options[0]&&ae<=f.options[1];record_strict+=strict;
        record_pe=std::max(record_pe,pe);record_ae=std::max(record_ae,ae);record_step=std::max(record_step,js);
        recorded<<i<<','<<pe<<','<<ae<<','<<js<<','<<strict<<'\n';
    }
    recorded.close();std::cout<<std::setprecision(17)<<"SOURCE_PREFLIGHT nodes="<<count<<" original_strict="<<record_strict<<" max_position_m="<<record_pe<<" max_orientation_rad="<<record_ae<<" max_joint_step="<<record_step<<" physical_motion=false"<<std::endl;
    // The original home q is the initial seed, not a guessed IK branch.
    f.seed=nodes[0].q;Joints previous_seed=f.seed;
    std::ofstream output("rows.csv");output<<"index,phase,stroke,method,header_status,row_status,position_m,orientation_rad,joint_step_rad,delta_recorded_q_rad,old_strict_ok,fp32_budget_ok,cpu_iterations";for(int k=0;k<7;k++)output<<",q"<<k;output<<'\n'<<std::setprecision(17);
    std::ofstream calls("calls.csv");calls<<"call,batch_start,first_target,requested,accepted,done,status,first_rejected\n";
    unsigned accepted=0,fallback=0,unresolved=0,call_count=0,rejected_calls=0,old_strict=0,offline_bad=0;
    auto save=[&](unsigned index,const char* method,uint32_t status,uint32_t row_status,const Joints&q,unsigned iterations) {
        const Node& n=nodes[index];const Pose pose=fk(f,q);double pe=position_error(pose,n.p),ae=rotation_error(pose,f.rotation),js=step(q,f.seed),delta=step(q,n.q);
        bool strict=pe<=f.options[0]&&ae<=f.options[1],budget=pe<=1e-5&&ae<=1e-4;
        for(int k=0;k<7;k++)budget=budget&&std::isfinite(q[k])&&q[k]>=f.model[21*k+19]&&q[k]<=f.model[21*k+20];
        old_strict+=strict;offline_bad+=!budget;
        output<<index<<','<<n.phase<<','<<n.stroke<<','<<method<<','<<status<<','<<row_status<<','<<pe<<','<<ae<<','<<js<<','<<delta<<','<<strict<<','<<budget<<','<<iterations;
        for(double v:q)output<<','<<v;output<<'\n';previous_seed=f.seed;f.seed=q;
    };
    const auto begin=std::chrono::steady_clock::now();
    for(unsigned batch=1;batch<count;batch+=64) {
        const unsigned end=std::min(count,batch+64);unsigned next=batch;
        while(next<end) {
            std::vector<Point> targets;for(unsigned i=next;i<end;i++)targets.push_back(nodes[i].p);
            Invocation call(f);call.job=1000+call_count;call.points(targets);call.run(IK_CHAIN,unsigned(targets.size()));call.header_identity(IK_CHAIN,unsigned(targets.size()));
            const uint32_t status=hi(call.header[0]),done=hi(call.header[3]);unsigned good=0;uint32_t row_status=NONE;
            require(status==OK||status==PARTIAL||status==BAD_INPUT||status==BAD_MODEL,"unexpected header status");
            for(unsigned row=0;row<done;row++) {
                const uint64_t*w=call.output+16*row;row_status=lo(w[10]);
                if(row_status!=0){require(row+1==done,"failure outside prefix tail");break;}
                require(hi(w[10])==1000+row,"row identity");require(w[11]==pair(call.generation,42),"row generation");
                Joints q;for(int k=0;k<7;k++)q[k]=unpack(w[k]);save(next+row,"pl",status,0,q,0);good++;accepted++;
            }
            calls<<call_count++<<','<<batch<<','<<next<<','<<targets.size()<<','<<good<<','<<done<<','<<status<<','<<lo(call.header[4])<<'\n';
            next+=good;
            if(status==OK){require(next==end&&done==targets.size(),"OK did not consume whole remainder");break;}
            rejected_calls++;require(next<end,"rejected after full batch");
            if(status==PARTIAL)require(lo(call.header[4])==good&&done==good+1,"PARTIAL prefix semantics");
            // Repair precisely the rejected point with the original FP64 solver,
            // using the last accepted q. Resume the unprocessed batch suffix.
            Pose target={{1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1}};
            for(int r=0;r<3;r++){target[4*r+3]=nodes[next].p[r];for(int c=0;c<3;c++)target[4*r+c]=f.rotation[3*r+c];}
            Joints q;double stats[3]={},pose[16]={};
            const int ref_status=run_row7(false,f.model,f.tool,target.data(),f.seed.data(),f.seed.data(),f.options,q.data(),stats,pose);
            const Pose refpose=fk(f,q);const bool ref_ok=!ref_status&&position_error(refpose,nodes[next].p)<=f.options[0]&&rotation_error(refpose,f.rotation)<=f.options[1];
            if(ref_ok){fallback++;save(next,"cpu_fallback",status,row_status,q,unsigned(stats[2]));}
            else {
                unresolved++;save(next,"unresolved_historical_reseed",status,row_status,nodes[next].q,unsigned(stats[2]));
                std::cout<<"UNRESOLVED target="<<next<<" cpu_status="<<ref_status<<" historical_reseed_for_audit_only=true\n";
            }
            next++;
        }
    }
    const double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count();
    output.close();calls.close();require(accepted+fallback+unresolved==count-1,"missing target accounting");
    std::cout<<"FULL_TRAJECTORY targets="<<count-1<<" pl_accepted="<<accepted<<" cpu_fallback="<<fallback<<" unresolved="<<unresolved<<" rejected_calls="<<rejected_calls<<" total_calls="<<call_count<<" old_strict="<<old_strict<<" offline_budget_failures="<<offline_bad<<" host_seconds="<<seconds<<" physical_motion=false"<<std::endl;
    return offline_bad||unresolved?2:0;
 }catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}
}
