# 线稿 PL 加速构建验收报告

生成日期：2026-10-20。工具：Vivado / Vitis HLS 2024.2，器件 xc7z020clg400-2。

## 已完成

- 独立 Vivado 工程、综合、布局布线和比特流生成完成。
- 建立时间最差余量 **0.116 ns**；保持时间最差余量 **0.014 ns**；DRC 错误 **0**。
- 软件回归 **244 项全部通过、无跳过**。
- 真实图库 **14 张**：细化位图、原生图追踪、笔画几何和顺序、完整路径哈希与原算法一致。
- HLS C 仿真 **25 组**通过；C/RTL 联合仿真 **10 组**通过，另含非法尺寸保护。真实图库 RTL 样本缩至 96×96，边界样本覆盖最大宽/高 1536、空图及多轮调用。
- 8 级 Zhang–Suen、100 MHz、HP2 DDR；运行时只附着启动验证的平台，异常可回退原 CPU。

## 整个平台资源

|资源|使用量|
|---|---:|
| Slice LUTs | 39238.0 |
| Slice Registers | 43347.0 |
| Block RAM Tile | 37.0 |
| DSPs | 68.0 |

## 保留的平台约束告警

DRC 为 0 错误并不表示所有方法学告警已消除。与原 `vivado_v2c_gepl` 导出报告对照，TIMING-4（1 项）、TIMING-27（1 项）、TIMING-54（4 项）数量一致，分别来自显示时钟 IP 的内部主时钟定义和 GE_PL IP 的 scoped 时钟约束。本次没有通过新增 false path 隐藏线稿路径。

CDC 报告仍有 CDC-1 两项、CDC-13 六项，与原平台一致；可见端点涉及原 GE_PL 的 GMII/时钟切换逻辑。本次不能宣称全平台 CDC 告警已清零。新增线稿数据通路使用同一个 FCLK0 时钟域。

`no_clock=0`、`unconstrained_internal_endpoints=0`；同时保留原平台的 5 个无输入延迟检查项、34 个无输出延迟检查项及 1 个多时钟检查项。因此上述时序通过指**现有约束下的内部时序通过**，外部 LCD/触摸/网口仍须按既有接口要求上板验收。相关原始报告一并保留，不能将其描述为全平台“零告警”。

## 交付位置

- 工程：`hw/vivado_lineart/tcb705_lineart.xpr`
- 比特流及 HWH：`hw/vivado_lineart/export/tcb705_planner.bit`、`.hwh`
- XSA：`hw/vivado_lineart/export/tcb705_md0700r.xsa`
- 时序/资源/DRC/CDC 报告：`hw/vivado_lineart/export/`
- 可部署平台：`overlay/tcb705_lineart/platform.json`
- 验证数据及 SHA-256：`hw/reports/lineart/acceptance.json`
- 复现、部署及回滚：`docs/线稿PL加速实施说明.md`

文件名称保留原平台命名，但本目录的 bit/hwh/xsa 已包含新增线稿 IP；不可与旧目录同名文件混用。

完整 Vivado 工程归档建议解压至短英文路径（例如 `C:/fpga_build/lineart`），避免 Windows 260 字符路径限制。

## 板端验收（2026-10-20，ZYNQ7020 实机）

### 部署与启动

- 板端版本目录：`/home/xilinx/tcb705_releases/20261020_lineart_r1/ZYNQArm`（`/home/xilinx/ZYNQArm` 指向此处）。旧版本及回滚备份：`/home/xilinx/tcb705_deploy_backups/20261020_lineart_r1`。
- 新 FPGA 通过**启动配置切换 + 重启**加载（未在 GE_PL 驱动绑定时热下载），版本 `tcb705_lineart_20261020_r1`，比特流 SHA-256 `5dd9af8e…a683a4`。
- 七轴规划核与线稿细化核启动自检通过；平台状态 `faulted=false`，规划核时钟 76.92 MHz，线稿核 100 MHz、8 级、最大 1536×1536。
- 标定未变（`calibration_sha256 a3e87418…`）。部署后配置唯一变化是同日另一项工作新增的 `execution.sdk`（华成 SDK 运动控制）和其后的控制器网页端口 8010→80，其余字段与部署前一致。

### 板端回归

- 基础软件回归：**244 项全部通过**（18 个测试集，`build/tcb705/verification_lineart_board/report.json`）。这是在初始化优化补丁之前跑的完整回归。
- 初始化优化补丁（见下）之后**没有重新完整跑 250 项**；只做了专项复测：新增 `tests/test_lineart_attachment.py` 6 项、相关回归 34 项、14 张图库再次对比，全部通过。完整回归脚本已经加入新增测试，下次全量运行时会一并执行。

### 14 张真实图库：PL 结果与原 CPU 算法逐项一致

`tools/verify_lineart_gallery.py --pl`（强制使用 PL，并与原 CPU 算法对照）：14 张图的细化位图、最终笔画、顺序和路径哈希**全部一致**（`exact=true`）。

### 初始化优化补丁（lineart_metadata_cache_patch1）

首轮实测发现：每张图都要重新解析硬件描述（HWH），每张额外多 6～7 秒，导致“加速”后的完整提取（10.1～19.3 秒）反而比 CPU 慢。补丁内容：

- `lineart_backend.py`：同一进程内复用已验证的硬件描述。每次调用仍重新校验平台文件哈希、启动凭证和硬件占用租约，DMA 缓冲区和租约不缓存。
- `tcb705/workbench.py`：服务启动时调用 `prepare()` 预热（不下载比特流，不启动硬件操作）。服务日志已确认 `LINEART_ATTACH_PREPARE {'ready': True, …}`。
- 新增 `tests/test_lineart_attachment.py`。

补丁后第二轮 14 张图（`gallery_pl_patch1.json`）：

| 指标 | 原 CPU 算法 | PL 细化 + ARM C++ 追踪 |
|---|---:|---:|
| 完整线稿提取，最短 | 2.12 s | 0.63 s |
| 完整线稿提取，中位数 | 5.88 s | 1.14 s |
| 完整线稿提取，最长 | 12.84 s | 4.82 s |
| 单图加速比，中位数 | — | 约 3.4 倍 |

说明：

- 这里只计**线稿提取**，不含云端生图、七轴轨迹规划和实际绘画。
- 第二轮部分样本测试时显示服务没有运行，所以这组数字只作初步结果。
- 进程内首次附着硬件描述约 9.3 秒（`attachment_prepare`），之后的调用复用缓存。

### 显示正常时的代表图片复测

ACTIVE_GUI_RESULT

### 显示、触摸与网口

- 软件补丁重启后（05:05）`so101-md0700r`、`so101-gt911`、`tcb705-ui` 均为 active，未重启过。`/run/so101-lcd/status.json` 为 `RUNNING`、`hardware_frames_verified=true`，构建号与新比特流一致；`touch.json` 为 `RUNNING`，并记录到实际按压。
- 从 X 帧缓冲直接截取的当前画面（`build/tcb705/deployment/lineart_screen_now.png`）显示界面正常刷新，可以正常选图、规划和开始绘画。
- GE_PL：只验证了驱动初始化，最后一次检查时链路为 down。**PL 网口与机械臂的通信尚未验收。**
- 机械臂控制器当前经板子 `eth1` 连接（2026-10-20 已用其完成实机绘画，见 `docs/TCB705_SDK运动控制_20261020.md`），这与线稿 PL 加速是两项独立的工作。

### 仍需注意

- 方案中“约 1 秒”的目标：简单图已达到（0.6～1.1 秒）；笔画多的图仍需 2～5 秒，主要耗时在 Python 的由外向内排序和平滑。
- 用户界面里的线稿提取在显示服务进程中执行，它不共享工作台进程的预热。2026-10-20 05:16 一张人像的界面提取记录为 45.5 秒：其中 PL 细化只用了 0.21 秒，其余时间花在首次附着和 Python 后处理上。这一点需要单独优化：显示进程启动时也做预热，并把排序和平滑改成原生代码。
