#include "tcb_planner_accel.h"
#include <fstream>
#include <iostream>
#include <cmath>
#include <cstring>
#include <stdexcept>
using namespace tcb_pl;
static uint64_t pack(double x){uint64_t u;std::memcpy(&u,&x,8);return u;}
static double unpack(uint64_t u){double x;std::memcpy(&x,&u,8);return x;}
static void require(bool b,const char*m){if(!b)throw std::runtime_error(m);}
int main(){
    uint64_t c[256]={},in[8192]={},out[24576]={},h[8]={},cancel[8]={};
    std::ifstream f("vectors.txt");double model[147],tool[16],opt[7],seed[7],rot[9],positions[6],expected[14],poses[32];
    for(double&v:model)f>>v;for(double&v:tool)f>>v;for(double&v:opt)f>>v;for(double&v:seed)f>>v;
    for(double&v:rot)f>>v;for(double&v:positions)f>>v;for(double&v:expected)f>>v;for(double&v:poses)f>>v;
    require(bool(f),"missing/malformed vectors");
    c[0]=uint64_t(ABI)|(uint64_t(MODEL)<<32);c[1]=42;
    for(int i=0;i<147;i++)c[2+i]=pack(model[i]);for(int i=0;i<16;i++)c[149+i]=pack(tool[i]);
    for(int i=0;i<7;i++){c[165+i]=pack(opt[i]);c[172+i]=pack(seed[i]);}for(int i=0;i<9;i++)c[179+i]=pack(rot[i]);
    for(int row=0;row<2;row++){for(int k=0;k<3;k++)in[4*row+k]=pack(positions[row*3+k]);in[4*row+3]=row+10;}
    tcb_planner_accel(c,in,out,h,cancel,IK_CHAIN,2,2,7,9);
    require(uint32_t(h[0]>>32)==OK && uint32_t(h[3]>>32)==2,"IK prefix failed");
    for(int row=0;row<2;row++)for(int k=0;k<7;k++)require(std::abs(unpack(out[row*16+k])-expected[row*7+k])<2e-7,"IK differs from independent CPU reference");
    for(int row=0;row<2;row++){for(int k=0;k<7;k++)in[row*8+k]=pack(expected[row*7+k]);in[row*8+7]=row+20;}
    tcb_planner_accel(c,in,out,h,cancel,FK_ROWS,2,2,7,10);
    require(uint32_t(h[0]>>32)==OK,"FK rows failed");
    for(int row=0;row<2;row++)for(int k=0;k<16;k++)require(std::abs(unpack(out[row*24+k])-poses[row*16+k])<5e-10,"FK differs from CPU reference");
    cancel[0]=uint64_t(11)|(uint64_t(7)<<32);
    tcb_planner_accel(c,in,out,h,cancel,FK_ROWS,2,2,7,11);
    require(uint32_t(h[0]>>32)==CANCELLED && uint32_t(h[3]>>32)==0,"cancel failed");
    c[0]^=1;tcb_planner_accel(c,in,out,h,cancel,FK_ROWS,2,2,7,12);
    require(uint32_t(h[0]>>32)==BAD_ABI,"ABI guard failed");c[0]^=1;
    tcb_planner_accel(c,in,out,h,cancel,IK_CHAIN,65,65,7,13);
    require(uint32_t(h[0]>>32)==BAD_INPUT,"capacity guard failed");
    std::cout<<"PASS: seven-axis IK_CHAIN, FK_ROWS, identity, cancellation, bounds\n";
}
