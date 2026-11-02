# 线稿提取 PL 加速（2026-10-20）

对应桌面的《线稿提取进PL_规划与可行性_20261020.docx》第一阶段。输入仍为原系统产生的二值线稿；将 Zhang–Suen 细化放到 PL，将像素图追踪和距离检查的热点移到 ARM 原生 C++。图像阈值、实际笔画几何、顺序、尺寸、机械臂标定、运动控制接口保持现有行为。第二阶段的摄像头、灰度滤波和阈值硬件化尚未实施。

## 硬件实现

- 独立工程：`hw/vivado_lineart/tcb705_lineart.xpr`，器件 `xc7z020clg400-2`，Vivado 2024.2。
- 在已验证的七轴规划、MD0700R、GT911、GE_PL 平台上增加 `tcb_lineart_accel_0`。
- 时钟 FCLK0 100 MHz；控制地址 `0x40010000`、64 KiB；DDR 经 HP2。原显示 HP0、规划 HP1 保留。
- 采用方案允许的 **8 级 A/B 交替流水**，每次调用相当于 4 轮 Zhang–Suen。PS 交换两个 DDR 缓冲区，直到整个调用没有删点。选择 8 级是为了给原平台和布局布线保留资源，不能将单次调用等同于完整收敛。
- 维度支持 1～1536，包含非 64 整数宽度。连续行优先、每像素 1 bit、每 64 bit 一个字、低位先行，尾部补零；不在每行末额外对齐。
- HLS 逐级保留两行像素，按零填充边界计算；输出 `deleted` 为布尔变化标志，不是删点数量。返回值 0 成功，1 维度非法；非法维度不访问 DDR。
- identity 为 `0x4c410108`。DDR 读写指针为 64 位寄存器，当前 ZYNQ 使用低于 4 GiB 的 CMA 地址。

实际寄存器偏移由 HLS 驱动头文件提取，不能从旧 IP 抄地址：

|字段|偏移|宽度|
|---|---:|---:|
|AP 控制|0x00|32|
|返回值|0x10|32|
|src|0x18|64|
|dst|0x24|64|
|width|0x30|32|
|height|0x38|32|
|deleted|0x40|32|
|identity|0x50|32|

## 软件接入

`stroke_paths.thin()` 自动选择 `lineart_backend.py`；原算法保留为 `_thin_cpu()`。PYNQ 仅附着已经启动验证的硬件，不在每张图处理时下载比特流。平台清单绑定 bit、hwh、寄存器映射和 SHA-256；启动期间先进行规划 IP 自检，再进行线稿 IP 自检，全部成功才发布本次启动凭证。

使用独立进程锁串行化同一线稿 IP。输入写入后 flush，硬件写入的结果 invalidate 后再读取。AXI 超时保留缓冲区和占用记录，停止再次访问该 IP；自动模式退回 CPU。此时应安排重启恢复，不能通过释放仍可能被 DMA 使用的缓冲区来强行重试。

`native/lineart.cpp` 提供像素图追踪和几何距离检查，并保留 Python 实现用于回退和差分验证。OpenCV 简化、NumPy 重采样及原先的平滑/外到内排序继续复用，未更改笔画美化规则。C++ 标量细化仅供对照测试，当前 CPU 回退仍使用原 Python/OpenCV 细化。

可选环境变量：

|变量|取值|用途|
|---|---|---|
|TCB705_LINEART|auto（默认）|PL 可用则用 PL，否则保留原因并回退 CPU|
|TCB705_LINEART|cpu|强制原 CPU 细化|
|TCB705_LINEART|pl|严格 PL，任何异常直接报告，用于验收|
|TCB705_NATIVE_LINEART|auto（默认）/ off|启用或关闭原生图追踪和距离检查|

结果中的 `extraction.thinning` 记录使用的后端、循环次数和时间。没有启动新平台时显示 CPU 是正常回退，不能据此宣称硬件已经加速。完整路径 SHA-256 不包含耗时元数据。

## 复现构建

在项目根目录执行，工具安装路径见脚本；现有工程和 IP 文件不会被脚本静默覆盖。

```powershell
& scripts/build_lineart_hls.ps1 -Stage csim
& scripts/build_lineart_hls.ps1 -Stage synthesis
& scripts/build_lineart_hls.ps1 -Stage cosim
& scripts/build_lineart_hls.ps1 -Stage package
& scripts/build_lineart_vivado.ps1 -Stage all
```

已有工程可使用 `-Stage build`。`create_lineart.tcl` 依赖工程内保留的已验证 GE_PL BD 重建脚本及显示/规划 IP 仓库。完整可移植归档另通过 Vivado `archive_project` 生成。Vivado 构建结束后必须检查 `export/build_verified.json`，仅有 `.xpr` 或 HLS 综合报告不代表成功生成可用硬件。

Windows 上建议把完整 Vivado 归档解压到短英文目录，例如 `C:/fpga_build/lineart`。归档脚本使用独立短临时目录，避免原规划 IP 的长文件名触发 Windows 260 字符路径限制。

ARM 原生库在板子上编译：

```sh
.venv/bin/python scripts/build_tcb705.py --sdk
.venv/bin/python scripts/verify_tcb705.py --output build/tcb705/verification_lineart_board
```

## 验证与验收

已执行的桌面验证：完整相关回归 244 项通过、无跳过；14 张真实图库的细化位图、图追踪结果、最终笔画、顺序和路径哈希均与原实现一致。最终 8 级 HLS C 仿真 25 组输入通过，包括 14 张完整尺寸图库以及维度/边界样本。C/RTL 联合仿真通过 10 组输入（含 3 张真实图库的 96×96 样本、1536 最大宽/高、空图及连续 10 轮处理）及非法尺寸保护。小图 RTL 仿真不能替代完整尺寸上板验收。

板端应执行 `tools/verify_lineart_gallery.py --images <图库> --output <报告> --pl`，强制实际 PL 与原 CPU 对照，并记录完整线稿处理用时；脚本不发机械臂指令。还应确认显示、触摸、七轴 IP 自检和 GE_PL 驱动可用。机械臂/网线未接时只能验证网口设备初始化，不能声称控制器通信验收通过。

方案中的约 1 秒是目标，不能用 HLS 时钟频率推导完整业务耗时。报告需区分：PL 核运行、CMA/初始化开销、追踪与平滑、完整线稿提取；云端生图和七轴运动规划时间单独计算。最终 FPGA 时序、资源与上板实测见同目录的构建验收报告。

## 部署与回滚

`deploy/tcb705/lineart/stage.sh` 在独立版本目录解包、验源文件哈希、编译 ARM 库、跑离线回归、检查平台清单。

`select_boot.py` 检查没有活动绘画任务，备份当前服务启动参数及平台选择，仅改变下一次启动选项。保留现有命令参数、纸面/工具标定和网络配置；不改机器人配置。必须通过正常重启加载新 FPGA，不能在 GE_PL 驱动已绑定时热重载。

`rollback.py` 只删除本版新增的 systemd 覆盖文件，恢复原工程链接；之后重启恢复旧 FPGA。旧工程、旧比特流和旧版本目录均保留。
