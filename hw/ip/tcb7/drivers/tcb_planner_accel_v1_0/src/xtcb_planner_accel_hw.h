// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
// control
// 0x00 : Control signals
//        bit 0  - ap_start (Read/Write/COH)
//        bit 1  - ap_done (Read/COR)
//        bit 2  - ap_idle (Read)
//        bit 3  - ap_ready (Read/COR)
//        bit 7  - auto_restart (Read/Write)
//        bit 9  - interrupt (Read)
//        others - reserved
// 0x04 : Global Interrupt Enable Register
//        bit 0  - Global Interrupt Enable (Read/Write)
//        others - reserved
// 0x08 : IP Interrupt Enable Register (Read/Write)
//        bit 0 - enable ap_done interrupt (Read/Write)
//        bit 1 - enable ap_ready interrupt (Read/Write)
//        others - reserved
// 0x0c : IP Interrupt Status Register (Read/TOW)
//        bit 0 - ap_done (Read/TOW)
//        bit 1 - ap_ready (Read/TOW)
//        others - reserved
// 0x10 : Data signal of config_words
//        bit 31~0 - config_words[31:0] (Read/Write)
// 0x14 : Data signal of config_words
//        bit 31~0 - config_words[63:32] (Read/Write)
// 0x18 : reserved
// 0x1c : Data signal of input_words
//        bit 31~0 - input_words[31:0] (Read/Write)
// 0x20 : Data signal of input_words
//        bit 31~0 - input_words[63:32] (Read/Write)
// 0x24 : reserved
// 0x28 : Data signal of output_words
//        bit 31~0 - output_words[31:0] (Read/Write)
// 0x2c : Data signal of output_words
//        bit 31~0 - output_words[63:32] (Read/Write)
// 0x30 : reserved
// 0x34 : Data signal of result_words
//        bit 31~0 - result_words[31:0] (Read/Write)
// 0x38 : Data signal of result_words
//        bit 31~0 - result_words[63:32] (Read/Write)
// 0x3c : reserved
// 0x40 : Data signal of cancel_words
//        bit 31~0 - cancel_words[31:0] (Read/Write)
// 0x44 : Data signal of cancel_words
//        bit 31~0 - cancel_words[63:32] (Read/Write)
// 0x48 : reserved
// 0x4c : Data signal of mode
//        bit 31~0 - mode[31:0] (Read/Write)
// 0x50 : reserved
// 0x54 : Data signal of count
//        bit 31~0 - count[31:0] (Read/Write)
// 0x58 : reserved
// 0x5c : Data signal of output_capacity
//        bit 31~0 - output_capacity[31:0] (Read/Write)
// 0x60 : reserved
// 0x64 : Data signal of job_id
//        bit 31~0 - job_id[31:0] (Read/Write)
// 0x68 : reserved
// 0x6c : Data signal of generation
//        bit 31~0 - generation[31:0] (Read/Write)
// 0x70 : reserved
// (SC = Self Clear, COR = Clear on Read, TOW = Toggle on Write, COH = Clear on Handshake)

#define XTCB_PLANNER_ACCEL_CONTROL_ADDR_AP_CTRL              0x00
#define XTCB_PLANNER_ACCEL_CONTROL_ADDR_GIE                  0x04
#define XTCB_PLANNER_ACCEL_CONTROL_ADDR_IER                  0x08
#define XTCB_PLANNER_ACCEL_CONTROL_ADDR_ISR                  0x0c
#define XTCB_PLANNER_ACCEL_CONTROL_ADDR_CONFIG_WORDS_DATA    0x10
#define XTCB_PLANNER_ACCEL_CONTROL_BITS_CONFIG_WORDS_DATA    64
#define XTCB_PLANNER_ACCEL_CONTROL_ADDR_INPUT_WORDS_DATA     0x1c
#define XTCB_PLANNER_ACCEL_CONTROL_BITS_INPUT_WORDS_DATA     64
#define XTCB_PLANNER_ACCEL_CONTROL_ADDR_OUTPUT_WORDS_DATA    0x28
#define XTCB_PLANNER_ACCEL_CONTROL_BITS_OUTPUT_WORDS_DATA    64
#define XTCB_PLANNER_ACCEL_CONTROL_ADDR_RESULT_WORDS_DATA    0x34
#define XTCB_PLANNER_ACCEL_CONTROL_BITS_RESULT_WORDS_DATA    64
#define XTCB_PLANNER_ACCEL_CONTROL_ADDR_CANCEL_WORDS_DATA    0x40
#define XTCB_PLANNER_ACCEL_CONTROL_BITS_CANCEL_WORDS_DATA    64
#define XTCB_PLANNER_ACCEL_CONTROL_ADDR_MODE_DATA            0x4c
#define XTCB_PLANNER_ACCEL_CONTROL_BITS_MODE_DATA            32
#define XTCB_PLANNER_ACCEL_CONTROL_ADDR_COUNT_DATA           0x54
#define XTCB_PLANNER_ACCEL_CONTROL_BITS_COUNT_DATA           32
#define XTCB_PLANNER_ACCEL_CONTROL_ADDR_OUTPUT_CAPACITY_DATA 0x5c
#define XTCB_PLANNER_ACCEL_CONTROL_BITS_OUTPUT_CAPACITY_DATA 32
#define XTCB_PLANNER_ACCEL_CONTROL_ADDR_JOB_ID_DATA          0x64
#define XTCB_PLANNER_ACCEL_CONTROL_BITS_JOB_ID_DATA          32
#define XTCB_PLANNER_ACCEL_CONTROL_ADDR_GENERATION_DATA      0x6c
#define XTCB_PLANNER_ACCEL_CONTROL_BITS_GENERATION_DATA      32

