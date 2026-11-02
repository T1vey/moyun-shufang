// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
/***************************** Include Files *********************************/
#include "xtcb_planner_accel.h"

/************************** Function Implementation *************************/
#ifndef __linux__
int XTcb_planner_accel_CfgInitialize(XTcb_planner_accel *InstancePtr, XTcb_planner_accel_Config *ConfigPtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(ConfigPtr != NULL);

    InstancePtr->Control_BaseAddress = ConfigPtr->Control_BaseAddress;
    InstancePtr->IsReady = XIL_COMPONENT_IS_READY;

    return XST_SUCCESS;
}
#endif

void XTcb_planner_accel_Start(XTcb_planner_accel *InstancePtr) {
    u32 Data;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_AP_CTRL) & 0x80;
    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_AP_CTRL, Data | 0x01);
}

u32 XTcb_planner_accel_IsDone(XTcb_planner_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_AP_CTRL);
    return (Data >> 1) & 0x1;
}

u32 XTcb_planner_accel_IsIdle(XTcb_planner_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_AP_CTRL);
    return (Data >> 2) & 0x1;
}

u32 XTcb_planner_accel_IsReady(XTcb_planner_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_AP_CTRL);
    // check ap_start to see if the pcore is ready for next input
    return !(Data & 0x1);
}

void XTcb_planner_accel_EnableAutoRestart(XTcb_planner_accel *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_AP_CTRL, 0x80);
}

void XTcb_planner_accel_DisableAutoRestart(XTcb_planner_accel *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_AP_CTRL, 0);
}

void XTcb_planner_accel_Set_config_words(XTcb_planner_accel *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_CONFIG_WORDS_DATA, (u32)(Data));
    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_CONFIG_WORDS_DATA + 4, (u32)(Data >> 32));
}

u64 XTcb_planner_accel_Get_config_words(XTcb_planner_accel *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_CONFIG_WORDS_DATA);
    Data += (u64)XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_CONFIG_WORDS_DATA + 4) << 32;
    return Data;
}

void XTcb_planner_accel_Set_input_words(XTcb_planner_accel *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_INPUT_WORDS_DATA, (u32)(Data));
    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_INPUT_WORDS_DATA + 4, (u32)(Data >> 32));
}

u64 XTcb_planner_accel_Get_input_words(XTcb_planner_accel *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_INPUT_WORDS_DATA);
    Data += (u64)XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_INPUT_WORDS_DATA + 4) << 32;
    return Data;
}

void XTcb_planner_accel_Set_output_words(XTcb_planner_accel *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_OUTPUT_WORDS_DATA, (u32)(Data));
    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_OUTPUT_WORDS_DATA + 4, (u32)(Data >> 32));
}

u64 XTcb_planner_accel_Get_output_words(XTcb_planner_accel *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_OUTPUT_WORDS_DATA);
    Data += (u64)XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_OUTPUT_WORDS_DATA + 4) << 32;
    return Data;
}

void XTcb_planner_accel_Set_result_words(XTcb_planner_accel *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_RESULT_WORDS_DATA, (u32)(Data));
    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_RESULT_WORDS_DATA + 4, (u32)(Data >> 32));
}

u64 XTcb_planner_accel_Get_result_words(XTcb_planner_accel *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_RESULT_WORDS_DATA);
    Data += (u64)XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_RESULT_WORDS_DATA + 4) << 32;
    return Data;
}

void XTcb_planner_accel_Set_cancel_words(XTcb_planner_accel *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_CANCEL_WORDS_DATA, (u32)(Data));
    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_CANCEL_WORDS_DATA + 4, (u32)(Data >> 32));
}

u64 XTcb_planner_accel_Get_cancel_words(XTcb_planner_accel *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_CANCEL_WORDS_DATA);
    Data += (u64)XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_CANCEL_WORDS_DATA + 4) << 32;
    return Data;
}

void XTcb_planner_accel_Set_mode(XTcb_planner_accel *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_MODE_DATA, Data);
}

u32 XTcb_planner_accel_Get_mode(XTcb_planner_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_MODE_DATA);
    return Data;
}

void XTcb_planner_accel_Set_count(XTcb_planner_accel *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_COUNT_DATA, Data);
}

u32 XTcb_planner_accel_Get_count(XTcb_planner_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_COUNT_DATA);
    return Data;
}

void XTcb_planner_accel_Set_output_capacity(XTcb_planner_accel *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_OUTPUT_CAPACITY_DATA, Data);
}

u32 XTcb_planner_accel_Get_output_capacity(XTcb_planner_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_OUTPUT_CAPACITY_DATA);
    return Data;
}

void XTcb_planner_accel_Set_job_id(XTcb_planner_accel *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_JOB_ID_DATA, Data);
}

u32 XTcb_planner_accel_Get_job_id(XTcb_planner_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_JOB_ID_DATA);
    return Data;
}

void XTcb_planner_accel_Set_generation(XTcb_planner_accel *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_GENERATION_DATA, Data);
}

u32 XTcb_planner_accel_Get_generation(XTcb_planner_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_GENERATION_DATA);
    return Data;
}

void XTcb_planner_accel_InterruptGlobalEnable(XTcb_planner_accel *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_GIE, 1);
}

void XTcb_planner_accel_InterruptGlobalDisable(XTcb_planner_accel *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_GIE, 0);
}

void XTcb_planner_accel_InterruptEnable(XTcb_planner_accel *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_IER);
    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_IER, Register | Mask);
}

void XTcb_planner_accel_InterruptDisable(XTcb_planner_accel *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_IER);
    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_IER, Register & (~Mask));
}

void XTcb_planner_accel_InterruptClear(XTcb_planner_accel *InstancePtr, u32 Mask) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_planner_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_ISR, Mask);
}

u32 XTcb_planner_accel_InterruptGetEnabled(XTcb_planner_accel *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_IER);
}

u32 XTcb_planner_accel_InterruptGetStatus(XTcb_planner_accel *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XTcb_planner_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_PLANNER_ACCEL_CONTROL_ADDR_ISR);
}

