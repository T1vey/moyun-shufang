#ifndef Z20_IK_STEP_V2_H
#define Z20_IK_STEP_V2_H

// Full task-step ABI. The core is fixed to the nominal SO-101 five-joint
// geometry; the pen target and damping/scaling remain runtime inputs.
// status: 0=OK, 1=invalid input, 2=numeric failure.
#if defined(_WIN32) && defined(Z20_IK_EXPORT)
#define Z20_IK_API __declspec(dllexport)
#else
#define Z20_IK_API
#endif
extern "C" Z20_IK_API int z20_ik_step(
    const float q[5], const float target_position[3], const float target_axis[3],
    const float weights[6], const float scales[6], const float tool[3],
    const float tool_axis[3], const float limits[10], float mu, float max_step,
    int mode, float dq[5], float q_next[5], float error[6],
    float *position_error, float *tilt_error, unsigned int *abi_version);

#endif
