# TCB705 七轴 FP32 并行逆解核

此目录是本次单精度版本。`hls_source/tcb705_parallel` 为此前 FP64 实验，`hls_source/tcb705` 为旧平台实现，均保留作对照。

## 数据流

```text
AXI gmem_control ── 模型、初始姿态、取消标记 ────────────────┐
                                                        │
AXI gmem_input → 几何分解 → FIFO → CORDIC / 连续选解 → FIFO
                                                        ↓
                                        有限值、关节限位、步长、取消
                                                        ↓
                                             AXI gmem_output
```

三个任务采用 HLS DATAFLOW 并发运行；相邻点保留肘部方向和前一组关节角，以选择连续分支。每级终止后仍排空本次固定数量的 FIFO 消息，输出只提交成功前缀和首个失败点。

- 目标器件：`xc7z020clg400-2`，目标 FCLK1：100 MHz。
- 几何、乘除、选解计算使用 FP32；反正切内部使用 32 位定点 CORDIC，输入输出为 FP32。最终候选复用一个 CORDIC 通道计算七角，几何、角度、写出三个阶段仍并发；这是为完整屏幕/网口平台留资源的选择。
- 为兼容现有主机缓冲区，DDR 数据布局仍为原 FP64 打包格式，边界处转换。不能把它称为全链路 32 位传输。
- 初始肘部位置只需两角 sin/cos，使用专用函数，避免综合不使用的完整 FK 逻辑。
- 新核仅支持 `IK_CHAIN`。`FK_ROWS` 显式拒绝，普通 CPU FK 功能仍可供现场状态和离线分析使用。
- 接近奇异位置、模型不支持、分支不可连续或超限时，返回 PARTIAL，由主机处理未完成后缀。

## 不再执行的重复检查

新核不计算解出关节角后的独立 FK 误差；成功行误差字段使用规范 quiet-NaN，完成头 capabilities=3 明确表示 FP32 和“误差未评估”。主机转为 JSON `null`，不把未测量误差显示成零。旧核能力位为 0，仍按旧协议检查有限误差值。

软件规划不再生成曲线 FK 探针或对密集时间采样帧做 FK 复核。实际执行需要的时间戳、插补系数、速度/加速度/关节边界以及停止处理保留。图案预览直接采用云端返回的线稿，不再用运动学结果生成预测图。字库/手写预览仍来自预设路径。

## 数值验证的边界

运行时删除复核不等于开发阶段不做验证。测试使用独立 FP64 矩阵正解作为数值参考，预算为位置 `1e-5 m`（0.01 mm）、姿态 `1e-4 rad`。原先 `1e-7 m / 1e-6 rad` 的通过数量另行记录；单精度不保证全部满足原门限。测试误差是计算误差，不能代表机械臂实际笔尖精度。

奇异保护采用 0.05 的条件门槛；该保护是限定解析公式适用区域，不是逐点 FK 复核。回退比例取决于轨迹与初始姿态，不能用普通历史轨迹吞吐量承诺所有位置的速度。

## 重建

在工程根目录运行：

```powershell
./scripts/build_tcb705_parallel_fp32_hls.ps1 -BuildDirectory C:\fpga_build\p32_rebuild -Profile controller_throughput -Stage all
./scripts/build_tcb705_parallel_fp32_hls.ps1 -BuildDirectory C:\fpga_build\p32_rebuild -Profile contract -Stage all
./scripts/build_tcb705_parallel_fp32_vivado.ps1 -HlsDirectory C:\fpga_build\p32_rebuild -ProjectDirectory C:\fpga_build\p32_full_rebuild -Stage all
```

Vivado 默认创建全新的 `C:\fpga_build\p32full_20261024\tcb705_parallel_fp32.xpr`；上面的重建例子另指定了全新目录。短路径用于避免 Windows/Vivado 子 IP 文件名超过工具限制。平台保留 MD0700R、GT911、GE_PL、vision 核。读取接口使用 HP1，写接口使用 HP3；LCD 使用 HP0，vision 使用 HP2。工程不包含 lineart thinning 核，软件根据平台实际能力直接选 CPU。

Vivado 导出目录为编译工程下的 `export`。交付时把通过验证的文件整理至本工程的 `hw/reports/parallel_fp32_20261024` 和新 overlay 目录。只有布局布线时序、DRC 和 RTL 仿真都通过后，才能宣布完成。HLS 的 10 ns 配置不是时序收敛证据。

每批 64 个有效目标必须少于 80,000 个时钟周期，才在 100 MHz 下超过 80,000 点/秒。RTL 统计包含本次 AXI 测试模型的读写与初始化，但不包含板端 Python 调度、缓存维护、真实 DDR 争用或 CPU 回退。整图规划和真实落纸速度需要单独上板测量。

上述脚本只编译、仿真和导出，不烧录板卡、不让机械臂运动。

## 执行准备的变化

下发前也不再执行按 FK 误差合并节点、关节段插值 FK 复核或手写中间点 FK 复核，而是保留已规划的细节点。现有连续队列、全局速度、平滑参数及停止处理保留，没有新增逐段 sleep。

一个 40 mm 横笔画的本机对照中，558 个节点原来合并为 78 条命令，现在保留 557 条命令；准备计算由约 100.6 ms 变为 3.7 ms。这不是 ZYNQ 实测，也不能说明实际书写会更快。命令数量增多对控制器队列的影响需后续实机测量。
