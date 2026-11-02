#include "tcb_lineart_accel.h"
#include <fstream>
#include <iostream>
#include <vector>
#include <cstdint>
unsigned read32(std::ifstream &f){uint32_t v=0;f.read((char*)&v,4);if(!f)throw "truncated vector";return v;}
int main(){
    std::ifstream f("lineart_vectors.bin",std::ios::binary);
    if(!f){std::cerr<<"missing vectors";return 1;}
    if(read32(f)!=0x31414c54)return 2;
    unsigned cases=read32(f);
    for(unsigned test=0;test<cases;++test){
        unsigned w=read32(f),h=read32(f),passes=read32(f),n=w*h;
        std::vector<unsigned char> bytes(n),gold(n);
        f.read((char*)bytes.data(),n);f.read((char*)gold.data(),n);if(!f)return 3;
        // The RTL co-sim wrapper snapshots the declared AXI depth, even for a tiny image.
        std::vector<ap_uint<64>> a((LINEART_MAX_DIM*LINEART_MAX_DIM+63)/64),b(a.size());
        for(unsigned i=0;i<n;++i)a[i/64][i%64]=bytes[i]!=0;
        for(unsigned k=0;k<passes;++k){
            unsigned deleted=0,id=0;
            if(tcb_lineart_accel(a.data(),b.data(),w,h,deleted,id) || id!=LINEART_ID)return 4;
            unsigned before=0,after=0;
            for(unsigned i=0;i<n;++i){before+=a[i/64][i%64];after+=b[i/64][i%64];}
            if(bool(before-after)!=bool(deleted) || deleted>1){std::cerr<<"deletion flag mismatch";return 5;}
            a.swap(b);
        }
        for(unsigned i=0;i<n;++i)if(bool(a[i/64][i%64])!=bool(gold[i])){
            std::cerr<<"mismatch case="<<test<<" x="<<i%w<<" y="<<i/w<<"\n";return 6;}
        for(unsigned i=n;i<((n+63)/64)*64;++i)if(a[i/64][i%64])return 7;
        std::cout<<"LINEART_PASS case="<<test<<" size="<<w<<"x"<<h<<" passes="<<passes<<std::endl;
    }
    std::vector<ap_uint<64>> a((LINEART_MAX_DIM*LINEART_MAX_DIM+63)/64),b(a.size());
    a[0]=123;b[0]=456;unsigned deleted=9,id=0;
    if(tcb_lineart_accel(a.data(),b.data(),0,1,deleted,id)!=1 || b[0]!=456 || deleted!=0)return 8;
    return 0;
}
