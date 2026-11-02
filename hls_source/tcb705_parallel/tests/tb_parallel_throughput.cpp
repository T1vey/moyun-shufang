#include "parallel_test_support.hpp"
int main() {
    try {
        parallel_test::Fixture f;
        // Single measured HLS transaction: 64 distinct targets, each 0.5 mm away.
        parallel_test::run_chain("throughput_line64_0p5mm",f,parallel_test::line64(f),true);
        std::cout<<"NUMERICAL PASS. Derive throughput from RTL transaction cycles, not this C simulation wall time.\n";
        std::cout<<"At 100 MHz, >100000 valid points/s requires this 64-point transaction <64000 cycles (including AXI/config/result).\n";
        return 0;
    } catch(const std::exception& e) {std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;}
}
