#pragma once
#include <stdint.h>
// Port of 1013 planner_accel_v2. New identity prevents five/seven-axis confusion.
namespace tcb_pl {
const uint32_t ABI=0x54430701u, MODEL=0x37475231u, NONE=0xffffffffu;
enum { IK_CHAIN=1, FK_ROWS=2, OK=0, PARTIAL=1, CANCELLED=2,
       BAD_ABI=3, BAD_MODEL=4, BAD_INPUT=5 };
const unsigned CONTEXT_WORDS=256, MAX_IK=64, MAX_FK=1024;
}
extern "C" void tcb_planner_accel(const uint64_t* config_words,
    const uint64_t* input_words,uint64_t* output_words,uint64_t* result_words,
    volatile uint64_t* cancel_words,uint32_t mode,uint32_t count,
    uint32_t output_capacity,uint32_t job_id,uint32_t generation);
