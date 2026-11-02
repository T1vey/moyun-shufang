// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
#ifndef XTCB_BRUSH_RECOG_H
#define XTCB_BRUSH_RECOG_H

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
#include "xtcb_brush_recog_hw.h"

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
} XTcb_brush_recog_Config;
#endif

typedef struct {
    u64 Control_BaseAddress;
    u32 IsReady;
} XTcb_brush_recog;

typedef u32 word_type;

/***************** Macros (Inline Functions) Definitions *********************/
#ifndef __linux__
#define XTcb_brush_recog_WriteReg(BaseAddress, RegOffset, Data) \
    Xil_Out32((BaseAddress) + (RegOffset), (u32)(Data))
#define XTcb_brush_recog_ReadReg(BaseAddress, RegOffset) \
    Xil_In32((BaseAddress) + (RegOffset))
#else
#define XTcb_brush_recog_WriteReg(BaseAddress, RegOffset, Data) \
    *(volatile u32*)((BaseAddress) + (RegOffset)) = (u32)(Data)
#define XTcb_brush_recog_ReadReg(BaseAddress, RegOffset) \
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
int XTcb_brush_recog_Initialize(XTcb_brush_recog *InstancePtr, UINTPTR BaseAddress);
XTcb_brush_recog_Config* XTcb_brush_recog_LookupConfig(UINTPTR BaseAddress);
#else
int XTcb_brush_recog_Initialize(XTcb_brush_recog *InstancePtr, u16 DeviceId);
XTcb_brush_recog_Config* XTcb_brush_recog_LookupConfig(u16 DeviceId);
#endif
int XTcb_brush_recog_CfgInitialize(XTcb_brush_recog *InstancePtr, XTcb_brush_recog_Config *ConfigPtr);
#else
int XTcb_brush_recog_Initialize(XTcb_brush_recog *InstancePtr, const char* InstanceName);
int XTcb_brush_recog_Release(XTcb_brush_recog *InstancePtr);
#endif

void XTcb_brush_recog_Start(XTcb_brush_recog *InstancePtr);
u32 XTcb_brush_recog_IsDone(XTcb_brush_recog *InstancePtr);
u32 XTcb_brush_recog_IsIdle(XTcb_brush_recog *InstancePtr);
u32 XTcb_brush_recog_IsReady(XTcb_brush_recog *InstancePtr);
void XTcb_brush_recog_EnableAutoRestart(XTcb_brush_recog *InstancePtr);
void XTcb_brush_recog_DisableAutoRestart(XTcb_brush_recog *InstancePtr);
u32 XTcb_brush_recog_Get_return(XTcb_brush_recog *InstancePtr);

void XTcb_brush_recog_Set_mode(XTcb_brush_recog *InstancePtr, u32 Data);
u32 XTcb_brush_recog_Get_mode(XTcb_brush_recog *InstancePtr);
void XTcb_brush_recog_Set_params(XTcb_brush_recog *InstancePtr, u64 Data);
u64 XTcb_brush_recog_Get_params(XTcb_brush_recog *InstancePtr);
void XTcb_brush_recog_Set_src(XTcb_brush_recog *InstancePtr, u64 Data);
u64 XTcb_brush_recog_Get_src(XTcb_brush_recog *InstancePtr);
void XTcb_brush_recog_Set_dst(XTcb_brush_recog *InstancePtr, u64 Data);
u64 XTcb_brush_recog_Get_dst(XTcb_brush_recog *InstancePtr);
void XTcb_brush_recog_Set_tpl(XTcb_brush_recog *InstancePtr, u64 Data);
u64 XTcb_brush_recog_Get_tpl(XTcb_brush_recog *InstancePtr);
u32 XTcb_brush_recog_Get_identity(XTcb_brush_recog *InstancePtr);
u32 XTcb_brush_recog_Get_identity_vld(XTcb_brush_recog *InstancePtr);

void XTcb_brush_recog_InterruptGlobalEnable(XTcb_brush_recog *InstancePtr);
void XTcb_brush_recog_InterruptGlobalDisable(XTcb_brush_recog *InstancePtr);
void XTcb_brush_recog_InterruptEnable(XTcb_brush_recog *InstancePtr, u32 Mask);
void XTcb_brush_recog_InterruptDisable(XTcb_brush_recog *InstancePtr, u32 Mask);
void XTcb_brush_recog_InterruptClear(XTcb_brush_recog *InstancePtr, u32 Mask);
u32 XTcb_brush_recog_InterruptGetEnabled(XTcb_brush_recog *InstancePtr);
u32 XTcb_brush_recog_InterruptGetStatus(XTcb_brush_recog *InstancePtr);

#ifdef __cplusplus
}
#endif

#endif
