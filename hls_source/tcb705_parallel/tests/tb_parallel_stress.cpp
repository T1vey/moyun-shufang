// Extended host-only numerical sweep. The shorter tb_parallel.cpp is intended
// for routine HLS C/RTL simulation; this one covers many more seed poses.
#include "parallel_test_support.hpp"
using namespace parallel_test;
int main() {
    try {
        uint32_t rng=0x7458705;unsigned requested=0,verified=0,old_verified=0,fallback_batches=0;
        double max_position=0,max_angle=0,max_jump=0,max_delta_old=0;
        for(unsigned batch=0;batch<128;batch++) {
            Fixture f;
            for(int k=0;k<7;k++) {
                rng=rng*1664525u+1013904223u;const double u=double(rng)/4294967295.;
                // Stay 15% away from each joint limit, retaining broad geometric
                // coverage and several near-singular configurations.
                f.seed[k]=f.model[21*k+19]+(.15+.70*u)*(f.model[21*k+20]-f.model[21*k+19]);
            }
            const Pose start=fk(f,f.seed);
            for(int r=0;r<3;r++)for(int c=0;c<3;c++)f.rotation[3*r+c]=start[4*r+c];
            std::vector<Point> points;const unsigned axis=batch%3;const double sign=(batch&4)?-1:1;
            for(unsigned row=1;row<=8;row++) {
                Point p={{start[3],start[7],start[11]}};
                p[axis]+=sign*.0002*row;
                if(batch&8)p[(axis+1)%3]+=.0001*std::sin(row*.4);
                points.push_back(p);
            }
            const ChainSummary s=run_chain("random_pose_"+std::to_string(batch),f,points);
            requested+=s.requested;verified+=s.verified_ok;old_verified+=s.legacy_ok;
            fallback_batches+=s.verified_ok<s.requested;
            max_position=std::max(max_position,s.max_position);max_angle=std::max(max_angle,s.max_angle);
            max_jump=std::max(max_jump,s.max_joint_step);max_delta_old=std::max(max_delta_old,s.max_delta_old);
        }
        std::cout<<std::setprecision(12)<<"STRESS PASS batches=128 requested="<<requested<<" verified="<<verified
            <<" old_verified="<<old_verified<<" fallback_batches="<<fallback_batches
            <<" max_position_m="<<max_position<<" max_angle_rad="<<max_angle
            <<" max_joint_step_rad="<<max_jump<<" max_delta_old_rad="<<max_delta_old<<'\n';
        return 0;
    }catch(const std::exception& e){std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;}
}
