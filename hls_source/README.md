# hls_source/ —— FPGA 七轴 IK 核源码（Vitis HLS）

| 文件 | 内容 |
|---|---|
| `tcb705/tcb_planner_accel.cpp/.h` | 顶层：从 DDR 读上下文（模型 147 参数、4×4 工具、IK 选项、种子、姿态）和目标点，逐行求解；IK 链起点用前两点外推 `2q[k]-q[k-1]` |
| `tcb705/pl_math7.hpp` | **v2c（2026-10-18）**：自写 sin/cos（fdlibm 系数，误差 1e-16）、刚体 3×4 变换、流水化雅可比与 7×7 求解 |
| `tcb705/pl_math7_v1.hpp` | 原版本，仅用于对比 |
| `tcb705/tb_tcb_planner.cpp` + `vectors.txt` | C/RTL 仿真测试与金标准向量 |
| `tcb705/tcb_planner_2024.cfg` | Vitis HLS 配置，时钟 13 ns（板上实际 FCLK_CLK1 76.92 MHz） |

## v1 → v2c（HLS 综合，xc7z020，13 ns）

| | v1 | v2c |
|---|---|---|
| 含 7×7 求解的一次迭代 | 22,214 周期 | 5,847 |
| 仅 FK+雅可比 | ~8,800 | ~950 |
| 每点迭代次数（外推种子） | 2 | 1 |
| **每点耗时** | **≈0.92 ms** | **≈0.10 ms** |
| LUT / DSP（本核） | 26.5k / 113 | 33.9k / 70 |

一致性：4 万次随机 IK 与 v1 状态、迭代数相同，关节差 ≤2.7e-10 rad；C 仿真通过。对比程序：`build/tcb705/ik_speed/ab_test.cpp`、`seed_test.cpp`。

调用方：`tcb705/planning_batches.py` 的 `PLChain`（每批 ≤64 点；每个结果由 CPU FP64 复核）。CPU 核 `native/tcb_planner/core.cpp` 使用同样的外推规则。
