#include "wls_step.h"
#include <cmath>
#include <cfloat>

static bool finite_value(float x) {
    return x <= FLT_MAX && x >= -FLT_MAX;
}

extern "C" int z20_wls_step(const float j[30], const float e[6],
    const float w[6], const float scales[6], float mu, int mode, float dq[5]) {
#pragma HLS INTERFACE s_axilite port=j bundle=control
#pragma HLS INTERFACE s_axilite port=e bundle=control
#pragma HLS INTERFACE s_axilite port=w bundle=control
#pragma HLS INTERFACE s_axilite port=scales bundle=control
#pragma HLS INTERFACE s_axilite port=mu bundle=control
#pragma HLS INTERFACE s_axilite port=mode bundle=control
#pragma HLS INTERFACE s_axilite port=dq bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    // A simple serial reference architecture first. No target II is claimed.
    for (int i = 0; i < 5; ++i) dq[i] = 0.0f;
    if (!finite_value(mu) || mu <= 0.0f || (mode != 0 && mode != 1)) return 1;
    for (int r = 0; r < 6; ++r) {
        if (!finite_value(e[r]) || !finite_value(w[r]) || w[r] < 0.0f ||
            !finite_value(scales[r]) || scales[r] <= 0.0f) return 1;
        for (int c = 0; c < 5; ++c) if (!finite_value(j[r*5+c])) return 1;
    }
    // ABI remains float32. Assemble A/b in double to preserve cancellation
    // before rounding once to the float32 Cholesky core. Resource cost UNMEASURED.
    double js[6][5], es[6];
    for (int r = 0; r < 6; ++r) {
        es[r] = static_cast<double>(e[r]) * scales[r];
        for (int c = 0; c < 5; ++c) {
            js[r][c] = static_cast<double>(j[r*5+c]) * scales[r];
        }
    }
    float a[5][5], b[5];
    for (int i = 0; i < 5; ++i) {
        double rhs = 0.0;
        for (int r = 0; r < 6; ++r) rhs += js[r][i] * (w[r] * es[r]);
        if (!(rhs <= FLT_MAX && rhs >= -FLT_MAX)) return 2;
        b[i] = static_cast<float>(rhs);
        for (int k = 0; k <= i; ++k) {
            double acc = 0.0;
            for (int r = 0; r < 6; ++r)
                acc += js[r][i] * ((mode == 0 ? w[r] : 1.0f) * js[r][k]);
            if (i == k) acc += mu;
            if (!(acc <= FLT_MAX && acc >= -FLT_MAX)) return 2;
            a[i][k] = static_cast<float>(acc);
            a[k][i] = a[i][k];
        }
    }
    float lower[5][5] = {};
    for (int i = 0; i < 5; ++i) {
        for (int k = 0; k <= i; ++k) {
            float pivot = a[i][k];
            for (int t = 0; t < k; ++t) pivot -= lower[i][t] * lower[k][t];
            if (!finite_value(pivot)) return 2;
            if (i == k) {
                if (pivot <= 0.0f) return 2;
                lower[i][k] = std::sqrt(pivot);
            } else {
                lower[i][k] = pivot / lower[k][k];
            }
            if (!finite_value(lower[i][k])) return 2;
        }
    }
    float y[5], result[5];
    for (int i = 0; i < 5; ++i) {
        float v = b[i];
        for (int k = 0; k < i; ++k) v -= lower[i][k] * y[k];
        y[i] = v / lower[i][i];
        if (!finite_value(y[i])) return 2;
    }
    for (int ii = 0; ii < 5; ++ii) {
        int i = 4 - ii;
        float v = y[i];
        for (int k = i+1; k < 5; ++k) v -= lower[k][i] * result[k];
        result[i] = v / lower[i][i];
        if (!finite_value(result[i])) return 2;
    }
    for (int i = 0; i < 5; ++i) dq[i] = result[i];
    return 0;
}
