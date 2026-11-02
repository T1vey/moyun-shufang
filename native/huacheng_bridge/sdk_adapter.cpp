#include "sdk_adapter.hpp"
#include "robot.h"
#include "xoip.h"
#include <cmath>
#include <stdexcept>
namespace tcb {
SdkSession::SdkSession(const std::string&local,const std::string&remote,unsigned port){
    try {connected_=HCXSDKLib::RobotManager::init_data(local,remote,port);}
    catch(...){HCXSDKLib::RobotManager::stop_data();throw;}
    if(!connected_||!HCXSDKLib::RobotManager::getLinkStatus()){
        HCXSDKLib::RobotManager::stop_data();connected_=false;throw std::runtime_error("SDK connection failed");
    }
}
SdkSession::~SdkSession(){if(connected_){try{HCXSDKLib::RobotManager::stop_data();}catch(...){}}}
std::vector<float> SdkSession::read_joints(int robot){
    std::vector<float> q;
    if(!HCXSDKLib::RobotManager::getLinkStatus()||!HCXSDKLib::RobotManager::getJoints(robot,q,true)||q.size()!=7)throw std::runtime_error("seven-axis feedback unavailable");
    for(float x:q){if(!std::isfinite(x))throw std::runtime_error("nonfinite feedback");}
    return q;
}
std::string SdkSession::library_version()const{return HCXSDKLib::VersionManager::getLibVersion();}
std::string SdkSession::host_version()const{return HCXSDKLib::VersionManager::getHostVersion();}
}
