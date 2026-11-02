#pragma once
#include <string>
#include <vector>
namespace tcb {
class SdkSession {
    bool connected_=false;
public:
    SdkSession(const std::string&local,const std::string&remote,unsigned port);
    ~SdkSession();
    SdkSession(const SdkSession&)=delete;
    SdkSession&operator=(const SdkSession&)=delete;
    std::vector<float> read_joints(int robot);
    std::string library_version() const;
    std::string host_version() const;
};
}
