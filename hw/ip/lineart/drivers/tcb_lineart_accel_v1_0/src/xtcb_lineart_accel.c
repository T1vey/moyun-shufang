// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
/***************************** Include Files *********************************/
#include "xtcb_lineart_accel.h"

/************************** Function Implementation *************************/
#ifndef __linux__
int XTcb_lineart_accel_CfgInitialize(XTcb_lineart_accel *InstancePtr, XTcb_lineart_accel_Config *ConfigPtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(ConfigPtr != NULL);

    InstancePtr->Control_BaseAddress = ConfigPtr->Control_BaseAddress;
    InstancePtr->IsReady = XIL_COMPONENT_IS_READY;

    return XST_SUCCESS;
}
#endif

void XTcb_lineart_accel_Start(XTcb_lineart_accel *InstancePtr) {
    u32 Data;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_AP_CTRL) & 0x80;
    XTcb_lineart_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_AP_CTRL, Data | 0x01);
}

u32 XTcb_lineart_accel_IsDone(XTcb_lineart_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_AP_CTRL);
    return (Data >> 1) & 0x1;
}

u32 XTcb_lineart_accel_IsIdle(XTcb_lineart_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_AP_CTRL);
    return (Data >> 2) & 0x1;
}

u32 XTcb_lineart_accel_IsReady(XTcb_lineart_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_AP_CTRL);
    // check ap_start to see if the pcore is ready for next input
    return !(Data & 0x1);
}

void XTcb_lineart_accel_EnableAutoRestart(XTcb_lineart_accel *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_lineart_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_AP_CTRL, 0x80);
}

void XTcb_lineart_accel_DisableAutoRestart(XTcb_lineart_accel *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_lineart_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_AP_CTRL, 0);
}

u32 XTcb_lineart_accel_Get_return(XTcb_lineart_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_AP_RETURN);
    return Data;
}
void XTcb_lineart_accel_Set_src(XTcb_lineart_accel *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_lineart_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_SRC_DATA, (u32)(Data));
    XTcb_lineart_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_SRC_DATA + 4, (u32)(Data >> 32));
}

u64 XTcb_lineart_accel_Get_src(XTcb_lineart_accel *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_SRC_DATA);
    Data += (u64)XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_SRC_DATA + 4) << 32;
    return Data;
}

void XTcb_lineart_accel_Set_dst(XTcb_lineart_accel *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_lineart_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_DST_DATA, (u32)(Data));
    XTcb_lineart_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_DST_DATA + 4, (u32)(Data >> 32));
}

u64 XTcb_lineart_accel_Get_dst(XTcb_lineart_accel *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_DST_DATA);
    Data += (u64)XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_DST_DATA + 4) << 32;
    return Data;
}

void XTcb_lineart_accel_Set_width(XTcb_lineart_accel *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_lineart_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_WIDTH_DATA, Data);
}

u32 XTcb_lineart_accel_Get_width(XTcb_lineart_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_WIDTH_DATA);
    return Data;
}

void XTcb_lineart_accel_Set_height(XTcb_lineart_accel *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_lineart_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_HEIGHT_DATA, Data);
}

u32 XTcb_lineart_accel_Get_height(XTcb_lineart_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_HEIGHT_DATA);
    return Data;
}

u32 XTcb_lineart_accel_Get_deleted(XTcb_lineart_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_DELETED_DATA);
    return Data;
}

u32 XTcb_lineart_accel_Get_deleted_vld(XTcb_lineart_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_DELETED_CTRL);
    return Data & 0x1;
}

u32 XTcb_lineart_accel_Get_identity(XTcb_lineart_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_IDENTITY_DATA);
    return Data;
}

u32 XTcb_lineart_accel_Get_identity_vld(XTcb_lineart_accel *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_IDENTITY_CTRL);
    return Data & 0x1;
}

void XTcb_lineart_accel_InterruptGlobalEnable(XTcb_lineart_accel *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_lineart_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_GIE, 1);
}

void XTcb_lineart_accel_InterruptGlobalDisable(XTcb_lineart_accel *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_lineart_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_GIE, 0);
}

void XTcb_lineart_accel_InterruptEnable(XTcb_lineart_accel *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_IER);
    XTcb_lineart_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_IER, Register | Mask);
}

void XTcb_lineart_accel_InterruptDisable(XTcb_lineart_accel *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_IER);
    XTcb_lineart_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_IER, Register & (~Mask));
}

void XTcb_lineart_accel_InterruptClear(XTcb_lineart_accel *InstancePtr, u32 Mask) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XTcb_lineart_accel_WriteReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_ISR, Mask);
}

u32 XTcb_lineart_accel_InterruptGetEnabled(XTcb_lineart_accel *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_IER);
}

u32 XTcb_lineart_accel_InterruptGetStatus(XTcb_lineart_accel *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XTcb_lineart_accel_ReadReg(InstancePtr->Control_BaseAddress, XTCB_LINEART_ACCEL_CONTROL_ADDR_ISR);
}

