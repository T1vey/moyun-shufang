// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
#ifndef XTCB_LINEART_ACCEL_H
#define XTCB_LINEART_ACCEL_H

#ifdef __cplusplus
extern "C" {
#endif

/***************************** Include Files *********************************/
#ifndef __linux__
#include "xil_types.h"
#include "xil_assert.h"
#include "xstatus.h"
#include "xil_io.h"
#else
#include <stdint.h>
#include <assert.h>
#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stddef.h>
#endif
#include "xtcb_lineart_accel_hw.h"

/**************************** Type Definitions ******************************/
#ifdef __linux__
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#else
typedef struct {
#ifdef SDT
    char *Name;
#else
    u16 DeviceId;
#endif
    u64 Control_BaseAddress;
} XTcb_lineart_accel_Config;
#endif

typedef struct {
    u64 Control_BaseAddress;
    u32 IsReady;
} XTcb_lineart_accel;

typedef u32 word_type;

/***************** Macros (Inline Functions) Definitions *********************/
#ifndef __linux__
#define XTcb_lineart_accel_WriteReg(BaseAddress, RegOffset, Data) \
    Xil_Out32((BaseAddress) + (RegOffset), (u32)(Data))
#define XTcb_lineart_accel_ReadReg(BaseAddress, RegOffset) \
    Xil_In32((BaseAddress) + (RegOffset))
#else
#define XTcb_lineart_accel_WriteReg(BaseAddress, RegOffset, Data) \
    *(volatile u32*)((BaseAddress) + (RegOffset)) = (u32)(Data)
#define XTcb_lineart_accel_ReadReg(BaseAddress, RegOffset) \
    *(volatile u32*)((BaseAddress) + (RegOffset))

#define Xil_AssertVoid(expr)    assert(expr)
#define Xil_AssertNonvoid(expr) assert(expr)

#define XST_SUCCESS             0
#define XST_DEVICE_NOT_FOUND    2
#define XST_OPEN_DEVICE_FAILED  3
#define XIL_COMPONENT_IS_READY  1
#endif

/************************** Function Prototypes *****************************/
#ifndef __linux__
#ifdef SDT
int XTcb_lineart_accel_Initialize(XTcb_lineart_accel *InstancePtr, UINTPTR BaseAddress);
XTcb_lineart_accel_Config* XTcb_lineart_accel_LookupConfig(UINTPTR BaseAddress);
#else
int XTcb_lineart_accel_Initialize(XTcb_lineart_accel *InstancePtr, u16 DeviceId);
XTcb_lineart_accel_Config* XTcb_lineart_accel_LookupConfig(u16 DeviceId);
#endif
int XTcb_lineart_accel_CfgInitialize(XTcb_lineart_accel *InstancePtr, XTcb_lineart_accel_Config *ConfigPtr);
#else
int XTcb_lineart_accel_Initialize(XTcb_lineart_accel *InstancePtr, const char* InstanceName);
int XTcb_lineart_accel_Release(XTcb_lineart_accel *InstancePtr);
#endif

void XTcb_lineart_accel_Start(XTcb_lineart_accel *InstancePtr);
u32 XTcb_lineart_accel_IsDone(XTcb_lineart_accel *InstancePtr);
u32 XTcb_lineart_accel_IsIdle(XTcb_lineart_accel *InstancePtr);
u32 XTcb_lineart_accel_IsReady(XTcb_lineart_accel *InstancePtr);
void XTcb_lineart_accel_EnableAutoRestart(XTcb_lineart_accel *InstancePtr);
void XTcb_lineart_accel_DisableAutoRestart(XTcb_lineart_accel *InstancePtr);
u32 XTcb_lineart_accel_Get_return(XTcb_lineart_accel *InstancePtr);

void XTcb_lineart_accel_Set_src(XTcb_lineart_accel *InstancePtr, u64 Data);
u64 XTcb_lineart_accel_Get_src(XTcb_lineart_accel *InstancePtr);
void XTcb_lineart_accel_Set_dst(XTcb_lineart_accel *InstancePtr, u64 Data);
u64 XTcb_lineart_accel_Get_dst(XTcb_lineart_accel *InstancePtr);
void XTcb_lineart_accel_Set_width(XTcb_lineart_accel *InstancePtr, u32 Data);
u32 XTcb_lineart_accel_Get_width(XTcb_lineart_accel *InstancePtr);
void XTcb_lineart_accel_Set_height(XTcb_lineart_accel *InstancePtr, u32 Data);
u32 XTcb_lineart_accel_Get_height(XTcb_lineart_accel *InstancePtr);
u32 XTcb_lineart_accel_Get_deleted(XTcb_lineart_accel *InstancePtr);
u32 XTcb_lineart_accel_Get_deleted_vld(XTcb_lineart_accel *InstancePtr);
u32 XTcb_lineart_accel_Get_identity(XTcb_lineart_accel *InstancePtr);
u32 XTcb_lineart_accel_Get_identity_vld(XTcb_lineart_accel *InstancePtr);

void XTcb_lineart_accel_InterruptGlobalEnable(XTcb_lineart_accel *InstancePtr);
void XTcb_lineart_accel_InterruptGlobalDisable(XTcb_lineart_accel *InstancePtr);
void XTcb_lineart_accel_InterruptEnable(XTcb_lineart_accel *InstancePtr, u32 Mask);
void XTcb_lineart_accel_InterruptDisable(XTcb_lineart_accel *InstancePtr, u32 Mask);
void XTcb_lineart_accel_InterruptClear(XTcb_lineart_accel *InstancePtr, u32 Mask);
u32 XTcb_lineart_accel_InterruptGetEnabled(XTcb_lineart_accel *InstancePtr);
u32 XTcb_lineart_accel_InterruptGetStatus(XTcb_lineart_accel *InstancePtr);

#ifdef __cplusplus
}
#endif

#endif
