// Offline stream scheduler. This binary has NO hardware SDK link or motion path.
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
static uint32_t u32(const unsigned char*p){return uint32_t(p[0])|(uint32_t(p[1])<<8)|(uint32_t(p[2])<<16)|(uint32_t(p[3])<<24);}
static double f64(const unsigned char*p){double d;std::memcpy(&d,p,8);return d;}
static float f32(const unsigned char*p){float d;std::memcpy(&d,p,4);return d;}
static uint32_t crc32(const unsigned char*p,size_t n){uint32_t crc=0xffffffffu;for(size_t i=0;i<n;i++){crc^=p[i];for(int k=0;k<8;k++)crc=(crc>>1)^(0xedb88320u&uint32_t(-int(crc&1)));}return crc^0xffffffffu;}
int main(int argc,char**argv){
    try{
        if(argc!=3|| (std::string(argv[1])!="--simulate-fast"&&std::string(argv[1])!="--simulate-realtime"))throw std::runtime_error("Usage: tcb_runner --simulate-fast|--simulate-realtime trajectory.bin; hardware streaming is not commissioned");
        uint16_t endian=1;if(*reinterpret_cast<unsigned char*>(&endian)!=1)throw std::runtime_error("little endian host required");
        std::ifstream input(argv[2],std::ios::binary|std::ios::ate);if(!input)throw std::runtime_error("cannot open trajectory");
        auto size=input.tellg();if(size<28||size>33000028)throw std::runtime_error("invalid trajectory length");
        std::vector<unsigned char>b(static_cast<size_t>(size));input.seekg(0);input.read(reinterpret_cast<char*>(b.data()),size);if(!input)throw std::runtime_error("truncated trajectory");
        uint32_t count=u32(b.data()+16);
        if(std::memcmp(b.data(),"TCBPLAN1",8)||u32(b.data()+8)!=1||u32(b.data()+12)!=7||count<2||count>750000||u32(b.data()+20)!=44||b.size()!=28+size_t(count)*44||u32(b.data()+24)!=crc32(b.data()+28,b.size()-28))throw std::runtime_error("trajectory header or CRC mismatch");
        double previous=-1;
        for(uint32_t i=0;i<count;i++){
            auto p=b.data()+28+size_t(i)*44;double t=f64(p);
            if(!std::isfinite(t)||t<=previous||t>7200||(i==0&&t!=0)||(i&&t-previous>.00400001)||u32(p+36)>5)throw std::runtime_error("invalid time or phase");
            for(int j=0;j<7;j++){float q=f32(p+8+j*4);if(!std::isfinite(q)||std::abs(q)>720)throw std::runtime_error("invalid seven-axis target");}
            previous=t;
        }
        bool realtime=std::string(argv[1])=="--simulate-realtime";
        auto start=std::chrono::steady_clock::now();double maxlate=0;uint32_t misses=0;
        for(uint32_t i=0;i<count;i++){
            if(realtime){
                auto due=start+std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(f64(b.data()+28+size_t(i)*44)));
                std::this_thread::sleep_until(due);double late=std::chrono::duration<double>(std::chrono::steady_clock::now()-due).count();maxlate=std::max(maxlate,late);if(late>.001)misses++;
            }
        }
        std::cout<<std::setprecision(12)<<"{\"simulation\":true,\"physical_motion\":false,\"frames\":"<<count<<",\"duration_s\":"<<previous<<",\"timing_measured\":"<<(realtime?"true":"false")<<",\"max_lateness_s\":";
        if(realtime)std::cout<<maxlate;else std::cout<<"null";
        std::cout<<",\"deadline_misses\":";
        if(realtime)std::cout<<misses;else std::cout<<"null";
        std::cout<<",\"task_complete\":true,\"execution_finished\":true}"<<std::endl;
        return 0;
    }catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 2;}
}
