#pragma once
#include "controller_test_support.hpp"
namespace controller_test {
inline void validate_recorded_inputs() {
    Fixture f;double worst_position=0,worst_angle=0;
    for(unsigned group=0;group<2;group++)for(unsigned row=0;row<(group?controller_dh_fixture::DRAW_COUNT:controller_dh_fixture::PREFIX_COUNT);row++) {
        const double* source_q=group?controller_dh_fixture::DRAW_Q[row]:controller_dh_fixture::PREFIX_Q[row];
        const double* source_p=group?controller_dh_fixture::DRAW_POSITION[row]:controller_dh_fixture::PREFIX_POSITION[row];
        Joints q;for(int k=0;k<7;k++)q[k]=source_q[k];
        const Pose pose=fk(f,q);const Point p={{source_p[0],source_p[1],source_p[2]}};
        worst_position=std::max(worst_position,position_error(pose,p));
        worst_angle=std::max(worst_angle,angle_error(pose,f.rotation));
    }
    require(worst_position<=f.options[0]&&worst_angle<=f.options[1],"recorded controller fixture does not meet original FK tolerance");
    std::cout<<std::setprecision(12)<<"CONTROLLER_FIXTURE machine_sha="<<controller_dh_fixture::MACHINE_SHA256
        <<" nodes_sha="<<controller_dh_fixture::NODES_SHA256<<" recorded_max_position_m="<<worst_position
        <<" recorded_max_angle_rad="<<worst_angle<<" physical_motion=false\n";
}
inline ChainSummary recorded_prefix(unsigned start) {
    require(start+64<controller_dh_fixture::PREFIX_COUNT,"prefix fixture bounds");Fixture f;
    for(int k=0;k<7;k++)f.seed[k]=controller_dh_fixture::PREFIX_Q[start][k];
    std::vector<Point> p;for(unsigned i=start+1;i<=start+64;i++)p.push_back(Point{{controller_dh_fixture::PREFIX_POSITION[i][0],controller_dh_fixture::PREFIX_POSITION[i][1],controller_dh_fixture::PREFIX_POSITION[i][2]}});
    return run_chain("controller_recorded_prefix_"+std::to_string(start+1)+"_"+std::to_string(start+64),f,p,true);
}
inline ChainSummary recorded_draw() {
    Fixture f;for(int k=0;k<7;k++)f.seed[k]=controller_dh_fixture::DRAW_Q[0][k];
    std::vector<Point> p;for(unsigned i=1;i<controller_dh_fixture::DRAW_COUNT;i++)p.push_back(Point{{controller_dh_fixture::DRAW_POSITION[i][0],controller_dh_fixture::DRAW_POSITION[i][1],controller_dh_fixture::DRAW_POSITION[i][2]}});
    return run_chain("controller_recorded_DRAW_"+std::to_string(controller_dh_fixture::DRAW_START+1)+"_64targets",f,p,true);
}
inline ChainSummary synthetic_line() {
    Fixture f;return run_chain("controller_model_synthetic_line64_0p5mm",f,line64(f),true);
}
inline ChainSummary synthetic_corner() {
    Fixture f;Point o=origin(f);std::vector<Point>p;
    for(int i=1;i<=16;i++)p.push_back(Point{{o[0]+.0005*i,o[1],o[2]}});
    for(int i=1;i<=16;i++)p.push_back(Point{{o[0]+.008,o[1]+.0005*i,o[2]}});
    return run_chain("controller_model_synthetic_corner90",f,p,true);
}
}
