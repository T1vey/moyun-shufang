# TCB705 七轴逆解并行核（R6）

目标器件 `xc7z020clg400-2`，目标主频 **100 MHz**，目标为连续绘画轨迹 **超过 100,000 个有效逆解点/秒**。本目录是独立 HLS 重构实现；原 `hls_source/tcb705`、整机 Vivado 工程与板端运行文件尚未替换。达标与否以验收说明中的 RTL 周期、布局布线结果为准。

## 新结构

```text
DDR 模型、初值、连续目标
          ↓
模型与参数检查（每批一次）
          ↓
阶段 A：SRS 解析候选
几何计算 → 三路并行 CORDIC → 最近合法分支
          ↓ 深度 2 FIFO
阶段 B：独立原模型 FK 验收
位置/姿态误差 → 限位/关节步长 → 按顺序提交
          ↓
DDR 已通过的关节解前缀
          ↓
失败点由 CPU 通用 IK 接着计算
```

阶段 A 生成下一点时，阶段 B 同时检查上一点。CORDIC 的三个通道并行求角；正解内部的 sin/cos、不同矩阵元素和 XYZ 分量也利用流水和并行算术。七级连杆、相邻轨迹冗余选解有真实依赖，未用虚假的 `DEPENDENCE false` 绕过。

R1–R5 保留迭代逆解并扩展并行度，实际 RTL 吞吐量未达标，R5 单核超出 ZYNQ7020 的 LUT 容量。R6 利用当前控制器 DH 的 SRS 结构，改为解析候选，移除实际硬件调用路径中的 Newton、正规方程和 LDLᵀ。历史源码仍保留供对照，但未被 R6 调用。

## 代码入口

| 文件 | 作用 |
|---|---|
| `tcb_planner_parallel.cpp` | AXI 接口、配置与模型检查、DATAFLOW 调用、通用 FK_ROWS |
| `parallel_srs_pipeline.hpp` | 候选生产/独立验收两阶段、FIFO、失败排空、取消和有效前缀提交 |
| `parallel_srs.hpp` | 运行时连杆参数、上一肘点投影、解析肩/肘/腕角、分支与限位 |
| `parallel_atan2.hpp` | 三通道、48 轮整数 CORDIC；FP64 输入/输出 |
| `pl_math7_parallel.hpp` | FP64 sin/cos 与原模型正解 |
| `parallel_compose_sparse.hpp` | 严格形状匹配的稀疏变换，其他形状保留通用矩阵乘法 |
| `tcb_planner_parallel.h` | ABI、作业状态和 DDR 字段 |
| `tests/controller_cases.hpp` | 历史 controller-DH 与独立 FK 验收 |
| `tests/tb_parallel_controller_throughput.cpp` | 三组连续 64 点吞吐率测试 |
| `tests/tb_parallel_srs_contract.cpp` | 失败、取消、输出边界、FIFO 排空测试 |

## 适用模型与精度

快速逆解要求运行时模型严格符合本工程保存的 SRS controller-DH：局部关节轴全为 +Z、交替 Rx±90°、指定固定连杆为局部 Z 平移、工具不含侧向偏置或旋转、关节限位在 ±π 内。长度来自输入配置，不写死纸面高度。

`robots/tcb705/profile.armvision_joint.json` 和 `build/tcb705/startup_speed_20261020/machine.json` 经当前模型转换符合此结构。记录中的长度为 0.263、0.3205、0.2795、0.1615 m；最后一项来自控制器 DH 最后一段，**不是已标定毛笔长度**，两配置的 `T_flange_tcp` 为单位阵。旧 URDF profile、不同轴方向、侧向 TCP、工具旋转或几何修正不自动获得快速路径。

- 几何与独立 FK 为 FP64；CORDIC 内部为 64 位整数、54 位小数，独立验证舍入误差。
- 原位置容差 `1e-7 m`、姿态容差 `1e-6 rad` 不变；不跳过验收、不降低精度来统计速度。
- 独立 FK 保留原模型中的 `6.123233995736766e-17` 等系数。
- 将上一肘点投影到新肘圆、保持肘弯曲符号，再选最近合法肩/腕分支并限制关节跳变。这不是全局最近七轴解，也不要求与旧 Newton 得到逐位相同的角度。
- 不支持的模型、奇异附近、不可达、越限或大跳变返回 PARTIAL，CPU 接续通用逆解。不能把快速路径宣称为所有输入都达到 10 万点/秒。

## 有效前缀、失败与取消

生产阶段可持有推测状态，外部只认验收阶段已提交结果。首个失败后锁存终止状态，后续候选只排空、不写结果。两个阶段严格交换本批 `count` 个包，避免深度 2 FIFO 因提前退出而死锁。

失败行 status=1，后续输出保持原值，成功前缀保留。取消在 FK 前和提交前检查；解析迭代数为 0 不等于跳过 FK。失败行有限零残差只与失败状态一起解释，不能算有效点。

配套 `tcb705/planning_batches.py` 修复部分返回与整批目标长度不匹配的问题，只核验返回前缀；从首失败点、最后一个已验收关节解继续。CANCELLED 不触发 CPU 回退。`tests/test_tcb_partial_prefix.py` 覆盖前缀及取消竞态。

## 构建与复现

在项目根目录用 PowerShell；本机 Vitis/Vivado 2024.2，输出使用 ASCII 路径。

```powershell
./scripts/build_tcb705_parallel_hls.ps1 -BuildDirectory C:\fpga_build\tcb705_parallel_r6_20261024 -Profile controller -Stage csim
./scripts/build_tcb705_parallel_hls.ps1 -BuildDirectory C:\fpga_build\tcb705_parallel_r6_20261024 -Profile controller_throughput -Stage all
./scripts/build_tcb705_parallel_hls.ps1 -BuildDirectory C:\fpga_build\tcb705_parallel_r6_contract_20261024 -Profile contract -Stage all
./scripts/validate_tcb705_parallel_ooc.ps1 -SynthesisRoot C:\fpga_build\tcb705_parallel_r6_20261024\hls_controller_throughput -OutDirectory C:\fpga_build\tcb705_parallel_r6_ooc_20261024
```

`controller` 为 352 点功能回归。`controller_throughput` 为合成直线、历史前段、历史 DRAW 的三组连续 64 点。历史模型/节点附 SHA256，不是本轮实机运动证据。旧 `throughput` 使用不同 URDF 模型，其快速失败不能统计成 R6 逆解性能。

脚本保存综合源文件指纹，协同仿真与打包拒绝不同源码对应的旧 RTL。OOC 在独立 Vivado 工程中，于综合前加载 100 MHz 时钟约束，生成真实浮点 IP，综合、布局布线并输出资源/时序/DCP。

## 验收口径与当前范围

1. 所有计入吞吐量的结果通过独立 FK 原容差检查。
2. 100 MHz 下，64 个有效点的完整 AXI 事务少于 64,000 周期；计入配置、输入和结果访问。
3. 实际布局布线 WNS≥0、TNS=0 且保持时序通过；HLS 估计不代表最终时序。
4. OOC 只覆盖独立核内部路径；LCD、视觉、触摸、第二网口共存的整机还需集成、布局布线及上板验证。
5. 核吞吐量不包含 Python/PYNQ 管理、整图 CPU 检查和真实 DDR 竞争，整幅图规划时间需要另测。
6. 生产驱动仍校验旧 IP 名与 75–80 MHz；新顶层、100 MHz、HWH 和驱动需在整机集成时一起更新。

证据保存于 `build/tcb705/parallel_20261024/`。最终数值以该目录验收说明为准，本 README 不将目标写成已完成值。

