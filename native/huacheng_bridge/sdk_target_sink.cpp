#include "sdk_target_sink.hpp"
#include "robot.h"
#include <stdexcept>
using R=HCXSDKLib::RobotManager;
namespace tcb {
SdkTargetSink::SdkTargetSink(int robot):robot_(robot){
    if(robot<1||robot>32)throw std::runtime_error("invalid robot id");
}
void SdkTargetSink::prepare(const MeasuredTransportContract& c){
    prepared_=false;
    if(!c.delivery_semantics_verified||!c.clear_route_stops_passthrough_verified||!c.external_watchdog_verified||
       !std::isfinite(c.cycle_s)||c.cycle_s<.002||c.cycle_s>.004||c.evidence_sha256.size()!=64||
       c.evidence_sha256.find_first_not_of("0123456789abcdef")!=std::string::npos)
        throw std::runtime_error("REAL_STREAM_NOT_COMMISSIONED: measured transport/stop/watchdog evidence missing");
    bool softnormal=false;std::vector<std::string> alarms;std::vector<float> q;
    if(!R::getLinkStatus()||!R::getRobotSoftEmergencyStopStatus(softnormal)||!softnormal||R::isAlarming(alarms)||
       !R::getSingleRobotEnableStatus(robot_)||R::getRobotProtectStatus(robot_)||
       R::getRobotMoveState(robot_)!=0||!R::getJoints(robot_,q,true)||q.size()!=7)
        throw std::runtime_error("controller is not in commissioned passthrough state");
    for(int i=0;i<7;i++)if(!std::isfinite(q[i])||R::getCurrentRunMode(robot_,i)!=0)
        throw std::runtime_error("seven position axes required");
    // This adapter never enables motors, clears faults, changes mode or disables protection.
    // Switching protection and the required >=3 s settling belong to a commissioned supervisor.
    prepared_=true;
}
bool SdkTargetSink::submit(const Joints& q){
    if(!prepared_)throw std::runtime_error("transport not prepared");
    for(size_t i=0;i<7;i++){
        if(!std::isfinite(q[i]))throw std::runtime_error("nonfinite target");
        buffer_[i]=q[i];
    }
    if(!R::getLinkStatus())return false;
    return R::PluseToServo(robot_,buffer_); // exactly one call; never retry an uncertain send
}
bool SdkTargetSink::request_stop(){
    if(!prepared_)return false;
    prepared_=false;
    // Request accepted != robot stopped. The supervisor must independently verify standstill.
    return R::clearRobotRoute(robot_,true);
}
}
