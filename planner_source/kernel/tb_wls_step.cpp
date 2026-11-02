#include "wls_step.h"
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <string>
#include <stdexcept>

static double number(std::istream& input) {
    std::string token;
    if (!(input >> token)) throw std::runtime_error("truncated vectors");
    if (token == "nan") return std::numeric_limits<double>::quiet_NaN();
    if (token == "inf") return std::numeric_limits<double>::infinity();
    if (token == "-inf") return -std::numeric_limits<double>::infinity();
    size_t used = 0;
    double value = std::stod(token, &used);
    if (used != token.size()) throw std::runtime_error("invalid number");
    return value;
}

int main(int argc, char** argv) {
    try {
        std::ifstream input(argc > 1 ? argv[1] : "vectors.txt");
        if (!input) throw std::runtime_error("cannot open vectors.txt");
        std::ofstream output(argc > 2 ? argv[2] : "native_results.csv");
        if (!output) throw std::runtime_error("cannot open result file");
        output << "id,status,expected,passed,error_inf,allowed_error,backward_error\n" << std::setprecision(17);
        int count = 0;
        if (!(input >> count) || count <= 0) throw std::runtime_error("bad count");
        int failed = 0;
        double worst = 0, worst_backward = 0;
        for (int test = 0; test < count; ++test) {
            std::string id;
            int mode, expected;
            if (!(input >> id >> mode >> expected)) throw std::runtime_error("missing case header");
            float j[30], e[6], w[6], scales[6], dq[5];
            for (int k = 0; k < 30; ++k) j[k] = static_cast<float>(number(input));
            for (int k = 0; k < 6; ++k) e[k] = static_cast<float>(number(input));
            for (int k = 0; k < 6; ++k) w[k] = static_cast<float>(number(input));
            for (int k = 0; k < 6; ++k) scales[k] = static_cast<float>(number(input));
            float mu = static_cast<float>(number(input));
            double reference[5];
            for (int k = 0; k < 5; ++k) {
                reference[k] = number(input); dq[k] = 987.0f;
                if (!std::isfinite(reference[k])) throw std::runtime_error("non-finite reference");
            }
            double abs_tol = number(input), rel_tol = number(input), back_tol = number(input);
            if (!std::isfinite(abs_tol) || !std::isfinite(rel_tol) || !std::isfinite(back_tol) ||
                abs_tol <= 0 || rel_tol < 0 || back_tol <= 0 || expected < 0 || expected > 2)
                throw std::runtime_error("invalid tolerances or expected status");
            int status = z20_wls_step(j, e, w, scales, mu, mode, dq);
            bool pass = status == expected;
            double err = 0, magnitude = 0, norm_dq = 0, backward = 0;
            for (int k = 0; k < 5; ++k) {
                pass = pass && std::isfinite(dq[k]);
                double error = std::abs(static_cast<double>(dq[k]) - reference[k]);
                pass = pass && std::isfinite(error);
                err = std::max(err, error);
                magnitude = std::max(magnitude, std::abs(reference[k]));
                norm_dq = std::max(norm_dq, std::abs(static_cast<double>(dq[k])));
                if (expected != 0) pass = pass && dq[k] == 0.0f;
            }
            double allowed = abs_tol + rel_tol * magnitude;
            pass = pass && std::isfinite(allowed);
            if (expected == 0 && status == 0) {
                double norm_a = 0, norm_b = 0, residual = 0;
                for (int i = 0; i < 5; ++i) {
                    double b = 0, row_norm = 0, reconstructed = 0;
                    for (int r = 0; r < 6; ++r)
                        b += static_cast<double>(j[r*5+i]) * scales[r] * w[r] * e[r] * scales[r];
                    for (int k = 0; k < 5; ++k) {
                        double a = i == k ? mu : 0;
                        for (int r = 0; r < 6; ++r)
                            a += static_cast<double>(j[r*5+i]) * scales[r] * (mode == 0 ? w[r] : 1.0) * j[r*5+k] * scales[r];
                        row_norm += std::abs(a);
                        reconstructed += a * dq[k];
                    }
                    norm_a = std::max(norm_a, row_norm);
                    norm_b = std::max(norm_b, std::abs(b));
                    residual = std::max(residual, std::abs(reconstructed - b));
                }
                backward = residual / std::max(norm_a * norm_dq + norm_b, 1e-300);
                pass = pass && err <= allowed && backward <= back_tol && std::isfinite(backward);
                worst = std::max(worst, err);
                worst_backward = std::max(worst_backward, backward);
            }
            output << id << ',' << status << ',' << expected << ',' << pass << ',' << err << ',' << allowed << ',' << backward << '\n';
            if (!pass) { ++failed; std::cerr << "FAIL " << id << " status=" << status << " expected=" << expected << " err=" << err << " allowed=" << allowed << " backward=" << backward << '\n'; }
        }
        std::string extra;
        if (input >> extra) throw std::runtime_error("trailing vector data");
        output.close();
        if (!output) throw std::runtime_error("result write failed");
        std::cout << std::setprecision(10) << "WLS_VECTOR_GATE cases=" << count << " failed=" << failed
                  << " max_abs_error=" << worst << " max_backward=" << worst_backward << '\n';
        // Caller declares native/csim/cosim; the testbench does not infer it.
        return failed ? 1 : 0;
    } catch (const std::exception& e) {
        std::cerr << "HARNESS_ERROR " << e.what() << '\n';
        return 2;
    }
}
