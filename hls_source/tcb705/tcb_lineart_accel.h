#pragma once
#include <ap_int.h>
#define LINEART_MAX_DIM 1536
#define LINEART_STAGES 8
#define LINEART_ID 0x4c410108u
unsigned tcb_lineart_accel(const ap_uint<64>* src, ap_uint<64>* dst,
                          unsigned width, unsigned height,
                          unsigned &deleted, unsigned &identity);
