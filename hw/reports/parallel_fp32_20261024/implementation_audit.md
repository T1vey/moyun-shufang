# FP32 完整平台布线后只读审计

审计日期：2026-10-24。对象：`C:/fpga_build/p32full_20261024`，Vivado 2024.2，`xc7z020clg400-2`。本次只读取报告、HWH 和现有约束；没有修改源码、约束或工程，没有下载到板子或驱动机械臂。

## 结论

**新增 FP32 逆解与 AXI 通道在完整平台上以 100 MHz 通过布线后时序检查，未发现新增未约束内部路径或未同步 CDC。全平台仍有既有显示、触摸和 GE_PL 告警，不能称为“零告警设计”。**

- 全平台建立余量 WNS **+0.230 ns**、TNS **0**；保持余量 WHS **+0.011 ns**、THS **0**；脉宽余量 **+0.264 ns**，均无失败端点。
- 新核 `clk_fpga_1`：周期 **10.000 ns**，建立余量 **+0.600 ns**。最差路径位于私有 CORDIC 的指数归一化逻辑，实际数据路径 9.145 ns，约 65% 为布线延迟。这是实际完整设计结果，不是 HLS 估计。
- `check_timing.rpt`：无时钟寄存器 **0**、未约束内部端点 **0**、断源生成时钟 **0**、组合环 **0**。
- `bus_skew.rpt` 的 **10 项全部满足**，最小余量 **+28.722 ns**。
- 最终 `drc.rpt`：**0 Error、0 Critical Warning**；仍有 556 个 Warning/Advisory 检查实例。Methodology 与 CDC 使用各自的严重性等级，详见下文，不与 DRC 零错误混为一谈。
- 日志明确记录 `Bitgen Completed Successfully`、`FP32_FULL_BUILD_COMPLETE_NO_BOARD_PROGRAMMING`；BIT、HWH、XSA 已导出。本审计不代表板上联调完成。

## 时钟、复位和 AXI

已核对最终生成的 HWH：新核 `ap_clk`、输入互连 `planner_ddr` 的全部 AXI 时钟、输出互连 `planner_output_ddr` 的全部 AXI 时钟、PS HP1/HP3 都连接 **FCLK1 100 MHz**。它们的复位来自 `rst_tcb_planner/peripheral_aresetn`；该复位 IP 的同步时钟也是 FCLK1，外部复位接有效低 FCLK_RESET1_N，辅助有效高复位接常数 0。

PS 控制寄存器访问在 FCLK0/FCLK1 间通过现有 M06 AXI clock converter：CDC 报告识别为三级、带 `ASYNC_REG` 的同步器（CDC-3 Info）。新增 HP3 结果写通路处于同一 FCLK1 域，没有新增异步数据跨域。

## 继承告警与新增 IP 提示

| 项目 | 本次结果与对照 |
|---|---|
| Methodology Critical Warning 6 项 | TIMING-4 ×1、TIMING-27 ×1 是 LCD `clk_wiz_0/inst/clk_in1` 下游重复主时钟定义；TIMING-54 ×4 是 GE_PL 发送时钟的 scoped false-path。旧 `hw/reports/ge_pl/timing_summary.rpt` 及 `hw/reports/lineart/baseline_timing_summary.rpt` 已有相同规则和数量。LCD 两项在 10 月 17 日 `tcb705_vivado_final/methodology.rpt` 中也有相同对象。 |
| CDC Critical 8 项与 Warning 1 项 | CDC-1 ×2 是 GE_PL 的 ENET1_GMII_COL/CRS；CDC-13 ×6 属 GE_PL 时钟切换/非触发器原语路径；CDC-6 ×1 属 LCD VTC 数据同步。**最终 CDC 报告从“CDC Report”开始的完整正文与 10 月 18 日 `lineart/baseline_cdc.rpt` 逐字一致**，没有新增条目；部分旧 GE_PL 端点在原报告中为 `<hidden>`，不能据此宣布这些旧问题已经消除。 |
| 外部 I/O 约束缺口 | 5 个输入未设延时、33 个输出未设延时，另 1 个输出已有传播时钟；1 个多时钟 pin。旧 GE_PL `check_timing_verbose.rpt` 已列出相同数量，涉及 LCD、触摸、MDIO 及 GE_PL 时钟 mux。CDC 工具会跳过没有输入延时的端口，所以“未新增 CDC”不等于所有外部接口都已完整证明。 |
| 新输出 AXI IP 的 LUTAR-1 | `planner_output_ddr/s00_couplers/auto_pc` 有 **2 项** FIFO 内部 LUT 驱动异步复位提示。旧输入互连、LCD、vision 的同类官方 AXI4→AXI3 IP 也有该类提示；它不是新增未约束路径或手写 CDC，但仍明确保留为待板端复位/连续传输回归的告警。没有在本次只读审计中豁免或修改它。 |

## 资源余量须披露

完整布线设计：LUT **39,743/53,200（74.70%）**，FF **55,925/106,400（52.56%）**，DSP **94/220（42.73%）**，BRAM Tile **59.5/140（42.50%）**。实际使用 Slice **13,256/13,300（99.67%）**，1151 个控制集合；布局空间已经很紧。不能仅凭 LUT 还剩约 25% 就判断能继续增加同等规模的逻辑。

## 证据位置

- 最终报告：[export](C:/fpga_build/p32full_20261024/export)：`timing_summary.rpt`、`clocks.rpt`、`check_timing.rpt`、`cdc.rpt`、`bus_skew.rpt`、`drc.rpt`、`utilization.rpt`、`build_verified.json`。
- Methodology 详细报告：[system_wrapper_methodology_drc_routed.rpt](C:/fpga_build/p32full_20261024/tcb705_parallel_fp32.runs/impl_1/system_wrapper_methodology_drc_routed.rpt)。
- 完整路由时序详情：[system_wrapper_timing_summary_routed.rpt](C:/fpga_build/p32full_20261024/tcb705_parallel_fp32.runs/impl_1/system_wrapper_timing_summary_routed.rpt)。
- 对照旧报告：[baseline_cdc.rpt](../lineart/baseline_cdc.rpt)、[GE_PL timing](../ge_pl/timing_summary.rpt)、[GE_PL I/O 列表](../ge_pl/check_timing_verbose.rpt)。

后续板上需要验证新三个 AXI 主端口的持续读写、取消与复位，以及 LCD/触摸/GE_PL 并发运行。这里的时序和报告审计不替代这些实机检查。
