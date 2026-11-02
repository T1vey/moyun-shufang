#pragma once
#include "stream_core.hpp"
#include <vector>
namespace tcb {
// Built for later commissioning. No GUI/CLI currently constructs this adapter.
// A live SdkSession must outlive this object. Call only from one SDK owner thread.
struct MeasuredTransportContract {
    bool delivery_semantics_verified=false;
    bool clear_route_stops_passthrough_verified=false;
    bool external_watchdog_verified=false;
    double cycle_s=0;
    std::string evidence_sha256;
};
class SdkTargetSink final:public TargetSink {
    int robot_;bool prepared_=false;std::vector<float> buffer_=std::vector<float>(7);
public:
    explicit SdkTargetSink(int robot);
    void prepare(const MeasuredTransportContract& contract);
    bool submit(const Joints& target) override;
    bool request_stop() override;
};
}
