// Static commissioning capture. No enable, mode change, origin reset or motion.
#include "sdk_adapter.hpp"
#include "robot.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
using R=HCXSDKLib::RobotManager;
static void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
template<class T> static void array(const std::vector<T>& v){
    std::cout<<'[';for(size_t i=0;i<v.size();++i){require(std::isfinite(v[i]),"nonfinite SDK value");if(i)std::cout<<',';std::cout<<v[i];}std::cout<<']';
}
static void matrix(const std::vector<std::vector<double>>& rows){
    std::cout<<'[';for(size_t i=0;i<rows.size();++i){if(i)std::cout<<',';array(rows[i]);}std::cout<<']';
}
static std::string quoted(const std::string& s){
    std::string out="\"";for(unsigned char c:s){if(c=='"'||c=='\\')out+='\\';if(c>=32)out+=char(c);}return out+'"';
}
int main(int argc,char** argv){
    try{
        require(argc==5,"Usage: tcb_commission_probe LOCAL_IP CONTROLLER_IP PORT ROBOT_ID (read only)");
        const int port=std::stoi(argv[3]),rid=std::stoi(argv[4]);
        require(port>0&&port<=65535&&rid>0&&rid<=32,"invalid port/robot id");
        tcb::SdkSession session(argv[1],argv[2],unsigned(port));
        uint16_t jointms=0,worldms=0;
        require(R::getPosReFreshMS(rid,jointms,worldms),"feedback refresh periods unavailable");
        require(jointms>0&&jointms<=1000&&worldms>0&&worldms<=1000,"unsupported feedback refresh periods");
        // Wait across at least two advertised refresh periods. No controller timestamp is invented.
        std::this_thread::sleep_for(std::chrono::milliseconds(2*std::max(jointms,worldms)));
        require(R::getRobotMoveState(rid)==0,"robot must be stationary for capture");
        const auto started=std::chrono::steady_clock::now();
        auto before=session.read_joints(rid);
        std::vector<double> q(before.begin(),before.end()),flange,tcp;
        std::vector<float> world;
        uint16_t tool=0,workspace=0;R::RobotToolCoordParam toolparam;R::RobotWorkSpaceParam workparam;
        require(R::getRobotCurrentToolCoord(rid,tool,toolparam),"current tool unavailable");
        require(R::getRobotCurrentWorkSpace(rid,workspace,workparam),"current workspace unavailable");
        require(R::forwardKinematics(rid,q,flange,0,0)&&flange.size()==6,"base flange FK unavailable");
        require(R::forwardKinematics(rid,q,tcp,tool,0)&&tcp.size()==6,"base TCP FK unavailable");
        require(R::getWorlds(rid,world,true)&&world.size()==6,"world feedback unavailable");
        std::vector<R::RobotDHParam> dh;const bool dhok=R::getRobotDHParams(rid,dh);
        std::this_thread::sleep_for(std::chrono::milliseconds(2*std::max(jointms,worldms)));
        auto after=session.read_joints(rid);double delta=0;
        for(size_t i=0;i<7;i++)delta=std::max(delta,double(std::abs(after[i]-before[i])));
        require(R::getRobotMoveState(rid)==0&&delta<=.02,"robot moved during capture; discard sample");
        uint16_t toolafter=0,workafter=0;R::RobotToolCoordParam ta;R::RobotWorkSpaceParam wa;
        require(R::getRobotCurrentToolCoord(rid,toolafter,ta)&&R::getRobotCurrentWorkSpace(rid,workafter,wa),"context reread failed");
        require(tool==toolafter&&workspace==workafter,"tool/workspace changed during capture");
        std::cout<<std::setprecision(12)<<"TCB_JSON {\"schema\":\"tcb705-static-capture-v1\",\"read_only\":true,\"robot_id\":"<<rid
          <<",\"sdk_version\":"<<quoted(session.library_version())<<",\"host_version\":"<<quoted(session.host_version())
          <<",\"joint_degrees\":";array(before);std::cout<<",\"joint_degrees_after\":";array(after);
        std::cout<<",\"fk_flange_base_raw\":";array(flange);std::cout<<",\"fk_tcp_base_raw\":";array(tcp);
        std::cout<<",\"world_feedback_raw\":";array(world);
        std::cout<<",\"tool_id\":"<<tool<<",\"workspace_id\":"<<workspace<<",\"tool_method\":"<<toolparam.method
          <<",\"tool_name\":"<<quoted(toolparam.name)<<",\"tool_points_raw\":";matrix(toolparam.points);
        std::cout<<",\"workspace_name\":"<<quoted(workparam.name)<<",\"workspace_points_raw\":";matrix(workparam.points);
        std::cout<<",\"dh_available\":"<<(dhok?"true":"false")<<",\"dh_raw\":[";
        if(dhok)for(size_t i=0;i<dh.size();i++){if(i)std::cout<<',';array(std::vector<double>{dh[i].theta,dh[i].d,dh[i].a,dh[i].alpha});}
        std::cout<<"],\"joint_refresh_ms\":"<<jointms<<",\"world_refresh_ms\":"<<worldms
          <<",\"stationary_check_max_delta_deg\":"<<delta<<",\"capture_span_s\":"
          <<std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count()
          <<",\"controller_timestamp_available\":false,\"pose_convention_confirmed\":false}"<<std::endl;
    }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 2;}
}
