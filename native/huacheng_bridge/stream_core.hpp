#pragma once
// Vendor-independent submission loop. Submission is NEVER physical completion.
#include <array>
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <functional>
#include <stdexcept>
#include <string>
#include <vector>
namespace tcb {
using Joints=std::array<float,7>;
struct Target {double time_s;Joints degrees;};
struct StreamLimits {
    double period_s=.004,late_tolerance_s=.001,start_tolerance_deg=.2;
    Joints lower{},upper{},velocity_deg_s{};
};
class StreamClock {
public:virtual ~StreamClock()=default;virtual double now()=0;virtual void wait_until(double absolute_s)=0;
};
class TargetSink {
public:virtual ~TargetSink()=default;
    // false or exception may mean accepted but acknowledgement lost. Never retry.
    virtual bool submit(const Joints& target)=0;
    // Only a request acknowledgement, never evidence that the robot stopped.
    virtual bool request_stop()=0;
};
struct SubmissionResult {
    std::string state="NOT_STARTED";size_t acknowledged=0;
    double max_lateness_s=0;bool stop_requested=false,stop_request_accepted=false;
    bool physical_completion_confirmed=false;
};
inline void validate_stream(const std::vector<Target>& targets,const StreamLimits& limits,const Joints& initial){
    if(targets.size()<2||targets.size()>150000||!std::isfinite(limits.period_s)||limits.period_s<.002||limits.period_s>.004||
       !std::isfinite(limits.late_tolerance_s)||limits.late_tolerance_s<=0||limits.late_tolerance_s>=limits.period_s||
       !std::isfinite(limits.start_tolerance_deg)||limits.start_tolerance_deg<=0||limits.start_tolerance_deg>1)
        throw std::runtime_error("invalid stream limits");
    for(size_t j=0;j<7;j++){
        if(!std::isfinite(limits.lower[j])||!std::isfinite(limits.upper[j])||limits.lower[j]>=limits.upper[j]||
           !std::isfinite(limits.velocity_deg_s[j])||limits.velocity_deg_s[j]<=0||!std::isfinite(initial[j]))
            throw std::runtime_error("invalid joint limits or feedback");
        if(std::abs(initial[j]-targets.front().degrees[j])>limits.start_tolerance_deg)
            throw std::runtime_error("initial feedback does not match trajectory");
    }
    for(size_t i=0;i<targets.size();i++){
        const auto& frame=targets[i];double dt=i?frame.time_s-targets[i-1].time_s:0;
        if(!std::isfinite(frame.time_s)||frame.time_s<0||frame.time_s>7200||(i==0&&frame.time_s!=0)||
           (i&&(dt<=0||dt>limits.period_s+1e-8))||
           (i&&i+1<targets.size()&&std::abs(dt-limits.period_s)>1e-8))
            throw std::runtime_error("invalid trajectory cadence");
        for(size_t j=0;j<7;j++){
            const float q=frame.degrees[j];
            if(!std::isfinite(q)||q<limits.lower[j]||q>limits.upper[j])throw std::runtime_error("target outside joint limits");
            if(i&&std::abs(double(q)-targets[i-1].degrees[j])>limits.velocity_deg_s[j]*dt+1e-5)
                throw std::runtime_error("target step exceeds velocity bound");
        }
    }
}
inline SubmissionResult submit_stream(const std::vector<Target>& targets,const StreamLimits& limits,
    const Joints& initial,TargetSink& sink,StreamClock& clock,const std::function<bool()>& cancelled){
    validate_stream(targets,limits,initial);SubmissionResult result;bool may_have_sent=false;
    auto fail=[&](const char* reason){
        result.state=reason;
        if(may_have_sent){result.stop_requested=true;try{result.stop_request_accepted=sink.request_stop();}catch(...){}}
        return result;
    };
    try{
        const double start=clock.now();if(!std::isfinite(start))return fail("CLOCK_INVALID");
        for(const auto& frame:targets){
            if(cancelled())return fail("CANCELLED");
            const double due=start+frame.time_s;clock.wait_until(due);
            if(cancelled())return fail("CANCELLED");
            const double before=clock.now(),late=before-due;
            if(!std::isfinite(late)||late<0)return fail("CLOCK_INVALID");
            result.max_lateness_s=std::max(result.max_lateness_s,late);
            if(late>limits.late_tolerance_s)return fail("DEADLINE_MISSED");
            may_have_sent=true;
            if(!sink.submit(frame.degrees))return fail("SUBMISSION_UNCERTAIN");
            ++result.acknowledged;
            const double after=clock.now(),elapsed=after-before;
            if(!std::isfinite(after)||elapsed<0)return fail("CLOCK_INVALID");
            // Bound the SDK call itself; never burst overdue targets to catch up.
            if(after-due>=limits.period_s)return fail("SDK_CALL_OVERRUN");
        }
        result.state="SUBMITTED_AWAITING_FEEDBACK";return result;
    }catch(...){return fail("TRANSPORT_EXCEPTION");}
}
}
