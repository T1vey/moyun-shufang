// Host-only adapter to run the same validation against the unchanged old top.
// Do not add this file to candidate HLS synthesis or co-simulation.
#include "../../tcb705/tcb_planner_accel.h"
extern "C" void tcb_planner_parallel(const uint64_t*c,const uint64_t*i,uint64_t*o,
    uint64_t*h,volatile uint64_t*x,uint32_t mode,uint32_t count,uint32_t capacity,
    uint32_t job,uint32_t generation) {
    tcb_planner_accel(c,i,o,h,x,mode,count,capacity,job,generation);
}
