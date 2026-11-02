// Read-only process: does not enable, disable protections, clear alarms or send targets.
#include "sdk_adapter.hpp"
#include <iostream>
#include <iomanip>
#include <stdexcept>
#include <string>
static std::string quoted(const std::string&s){std::string o="\"";for(unsigned char c:s){if(c=='"'||c=='\\')o+='\\';if(c>=32&&c<127)o+=char(c);}return o+'"';}
int main(int argc,char**argv){
    try{
        if(argc!=5)throw std::runtime_error("Usage: tcb_sdk_probe LOCAL_IP CONTROLLER_IP PORT ROBOT_ID");
        int port=std::stoi(argv[3]),robot=std::stoi(argv[4]);if(port<1||port>65535||robot<1||robot>32)throw std::runtime_error("invalid port or robot id");
        tcb::SdkSession session(argv[1],argv[2],unsigned(port));auto q=session.read_joints(robot);
        std::cout<<"TCB_JSON {\"read_only\":true,\"sdk_version\":"<<quoted(session.library_version())<<",\"host_version\":"<<quoted(session.host_version())<<",\"joint_degrees\":[";
        for(size_t i=0;i<q.size();i++){if(i)std::cout<<',';std::cout<<std::setprecision(10)<<q[i];}
        std::cout<<"],\"controller_timestamp_available\":false}"<<std::endl;return 0;
    }catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 2;}
}
