#ifndef Z20_WLS_STEP_V1_H
#define Z20_WLS_STEP_V1_H

// ABI v1. Row-major J[6][5], W (not sqrt W), positive S and mu (not mu^2).
// mode=0: WLS. mode=1: RHS-only weighting for paired ablation, not production.
// status 0=OK, 1=INVALID_INPUT, 2=NUMERIC. On failure dq is entirely zero.
// These are radians increments, NOT motor positions and NOT motion commands.
#if defined(_WIN32) && defined(Z20_WLS_EXPORT)
#define Z20_API __declspec(dllexport)
#else
#define Z20_API
#endif
extern "C" Z20_API int z20_wls_step(const float j[30], const float e[6],
    const float w[6], const float scales[6], float mu, int mode, float dq[5]);

#endif
