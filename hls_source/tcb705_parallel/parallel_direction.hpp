#pragma once
#include <cmath>

// Keep BRAM bank selection outside this floating-point pipeline. In the R2
// schedule a RAM load, its bank mux and the first adder stage occupied one
// clock path; a distinct pipelined function provides a scheduling boundary.
// UG1399 2024.2 permits dadd/fulldsp latency 0..15; eight is selected here.
static double parallel_add_diagonal(double old_diagonal, double damping) {
#pragma HLS INLINE off
#pragma HLS PIPELINE II=1
    double sum;
#pragma HLS BIND_OP variable=sum op=dadd impl=fulldsp latency=8
    sum = old_diagonal + damping;
    return sum;
}

// Seven-axis damped least-squares direction. The equation is unchanged:
// (J^T W J + (damping^2 + reference_weight) I) dq
//     = J^T W e + reference_weight * (reference - q).
// FP64 is intentional: the seventh (redundant) direction can have a diagonal
// regularizer around 1e-8, below useful FP32 resolution of the normal matrix.
// A two-lane lower-triangle engine and column-wise LDL^T replace serial dot
// products and seven square roots. Only the seven pivots remain dependent.
static bool parallel_direction7(double j[6][7], const double *e,
    const double *q, const double *reference, const double *o, double *dq) {
#pragma HLS INLINE off
#pragma HLS ALLOCATION operation instances=dmul limit=4
#pragma HLS ALLOCATION operation instances=dadd limit=2
#pragma HLS ALLOCATION operation instances=dsub limit=2
#pragma HLS ALLOCATION operation instances=ddiv limit=1
    static const unsigned char row_of[28] = {
        0,1,1,2,2,2,3,3,3,3,4,4,4,4,4,5,5,5,5,5,5,6,6,6,6,6,6,6};
    static const unsigned char col_of[28] = {
        0,0,1,0,1,2,0,1,2,3,0,1,2,3,4,0,1,2,3,4,5,0,1,2,3,4,5,6};
#pragma HLS ARRAY_PARTITION variable=row_of complete
#pragma HLS ARRAY_PARTITION variable=col_of complete
    double a[28], lower[28], weighted[6][7], rhs[7], inv[7], column[7], factor[7], solution[7];
#pragma HLS ARRAY_PARTITION variable=a cyclic factor=2 dim=1
#pragma HLS BIND_STORAGE variable=a type=ram_2p impl=bram latency=1
#pragma HLS BIND_STORAGE variable=lower type=ram_2p impl=lutram latency=1
#pragma HLS ARRAY_PARTITION variable=weighted complete dim=2
#pragma HLS ARRAY_PARTITION variable=rhs complete
#pragma HLS ARRAY_PARTITION variable=inv complete
#pragma HLS ARRAY_PARTITION variable=column complete
#pragma HLS ARRAY_PARTITION variable=factor complete
#pragma HLS ARRAY_PARTITION variable=solution complete
    const double weight2 = o[4] * o[4];
    const double damping = o[5] * o[5] + o[6];
    if (!(damping > 0.0) || !std::isfinite(damping)) return false;
    for (int n = 0; n < 28; ++n) {
#pragma HLS PIPELINE II=1
        a[n] = 0.0;
        lower[n] = 0.0;
    }
    for (int i = 0; i < 7; ++i) {
#pragma HLS UNROLL
        rhs[i] = 0.0;
    }
    // Each pipeline visits an accumulator once. Its next dependent update is
    // in the following outer iteration, after this pipeline has drained.
    for (int r = 0; r < 6; ++r) {
        for (int i = 0; i < 7; ++i) {
#pragma HLS PIPELINE II=1
            const double v = r < 3 ? j[r][i] : j[r][i] * weight2;
            weighted[r][i] = v;
            rhs[i] += v * e[r];
        }
    }
    // Two different entries advance each iteration. No false-dependence
    // directive is used: the next dimension retains the actual recurrence.
    for (int r = 0; r < 6; ++r) {
        for (int first = 0; first < 28; first += 2) {
#pragma HLS PIPELINE II=1
            for (int lane = 0; lane < 2; ++lane) {
#pragma HLS UNROLL
                const int n = first + lane;
                a[n] += weighted[r][row_of[n]] * j[r][col_of[n]];
            }
        }
    }
    for (int i = 0; i < 7; ++i) {
#pragma HLS PIPELINE II=1
        rhs[i] += o[6] * (reference[i] - q[i]);
        const int diagonal_index = i * (i + 1) / 2 + i;
        const double old_diagonal = a[diagonal_index];
        const double damped_diagonal = parallel_add_diagonal(old_diagonal, damping);
        a[diagonal_index] = damped_diagonal;
    }

    // In-place symmetric rank-one elimination: A = L D L^T, diag(L) = 1.
    // The positive pivot test preserves the original SPD/finite failure gate.
    for (int k = 0; k < 7; ++k) {
        const double pivot = a[k * (k + 1) / 2 + k];
        if (!(pivot > 0.0) || !std::isfinite(pivot)) return false;
        const double reciprocal = 1.0 / pivot;
        if (!std::isfinite(reciprocal)) return false;
        inv[k] = reciprocal;
        for (int i = 0; i < 7; ++i) {
#pragma HLS PIPELINE II=1
            const double v = i > k ? a[i * (i + 1) / 2 + k] : 0.0;
            column[i] = v;
            factor[i] = v * reciprocal;
            if (i > k) lower[i * (i + 1) / 2 + k] = factor[i];
        }
        for (int first = 0; first < 28; first += 2) {
#pragma HLS PIPELINE II=1
            for (int lane = 0; lane < 2; ++lane) {
#pragma HLS UNROLL
                const int n = first + lane, i = row_of[n], c = col_of[n];
                if (c > k) a[n] -= factor[i] * column[c];
            }
        }
    }

    // Forward and backward substitution update independent vector elements
    // in parallel pairs instead of accumulating a dependent short dot product.
    for (int k = 0; k < 7; ++k) {
        const double value = rhs[k];
        for (int first = 0; first < 8; first += 2) {
#pragma HLS PIPELINE II=1
            for (int lane = 0; lane < 2; ++lane) {
#pragma HLS UNROLL
                const int i = first + lane;
                if (i < 7 && i > k) rhs[i] -= lower[i * (i + 1) / 2 + k] * value;
            }
        }
    }
    for (int i = 0; i < 7; ++i) {
#pragma HLS PIPELINE II=1
        solution[i] = rhs[i] * inv[i];
    }
    for (int reverse = 0; reverse < 7; ++reverse) {
        const int k = 6 - reverse;
        const double value = solution[k];
        for (int first = 0; first < 8; first += 2) {
#pragma HLS PIPELINE II=1
            for (int lane = 0; lane < 2; ++lane) {
#pragma HLS UNROLL
                const int i = first + lane;
                if (i < k) solution[i] -= lower[k * (k + 1) / 2 + i] * value;
            }
        }
    }
    for (int i = 0; i < 7; ++i) {
#pragma HLS PIPELINE II=1
        if (!std::isfinite(solution[i])) return false;
        dq[i] = solution[i];
    }
    return true;
}
