#include "controller_cases.hpp"
int main(){
    try {
        controller_test::validate_recorded_inputs();
        controller_test::synthetic_line();
        controller_test::recorded_prefix(0);
        controller_test::recorded_prefix(64);
        controller_test::recorded_prefix(128);
        controller_test::recorded_draw();
        controller_test::synthetic_corner();
        std::cout<<"CONTROLLER_DH OFFLINE PASS: 352 targets; historical controller model, recorded plan nodes, and synthetic paths. No robot motion.\n";
        return 0;
    }catch(const std::exception&e){std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;}
}
