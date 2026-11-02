// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
#ifndef __linux__

#include "xstatus.h"
#ifdef SDT
#include "xparameters.h"
#endif
#include "xtcb_brush_recog.h"

extern XTcb_brush_recog_Config XTcb_brush_recog_ConfigTable[];

#ifdef SDT
XTcb_brush_recog_Config *XTcb_brush_recog_LookupConfig(UINTPTR BaseAddress) {
	XTcb_brush_recog_Config *ConfigPtr = NULL;

	int Index;

	for (Index = (u32)0x0; XTcb_brush_recog_ConfigTable[Index].Name != NULL; Index++) {
		if (!BaseAddress || XTcb_brush_recog_ConfigTable[Index].Control_BaseAddress == BaseAddress) {
			ConfigPtr = &XTcb_brush_recog_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XTcb_brush_recog_Initialize(XTcb_brush_recog *InstancePtr, UINTPTR BaseAddress) {
	XTcb_brush_recog_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XTcb_brush_recog_LookupConfig(BaseAddress);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XTcb_brush_recog_CfgInitialize(InstancePtr, ConfigPtr);
}
#else
XTcb_brush_recog_Config *XTcb_brush_recog_LookupConfig(u16 DeviceId) {
	XTcb_brush_recog_Config *ConfigPtr = NULL;

	int Index;

	for (Index = 0; Index < XPAR_XTCB_BRUSH_RECOG_NUM_INSTANCES; Index++) {
		if (XTcb_brush_recog_ConfigTable[Index].DeviceId == DeviceId) {
			ConfigPtr = &XTcb_brush_recog_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XTcb_brush_recog_Initialize(XTcb_brush_recog *InstancePtr, u16 DeviceId) {
	XTcb_brush_recog_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XTcb_brush_recog_LookupConfig(DeviceId);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XTcb_brush_recog_CfgInitialize(InstancePtr, ConfigPtr);
}
#endif

#endif

