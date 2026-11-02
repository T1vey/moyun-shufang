# scripts/ —— 命令行脚本

## TCB705（主线）

| 脚本 | 作用 | 会让机械臂动吗 |
|---|---|---|
| `run_tcb705.py` | 启动后端 + 界面（`run_tcb705.bat` 调用它） | 只有在界面里确认执行时 |
| `tcb705_web_draw.py` | 命令行走完整流程：登记笔画 → 本地规划 → 执行 | 加 `--execute` 时 |
| `tcb705_calibrate_capture.py` | 采集关节标定样本（空中 20 个姿态） | 加 `--execute` 时 |
| `tcb705_demo.py` | 无控制器演示：规划、预测、模拟执行 | 否 |
| `tcb705_profile.py` | 准备/校验配置，只读查询控制器 | 否 |
| `tcb705_commission.py` | 网口检查、离线坐标分析 | 否 |
| `build_tcb705.py` | 编译 C++ 核心、模拟执行器、SDK 探针 | 否 |
| `build_tcb705_hls.ps1` / `build_tcb705_vivado.ps1` | 重新生成 HLS IP / Vivado 平台 | 否 |
| `load_platform.py` | 板子开机加载 FPGA 平台（系统服务调用） | 否 |
| `start_ge_pl.py` | 启用 PL 网口 | 否 |
| `benchmark_tcb705_acceleration.py` / `benchmark_tcb705_hardware.py` | CPU / FPGA 规划速度对比 | 否 |
| `verify_tcb705.py` | 回归测试并保存报告 | 否 |
| `package_tcb705.py` / `package_tcb705_platform.py` / `import_tcb705_assets.py` | 打包、封装平台、导入资料 | 否 |
| `export_tcb_register_map.py` | 从 HLS 头文件导出七轴核寄存器表 | 否 |

## 界面与板端共用

`run_user_gui.py`、`user_gui_kiosk.py`、`run_touch_gui.py`、`touch_*.py`、`sugar_*.py`、`drawing_preview_ui.py`、`bluetooth_receiver.py`、`arm_studio.py`（含 `BoardClient`，测试和 `tcb705_web_draw.py` 都在用）。

## SO101 旧机械臂

其余脚本（`benchmark_planning_*`、`check_*_overlay.py`、`export_*_register_map.py`、`identify_servo_dynamics.py`、`simulate_closed_loop.py`、`hand_follow_server.py`、`kinematic_calibration*.py`、`build_delivery.py` 等）属于 SO101 舵机方案，仍被旧代码或测试引用，所以保留在这里。完全没人引用的已移到 `_archive/scripts/`。
