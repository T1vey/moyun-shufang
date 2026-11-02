// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
/***************************** Include Files *********************************/
#include "xtcb_brush_recog.h"

/************************** Function Implementation *************************/
#ifndef __linux__
int XTcb_brush_recog_CfgInitialize(XTcb_brush_recog *InstancePtr, XTcb_brush_recog_Config *ConfigPtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(ConfigPtr != NULL);

    InstancePtr->Control_BaseAddress = ConfigPtr->Control_BaseAddress;
    InstancePtr->IsReady = XIL_COMPONENT_IS_READY;

    return XST_SUCCESS;
}
#endif

void XTcb_brush_recog_Start(XTcb_brush_recog *InstancePtr) {
    u32 Data;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_AP_CTRL) & 0x80;
    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_AP_CTRL, Data | 0x01);
}

u32 XTcb_brush_recog_IsDone(XTcb_brush_recog *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_AP_CTRL);
    return (Data >> 1) & 0x1;
}

u32 XTcb_brush_recog_IsIdle(XTcb_brush_recog *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_AP_CTRL);
    return (Data >> 2) & 0x1;
}

u32 XTcb_brush_recog_IsReady(XTcb_brush_recog *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_AP_CTRL);
    // check ap_start to see if the pcore is ready for next input
    return !(Data & 0x1);
}

void XTcb_brush_recog_EnableAutoRestart(XTcb_brush_recog *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_AP_CTRL, 0x80);
}

void XTcb_brush_recog_DisableAutoRestart(XTcb_brush_recog *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_AP_CTRL, 0);
}

u32 XTcb_brush_recog_Get_return(XTcb_brush_recog *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_AP_RETURN);
    return Data;
}
void XTcb_brush_recog_Set_mode(XTcb_brush_recog *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_MODE_DATA, Data);
}

u32 XTcb_brush_recog_Get_mode(XTcb_brush_recog *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_MODE_DATA);
    return Data;
}

void XTcb_brush_recog_Set_params(XTcb_brush_recog *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_PARAMS_DATA, (u32)(Data));
    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_PARAMS_DATA + 4, (u32)(Data >> 32));
}

u64 XTcb_brush_recog_Get_params(XTcb_brush_recog *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_PARAMS_DATA);
    Data += (u64)XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_PARAMS_DATA + 4) << 32;
    return Data;
}

void XTcb_brush_recog_Set_src(XTcb_brush_recog *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_SRC_DATA, (u32)(Data));
    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_SRC_DATA + 4, (u32)(Data >> 32));
}

u64 XTcb_brush_recog_Get_src(XTcb_brush_recog *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_SRC_DATA);
    Data += (u64)XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_SRC_DATA + 4) << 32;
    return Data;
}

void XTcb_brush_recog_Set_dst(XTcb_brush_recog *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_DST_DATA, (u32)(Data));
    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_DST_DATA + 4, (u32)(Data >> 32));
}

u64 XTcb_brush_recog_Get_dst(XTcb_brush_recog *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_DST_DATA);
    Data += (u64)XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_DST_DATA + 4) << 32;
    return Data;
}

void XTcb_brush_recog_Set_tpl(XTcb_brush_recog *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_TPL_DATA, (u32)(Data));
    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_TPL_DATA + 4, (u32)(Data >> 32));
}

u64 XTcb_brush_recog_Get_tpl(XTcb_brush_recog *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_TPL_DATA);
    Data += (u64)XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_TPL_DATA + 4) << 32;
    return Data;
}

u32 XTcb_brush_recog_Get_identity(XTcb_brush_recog *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_IDENTITY_DATA);
    return Data;
}

u32 XTcb_brush_recog_Get_identity_vld(XTcb_brush_recog *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_IDENTITY_CTRL);
    return Data & 0x1;
}

void XTcb_brush_recog_InterruptGlobalEnable(XTcb_brush_recog *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_GIE, 1);
}

void XTcb_brush_recog_InterruptGlobalDisable(XTcb_brush_recog *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_GIE, 0);
}

void XTcb_brush_recog_InterruptEnable(XTcb_brush_recog *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_IER);
    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_IER, Register | Mask);
}

void XTcb_brush_recog_InterruptDisable(XTcb_brush_recog *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_IER);
    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_IER, Register & (~Mask));
}

void XTcb_brush_recog_InterruptClear(XTcb_brush_recog *InstancePtr, u32 Mask) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_brush_recog_WriteReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_ISR, Mask);
}

u32 XTcb_brush_recog_InterruptGetEnabled(XTcb_brush_recog *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_IER);
}

u32 XTcb_brush_recog_InterruptGetStatus(XTcb_brush_recog *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XTcb_brush_recog_ReadReg(InstancePtr->Control_BaseAddress, XTCB_BRUSH_RECOG_CONTROL_ADDR_ISR);
}

