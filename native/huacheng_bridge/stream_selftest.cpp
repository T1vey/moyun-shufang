// Deterministic failure injection against the exact submission loop. No SDK link.
#include "stream_core.hpp"
#include <iostream>
#include <limits>
using namespace tcb;
static void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
struct Clock final:StreamClock {
    double t=0,delay=0;int waits=0,delay_on=1;
    double now() override{return t;}
    void wait_until(double due) override{t=std::max(t,due);if(++waits==delay_on)t+=delay;}
};
struct Sink final:TargetSink {
    Clock& clock;int calls=0,stopcalls=0,fail_on=0,throw_on=0;double call_time=0;bool stop_ok=true;
    explicit Sink(Clock& c):clock(c){}
    bool submit(const Joints&) override{++calls;clock.t+=call_time;if(calls==throw_on)throw std::runtime_error("lost ack");return calls!=fail_on;}
    bool request_stop() override{++stopcalls;return stop_ok;}
};
int main(){try{
    StreamLimits limits;limits.lower.fill(-180);limits.upper.fill(180);limits.velocity_deg_s.fill(10);
    std::vector<Target> frames;for(int i=0;i<5;i++){Target t{.004*i,{}};t.degrees.fill(float(.01*i));frames.push_back(t);}
    Joints initial{};auto no=[](){return false;};int tests=0;
    {Clock c;Sink s(c);auto r=submit_stream(frames,limits,initial,s,c,no);check(s.calls==5&&r.acknowledged==5&&r.state=="SUBMITTED_AWAITING_FEEDBACK"&&!r.physical_completion_confirmed&&s.stopcalls==0,"completion semantics");++tests;}
    {Clock c;c.delay=.002;c.delay_on=3;Sink s(c);auto r=submit_stream(frames,limits,initial,s,c,no);check(s.calls==2&&r.state=="DEADLINE_MISSED"&&s.stopcalls==1,"no late catchup");++tests;}
    {Clock c;Sink s(c);s.fail_on=2;auto r=submit_stream(frames,limits,initial,s,c,no);check(s.calls==2&&r.acknowledged==1&&r.state=="SUBMISSION_UNCERTAIN"&&s.stopcalls==1,"no retry on false ack");++tests;}
    {Clock c;Sink s(c);s.throw_on=2;s.stop_ok=false;auto r=submit_stream(frames,limits,initial,s,c,no);check(s.calls==2&&r.stop_requested&&!r.stop_request_accepted&&!r.physical_completion_confirmed,"unknown stop");++tests;}
    {Clock c;Sink s(c);s.call_time=.005;auto r=submit_stream(frames,limits,initial,s,c,no);check(s.calls==1&&r.state=="SDK_CALL_OVERRUN"&&s.stopcalls==1,"blocked call overrun");++tests;}
    {Clock c;Sink s(c);auto r=submit_stream(frames,limits,initial,s,c,[](){return true;});check(!s.calls&&!s.stopcalls&&r.state=="CANCELLED","cancel before send");++tests;}
    {Clock c;Sink s(c);auto r=submit_stream(frames,limits,initial,s,c,[&](){return s.calls==2;});check(s.calls==2&&s.stopcalls==1&&r.state=="CANCELLED","cancel during stream");++tests;}
    for(int fault=0;fault<6;fault++){
        auto bad=frames;auto lim=limits;auto start=initial;
        if(fault==0)bad[3].degrees[2]=std::numeric_limits<float>::quiet_NaN();
        if(fault==1)bad[3].degrees[2]=181;
        if(fault==2)bad[3].time_s=bad[2].time_s;
        if(fault==3)bad[3].degrees[2]=1;
        if(fault==4)start[2]=1;
        if(fault==5)lim.period_s=0;
        Clock c;Sink s(c);bool rejected=false;try{submit_stream(bad,lim,start,s,c,no);}catch(const std::runtime_error&){rejected=true;}
        check(rejected&&s.calls==0&&s.stopcalls==0,"validate all targets before any I/O");++tests;
    }
    std::cout<<"{\"tests\":"<<tests<<",\"passed\":true,\"sdk_linked\":false,\"physical_motion\":false}"<<std::endl;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 2;}}
