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
#include "xtcb_lineart_accel.h"

extern XTcb_lineart_accel_Config XTcb_lineart_accel_ConfigTable[];

#ifdef SDT
XTcb_lineart_accel_Config *XTcb_lineart_accel_LookupConfig(UINTPTR BaseAddress) {
	XTcb_lineart_accel_Config *ConfigPtr = NULL;

	int Index;

	for (Index = (u32)0x0; XTcb_lineart_accel_ConfigTable[Index].Name != NULL; Index++) {
		if (!BaseAddress || XTcb_lineart_accel_ConfigTable[Index].Control_BaseAddress == BaseAddress) {
			ConfigPtr = &XTcb_lineart_accel_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XTcb_lineart_accel_Initialize(XTcb_lineart_accel *InstancePtr, UINTPTR BaseAddress) {
	XTcb_lineart_accel_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XTcb_lineart_accel_LookupConfig(BaseAddress);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XTcb_lineart_accel_CfgInitialize(InstancePtr, ConfigPtr);
}
#else
XTcb_lineart_accel_Config *XTcb_lineart_accel_LookupConfig(u16 DeviceId) {
	XTcb_lineart_accel_Config *ConfigPtr = NULL;

	int Index;

	for (Index = 0; Index < XPAR_XTCB_LINEART_ACCEL_NUM_INSTANCES; Index++) {
		if (XTcb_lineart_accel_ConfigTable[Index].DeviceId == DeviceId) {
			ConfigPtr = &XTcb_lineart_accel_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XTcb_lineart_accel_Initialize(XTcb_lineart_accel *InstancePtr, u16 DeviceId) {
	XTcb_lineart_accel_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XTcb_lineart_accel_LookupConfig(DeviceId);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XTcb_lineart_accel_CfgInitialize(InstancePtr, ConfigPtr);
}
#endif

#endif

