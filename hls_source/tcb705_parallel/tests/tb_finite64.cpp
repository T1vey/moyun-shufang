// Host-only edge-case test of the candidate's exact IEEE-754 finite classifier.
// Include the actual implementation, not a test copy of the exponent mask.
#include "../pl_math7_parallel.hpp"
#include <cstring>
#include <iostream>
#include <stdexcept>

int main() {
    struct Case {const char* name;uint64_t bits;bool expected;};
    const Case cases[]={
        {"positive_zero",UINT64_C(0x0000000000000000),true},
        {"negative_zero",UINT64_C(0x8000000000000000),true},
        {"positive_min_subnormal",UINT64_C(0x0000000000000001),true},
        {"negative_min_subnormal",UINT64_C(0x8000000000000001),true},
        {"positive_max_subnormal",UINT64_C(0x000fffffffffffff),true},
        {"negative_max_subnormal",UINT64_C(0x800fffffffffffff),true},
        {"positive_min_normal",UINT64_C(0x0010000000000000),true},
        {"negative_min_normal",UINT64_C(0x8010000000000000),true},
        {"positive_max_finite",UINT64_C(0x7fefffffffffffff),true},
        {"negative_max_finite",UINT64_C(0xffefffffffffffff),true},
        {"positive_infinity",UINT64_C(0x7ff0000000000000),false},
        {"negative_infinity",UINT64_C(0xfff0000000000000),false},
        {"positive_quiet_NaN",UINT64_C(0x7ff8000000000001),false},
        {"negative_quiet_NaN",UINT64_C(0xfff8000000000001),false},
        {"positive_signalling_NaN",UINT64_C(0x7ff0000000000001),false},
        {"negative_signalling_NaN",UINT64_C(0xfff0000000000001),false}
    };
    try {
        for(const Case& c:cases) {
            double value;std::memcpy(&value,&c.bits,8);
            const bool actual=finite64(value),library=std::isfinite(value);
            if(actual!=c.expected||actual!=library)throw std::runtime_error(c.name);
            double row[3]={0,value,1};
            if(finite(row,3)!=c.expected)throw std::runtime_error(std::string("array: ")+c.name);
            std::cout<<"FINITE64 "<<c.name<<" expected="<<c.expected<<" actual="<<actual<<" PASS\n";
        }
        std::cout<<"FINITE64 PASS cases=16 (signed zero, subnormal, normal, maximum finite, infinities, quiet/signalling NaNs).\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;}
}
