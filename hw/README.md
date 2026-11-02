# hw/ —— FPGA 硬件工程

## 当前使用的完整工程

双击本目录的 `打开当前完整FPGA工程.lnk`，使用 Vivado 2024.2 打开：

`C:\fpga_build\audio_fp32_20261027\tcb705_parallel_fp32.xpr`

包含 100 MHz 单精度七轴规划核、MD0700R 显示、GT911 触摸、GE_PL 网口、笔迹识别和 WM8960 朗读模块。
2026-10-27 编译结果：建立余量 0.265 ns，保持余量 0.050 ns，DRC 错误 0。此处是构建验收结果，不代表板端出声已经验收。

| 目录 | 用途 |
|---|---|
| `parallel/` | 当前 FP32 工程创建和编译 Tcl |
| `audio/` | 音频 RTL、引脚约束、仿真及集成 Tcl |
| `vision/baseline/recreate_vision_bd.tcl` | 当前工程重建必需的外围模块基线；已从旧工程独立保存 |
| `ip/`、`vendor/` | 当前及历史构建需要的 IP 源码；其中工具生成的内部子工程不是重复顶层工程 |
| `md0700r/`、`ge_pl/`、`lineart/`、`target_ik/`、`vision/` | 硬件模块源码、约束及重建脚本 |
| `reports/audio_fp32_20261027/` | 当前完整平台的时序、资源和 DRC 报告 |
| `../overlay/tcb705_audio_fp32_20261027/` | 已封装的新平台 bit、hwh、寄存器映射及校验清单 |

重新构建：运行 `scripts/build_audio_fp32.ps1 -ProjectDirectory C:\fpga_build\新的空目录`。构建仍依赖脚本中声明的 FP32 HLS IP 路径。

## 旧工程清理记录（2026-10-28）

以下六套旧顶层工程已清出本项目：`vivado`、`vivado_audio`、`vivado_ge_pl`、`vivado_lineart`、`vivado_v2c_gepl`、`vivado_vision`。
完整备份在 `D:\zhiliao\TCB705_ZYNQ-10-15\Vivado旧工程备份_20261028`，附文件数量、字节数及原路径清单。仅移动旧构建产物，没有删除模块源码、IP、已封装平台、用户数据或标定。
旧构建脚本仍可用于重建其对应历史版本；不要把历史版本误作当前部署版本。原旧工程内部的相对路径可能依赖原位置，需要恢复到原路径后再打开。
`../NA/` 是历史重建流程引用的资源，仍予保留。
