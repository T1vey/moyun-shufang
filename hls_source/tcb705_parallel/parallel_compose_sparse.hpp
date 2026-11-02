#pragma once
#include <cmath>

// Exact sparse-shape fast path for the controller-DH link transforms.
// No link length, tool length, or paper calibration is hard-coded here.
// The caller must retain the general compose path when this predicate is false.
static bool parallel_compose_is_rx_z(const double b[12]) {
#pragma HLS INLINE
#pragma HLS ARRAY_PARTITION variable=b complete
    if (b[0] != 1.0 || b[1] != 0.0 || b[2] != 0.0 || b[3] != 0.0 ||
        b[4] != 0.0 || b[7] != 0.0 || b[8] != 0.0 || b[5] != b[10] ||
        b[6] != -b[9] || !std::isfinite(b[11])) return false;
    const double cosine = b[5], sine = b[9];
    const bool identity_rotation = cosine == 1.0 && sine == 0.0;
    // Keep the supplied cosine (normally 6.123233995736766e-17) in the
    // arithmetic. The tolerance classifies a right angle; it never rounds it.
    const bool right_angle_rotation = (sine == 1.0 || sine == -1.0) &&
        std::isfinite(cosine) && std::abs(cosine) <= 1e-12;
    return identity_rotation || right_angle_rotation;
}

// Precondition: parallel_compose_is_rx_z(b). Like general compose, arrays may
// not alias. Three rows share a small pipeline; no seven-link core replication.
static void parallel_compose_rx_z(const double a[12], const double b[12], double c[12]) {
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=a complete
#pragma HLS ARRAY_PARTITION variable=b complete
#pragma HLS ARRAY_PARTITION variable=c complete
#pragma HLS ALLOCATION operation instances=dmul limit=2
#pragma HLS ALLOCATION operation instances=dadd limit=2
#pragma HLS ALLOCATION operation instances=dsub limit=1
    const double cosine = b[5], sine = b[9], distance = b[11];
    const bool identity_rotation = sine == 0.0;
    SPARSE_ROWS: for (int row = 0; row < 3; ++row) {
#pragma HLS PIPELINE II=1
        const double x = a[row*4], y = a[row*4+1], z = a[row*4+2];
        c[row*4] = x;
        if (identity_rotation) {
            c[row*4+1] = y;
            c[row*4+2] = z;
        } else {
            const double signed_z = sine > 0.0 ? z : -z;
            const double negative_signed_y = sine > 0.0 ? -y : y;
            // Same two nonzero product sums as the dense 3x4 multiplication.
            c[row*4+1] = y * cosine + signed_z;
            c[row*4+2] = negative_signed_y + z * cosine;
        }
        c[row*4+3] = z * distance + a[row*4+3];
    }
}
