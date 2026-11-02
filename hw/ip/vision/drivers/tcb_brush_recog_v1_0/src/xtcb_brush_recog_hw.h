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
// 0x10 : Data signal of ap_return
//        bit 31~0 - ap_return[31:0] (Read)
// 0x18 : Data signal of mode
//        bit 31~0 - mode[31:0] (Read/Write)
// 0x1c : reserved
// 0x20 : Data signal of params
//        bit 31~0 - params[31:0] (Read/Write)
// 0x24 : Data signal of params
//        bit 31~0 - params[63:32] (Read/Write)
// 0x28 : reserved
// 0x2c : Data signal of src
//        bit 31~0 - src[31:0] (Read/Write)
// 0x30 : Data signal of src
//        bit 31~0 - src[63:32] (Read/Write)
// 0x34 : reserved
// 0x38 : Data signal of dst
//        bit 31~0 - dst[31:0] (Read/Write)
// 0x3c : Data signal of dst
//        bit 31~0 - dst[63:32] (Read/Write)
// 0x40 : reserved
// 0x44 : Data signal of tpl
//        bit 31~0 - tpl[31:0] (Read/Write)
// 0x48 : Data signal of tpl
//        bit 31~0 - tpl[63:32] (Read/Write)
// 0x4c : reserved
// 0x50 : Data signal of identity
//        bit 31~0 - identity[31:0] (Read)
// 0x54 : Control signal of identity
//        bit 0  - identity_ap_vld (Read/COR)
//        others - reserved
// (SC = Self Clear, COR = Clear on Read, TOW = Toggle on Write, COH = Clear on Handshake)

#define XTCB_BRUSH_RECOG_CONTROL_ADDR_AP_CTRL       0x00
#define XTCB_BRUSH_RECOG_CONTROL_ADDR_GIE           0x04
#define XTCB_BRUSH_RECOG_CONTROL_ADDR_IER           0x08
#define XTCB_BRUSH_RECOG_CONTROL_ADDR_ISR           0x0c
#define XTCB_BRUSH_RECOG_CONTROL_ADDR_AP_RETURN     0x10
#define XTCB_BRUSH_RECOG_CONTROL_BITS_AP_RETURN     32
#define XTCB_BRUSH_RECOG_CONTROL_ADDR_MODE_DATA     0x18
#define XTCB_BRUSH_RECOG_CONTROL_BITS_MODE_DATA     32
#define XTCB_BRUSH_RECOG_CONTROL_ADDR_PARAMS_DATA   0x20
#define XTCB_BRUSH_RECOG_CONTROL_BITS_PARAMS_DATA   64
#define XTCB_BRUSH_RECOG_CONTROL_ADDR_SRC_DATA      0x2c
#define XTCB_BRUSH_RECOG_CONTROL_BITS_SRC_DATA      64
#define XTCB_BRUSH_RECOG_CONTROL_ADDR_DST_DATA      0x38
#define XTCB_BRUSH_RECOG_CONTROL_BITS_DST_DATA      64
#define XTCB_BRUSH_RECOG_CONTROL_ADDR_TPL_DATA      0x44
#define XTCB_BRUSH_RECOG_CONTROL_BITS_TPL_DATA      64
#define XTCB_BRUSH_RECOG_CONTROL_ADDR_IDENTITY_DATA 0x50
#define XTCB_BRUSH_RECOG_CONTROL_BITS_IDENTITY_DATA 32
#define XTCB_BRUSH_RECOG_CONTROL_ADDR_IDENTITY_CTRL 0x54

