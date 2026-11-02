# 验证与性能

不同层级的数字对应不同问题；以下链接指向原包报告，不将整理日期当成新一次硬件测试。

| 项目 | 结果 | 条件 / 来源 |
|---|---|---|
| FP32 核吞吐 | 116,104–116,273 点/s | 100 MHz RTL cosim，64 点/事务；`hw/reports/parallel_fp32_20261024/hls/throughput_cycles.xml` |
| 完整轨迹连续回放 | 21,679/21,679，0 CPU 回退 | 同源 HLS C++ 主机离线回放；`hw/reports/parallel_fp32_20261024/full_trajectory/summary.json` |
| 最大计算位置误差 | 3.938234e-7 m，约 0.39 µm | 上述轨迹与独立 FP64 正解比较，不含标定和机械误差 |
| 最终音频 IOBUF 平台 | LUT 40,048（75.28%） | 2026-10-27 Routed；`hw/reports/audio_iobuf_20261027/utilization.rpt` |
| 最终平台时序 | WNS +0.136 ns，WHS +0.011 ns | `hw/reports/audio_iobuf_20261027/build_verified.json` 与 `timing_summary.rpt` |
| 历史联合软件验证 | 245 项通过 | 2026-10-24 离线软件回归；`hw/reports/parallel_fp32_20261024/software/final_software_validation.json` |

## 板端路径与系统瓶颈

[2026-10-24 板端记录](../hw/reports/parallel_fp32_20261024/board_20261024/README.md)包含实际时钟、自检和规划对照，无机械臂运动：

| 输入与代码 | CPU 逆解路径 | FPGA FP32 路径 |
|---|---:|---:|
| 同一新版代码，8 笔人像，4,744 节点，热规划 | 6.28 s | 9.23 s |
| 复杂线稿，21,680 节点，两次整图规划 | 27.05 / 24.97 s | 37.94 / 40.57 s |

当前板端 64 点调用包含 PS 调度、缓存与结果解析，约 32–33 ms/批；因此实际整图路径仍慢于 ARM 原生 CPU。RTL 吞吐说明核的计算能力，不能代替整机加速结论。新版减少重复 FK 复核带来的软件收益，也不计作 FPGA 收益。

## 使用这些结果

- “0 回退”限于记录的该条连续历史轨迹，不外推到任意目标。
- 0.39 µm 是模型计算误差，不是实物笔尖或墨迹精度。
- HLS 估计、布线后整板资源、板端测量分别引用各自文件。
- 3500 字已生成并检查轨迹，不表示逐字实写验收。
- 本次仓库整理仅做本机复现检查，没有重新综合、烧录或驱动机械臂。

本次整理验证结果见 `public_release_validation.json`；新增发布检查入口为 `scripts/verify_public_release.py`。

2026-11-02 本机公开版检查：87 项通过、0 失败、0 错误、0 跳过；模拟网页和后端状态接口均返回 HTTP 200。校验与技能脚本分别通过源码检查、正常/哈希损坏/缺件三种夹具检查。Windows 中文路径的 ONNX 加载问题已用内存加载修复；桌面验证使用 OpenCV 4.10.0。
