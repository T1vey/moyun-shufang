# 完整目标 IK：Vivado 2024.2 交付说明

日期：2026-10-03。工具版本为 **Vivado / Vitis HLS 2024.2**，器件为 `xc7z020clg400-2`。PS7 已按用户提供的正点原子 Z20 核心板原理图和厂家 PYNQ 工程核对：MIO Bank 0 为 3.3V、Bank 1 为 1.8V；DDR 为两颗 x16 芯片组成的 32 位总线。新设计只有 PS7、AXI 互连、复位、完整目标 IK 核；舵机串口仍通过现有软件通道，不增加外部 PL 引脚。

## 1. 直接打开工程

已实际创建的工程：

`C:\fpga_build\so101_target_2024_1003\vivado\so101_target_ik.xpr`

用 **Vivado 2024.2** 打开，依次运行 Run Synthesis、Run Implementation、Generate Bitstream。工程创建脚本不启动这些步骤，也不烧录。

HLS 的 RTL 生成已经用于准备 IP，它与完整 Vivado 工程的布局布线是不同步骤。HLS 估计不能代替最终资源与时序。最终要检查实现后的 WNS/TNS、保持时间和 DRC。

生成 bitstream 后，在 Vivado Tcl Console 执行：

```tcl
source [file normalize "[get_property DIRECTORY [current_project]]/../src/export_after_bitstream.tcl"]
```

导出目录：`C:\fpga_build\so101_target_2024_1003\export`。

需要配套使用：

- `drawing_target.bit`：你编译生成的 bitstream。
- `drawing_target.hwh`：同一次 Vivado 工程生成的硬件描述。
- `drawing_target.registers.json`：从新核的 HLS 驱动头提取的映射。

不能混用旧 `drawing_full.*` 或旧单步核的寄存器映射。新 IP 为 `z20_ik_target_0`，ABI 为 `so101-ik-target-v1`，硬件 magic 为 `0x534F0301`，地址基址为 `0x40000000`。

## 2. 修改内容

1. `hls_source/ik_target.cpp`：PL 完成一个目标的 FK、Jacobian、WLS、限位、步长限制、线搜索、停滞检查和收敛判断。初始目标与候选目标共用一个计算入口，避免复制两套 FK。单次最多 120 次迭代、32 次线搜索、32 长度停滞窗口；现有配置为每次尝试 40 次、线搜索 8 次、窗口 8。
2. `ik_target_backend.py`：每个需要求解的目标一次启动；输入常量缓存；输出最终关节角由 PS 独立 FK 检查。已验证的上一点姿态若已经满足下一目标，直接返回 0 迭代结果，避免无效 PL 启动。超时或错误 ABI 后锁定会话，要求重新加载 overlay；取消会等待当前有界求解完成，然后返回 ABORT。
3. `planner_source/r1a/model.py`、`solve.py`：延迟构造 Jacobian，使被拒线搜索候选和已收敛候选不必构造 Jacobian；保留 FK 元数据，不重复 FK。
4. `planner_source/r1b/planner.py`：连续模式不再生成随后丢弃的 rest-quintic 采样；增加目标生成、IK、段检查、插值计时和迭代分布。
5. `planning.py`：记录最终生效配置与实际 planner 路径；量化、预览、文件输出分阶段计时，完整写文件计时保存在 `timing.json`。
6. `engine.py`、`app.py`：新增 `--pl-mode target`。起始抬高姿态也可使用完整目标接口。
7. root/app 软件副本、`ik_solver/planner` 副本及现有 `planner_source/kernel` HLS 副本已经同步，避免旧启动目录加载不同实现。

PL 核当前固定五关节的 nominal 连杆偏移和关节轴；笔尖工具偏移、笔尖轴及关节限位可运行时输入。若机器配置修改了连杆长度或轴方向，需要重新生成对应核；后端会检查几何合同，不能直接套用本核。

本次沿用原有绘画速度、加速度和精度容差。配套软件修正了反馈故障时的测量语义，并明确 audit/strict 执行策略，见软件交付说明。未加入 DMA、自适应目标采样或硬件运动播放器；后续优化由板上分阶段报告决定。

## 3. 上板验证与启动

先将代码和新三件套传到板卡工程目录，三件套放在 `overlay/`。本次未自动连接板卡、上传文件、重启服务或编程设备。

先按照 [软件交付说明](DELIVERY.md) 安装环境。手动检查前停止已有绘画服务，避免同时访问 PL；在板卡工程根目录执行：

```bash
sudo systemctl stop so101-workbench.service
sudo .venv/bin/python -B scripts/check_target_overlay.py --overlay overlay/drawing_target.bit --output reports/target_board_gate.json
sudo .venv/bin/python -B scripts/benchmark_target_ik.py --backend ps --output reports/board_ps.json
sudo .venv/bin/python -B scripts/benchmark_target_ik.py --backend target --overlay overlay/drawing_target.bit --output reports/board_target.json
```

后两个命令使用相同的固定人像 paths、nominal 模型及初值，不读取/驱动舵机。加载 overlay 会配置 PL；不会驱动机械臂。

若要测试真实标定模型和计数量化，两个基准均补充同一组 `--machine config/machine实际配置.json --counts 起始计数.json`；counts 是离线保存的计数字典。新增计时数据不包含云端耗时，必须按报告 scope 判断，不能把桌面 C++ 成绩当作 PL 时延。

数值检查通过后，可恢复已安装的服务：

```bash
sudo systemctl start so101-workbench.service
```

配套部署入口是 `deploy/install_z20.sh --profile target`，Windows 上传入口为 `deploy/deploy_z20.ps1`；`deploy/enable_pl.sh` 转发到新安装入口。安装脚本自带数值检查，保留机器数据目录。完整命令见软件交付说明。

## 4. 重建 HLS IP 和 Vivado 工程

权威 HLS 源码位于项目 `hls_source/`。若更改源码，需要重新准备 IP 和工程；直接编辑 HLS C++ 不会改变 `.xpr` 已使用的 RTL IP。

在项目根目录执行（新的 ASCII 输出目录）：

```powershell
.\scripts\prepare_target_2024.ps1 -BuildDir C:\fpga_build\so101_target_rebuild -Cosim
```

默认工具路径为 `D:\Xilinx\Vitis\2024.2`、`D:\Xilinx\Vivado\2024.2`。脚本生成向量、运行 C 仿真、HLS 综合和可选 C/RTL 联合仿真、打包 IP、导出真实寄存器映射，最后创建 Vivado 工程；不会生成最终 bitstream 或烧录。输出目录已有 `.xpr` 时拒绝覆盖，请打开原工程或选择新的目录。

对应官方流程：[AMD Vitis 2024.2 CLI](https://docs.amd.com/r/2024.2-English/ug1702-vitis-accelerated-reference/Creating-HLS-Components-from-the-Command-Line)。

## 5. 测试与性能证据

- 主机 C++ 和 HLS C 仿真均运行 85 组向量，覆盖正常求解、不可达、零权重停滞、预算耗尽、非法输入和数值异常。
- 最终打包版本的 Verilog C/RTL 联合仿真 85 组全部通过。样本延迟最小 342、平均 7291、最大 61391 个周期；按目标 100MHz 折算平均约 72.91μs，仅代表这批仿真向量，不包含板上 MMIO，也不是所有输入的最大延迟保证。
- 新目标接口有 10 项测试，覆盖映射身份、寄存器尺寸、缓存、常量校准变化、标量/映射传输一致性、取消、超时锁定、错误 ABI 和伪造成功的独立 FK 检查。
- 规划器 38 项回归通过；旧单步核的 384 组独立数值向量仍通过。
- 人像 1632 个目标、1076 次 IK 迭代、5105 帧：软件优化前后命令逐项一致；完整 C++ 求解器关节轨迹最大差异约 `4.52e-7 rad`。
- 桌面主机旧 Python 基线约 1.24s，优化后的 Python 约 1.01s，完整 C++ 约 0.89s。样本、阶段和采样次数见 `reports/target_ik/`；旧基线 3 次，新基准 5 次。这只是主机规划比较，未包含真实串口运动和板上 MMIO。
- HLS 最终资源估计：6 BRAM_18K、99 DSP、27768 FF、30659 LUT；约 2%、45%、26%、57%。估计 Fmax 105.84MHz，约束目标 100MHz。仍需要你运行 Vivado 实现确认最终时序与资源。

**软件交付补齐：**第一轮记录的 5 项失败已在后续软件集成中处理：明确 audit/strict 两种执行策略、修正陈旧反馈语义，并更新已支持 `/api/home` 的旧测试预期。最新全应用 117 项测试通过，无跳过；完整输出在 `reports/target_ik/application_delivery_tests.txt`。部署、打包和 PC 网关入口见 [DELIVERY.md](DELIVERY.md)。

原始文件备份原位于 `backups/20261003_target_ik/`，已随历史材料移入工程外的整理备份（见 [工程首页](../README.md)），其中包含旧运行副本。HLS 实际状态和工程创建记录以 `reports/target_ik/DELIVERY_STATUS.json` 为准。

## 6. 第一轮板上结果如何判断

比较同一输入、初值、机器配置和精度阈值下的规划成功率、最终 FK 误差、目标数、迭代数，以及总时间的中位数。重点查看 `ik_s`、`interpolation_s`、量化检查和接口写/等/读时间。

若 target 已明显快，但插值或量化占主导，下一步优化这些阶段。若每目标启动仍占主导，再做批量 DMA。当前人像多数目标只需要 0～1 次迭代，不以“迭代上限缩小 4 倍”预测实际 4 倍加速。

当前连续插值的 FK 几何校验在原工程中已被关闭，本次没有改变该选择；报告中的零插值误差不能作为绘画精度实测证明。

## 7. 板卡参数核对依据

硬件资料位于 `D:\zhiliao\FPGA\【正点原子】Z20开发板资料盘(A盘)\3_开发板原理图和硬件相关文件`。

- `ZYNQ7010_7020核心板原理图_2V5.pdf` 第 4、7 页：Bank 500/MIO 0–15 为 3.3V，Bank 501/MIO 16–53 为 1.8V。
- 同文件第 8 页：U3/U4 为两颗 x16 DDR，数据连接覆盖 D0–D31；第 11 页明确标注核心板 PS 以太网 RGMII 为 1.8V。底板另一个 PL 以太网接口的 3.3V 不适用于这里。
- 厂家资料盘 `5_PYNQ_Design/ZYNQ_7020_PYNQ/7_ov5640_rgb2gray/vivado/ov5640_rgb2gray/ov5640_rgb2gray.srcs/sources_1/bd/base/hw_handoff/base_bd.tcl` 提供匹配的 32 位 DDR 参数、4Gbit/x16 器件预设、533.333MHz DDR 时钟、1GB 地址范围、UART/SD/QSPI/USB/以太网 MIO 分配。

因此修正了旧工程中 Bank 1 全部设为 3.3V、DDR 设为 16 位/x8 的不匹配，并按厂家配置将 MIO 9 用于 USB 复位，PS 以太网不用此引脚复位。修正后的源码是 `hw/target_ik/ps7_board.tcl`；差异和来源哈希保存在 `reports/target_ik/board/ps7_reconciliation.json`。不修改厂家资料原文件。

修正已应用到上面的实际 `.xpr`，Vivado 2024.2 Block Design 校验和输出生成通过，原有 `[PS7-6] RGMII 3.3V` 警告已消除。生成的顶层 DDR 数据总线为 32 位、DQS 为 4 对；日志保存在 `reports/target_ik/vivado_board_refresh.log`。

此工程按 PYNQ Linux overlay 使用。使用现有正常启动的厂家 PYNQ 系统，加载新的 bit/hwh；无需为本次 PL 加速器另做 BOOT.bin 或烧写启动 Flash。

**交付边界：**`.xpr` 和 IP 已生成，数值仿真与接口检查已执行；完整 Vivado 综合、布局布线、最终 bitstream、板上精度与加速倍数由后续编译和上板验证确认。
