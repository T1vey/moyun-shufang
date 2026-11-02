#ifndef SO101_IK_TARGET_H
#define SO101_IK_TARGET_H
#include "ik_step.h"
// ABI 0x534f0301: one bounded target solve per AXI-Lite start.
// 0 OK, 1 INVALID_INPUT, 2 NUMERIC, 3 MAX_ITER, 4 STAGNATION, 5 LIMIT_STALL.
extern "C" Z20_IK_API int z20_ik_target(
    const float q_init[5], const float target_position[3], const float target_axis[3],
    const float weights[6], const float scales[6], const float tool[3],
    const float tool_axis[3], const float limits[10], float mu, float max_step,
    float position_tolerance, float tilt_tolerance, float stagnation_cost_change,
    int max_iterations, int line_search_trials, int stagnation_window, int mode,
    float q_result[5], float *position_error, float *tilt_error,
    int *iterations_used, int *evaluations_used, unsigned int *abi_version);
#endif
