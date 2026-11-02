#include "controller_cases.hpp"
int main(){
    try {
        controller_test::validate_recorded_inputs();
        // Exactly three 64-point transactions: do not average malformed/failed
        // work into a throughput claim. All 192 points must independently pass.
        controller_test::synthetic_line();
        controller_test::recorded_prefix(0);
        controller_test::recorded_draw();
        std::cout<<"CONTROLLER_THROUGHPUT NUMERICAL PASS: 3 x 64 valid targets. Use each RTL transaction's cycle count; this is not board motion or a clock-closure result.\n";
        return 0;
    }catch(const std::exception&e){std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;}
}
