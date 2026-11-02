# R1a：SO-101 名义模型与 Z20 加权单步参照

> 2026-09-24 后续版本：四项 review 修复和 R1b 主机轨迹原型见 [R1AB_USAGE.md](R1AB_USAGE.md)。当前合同 `r1ab-wls-axis-v2`；核的法方程组装使用 double、Cholesky/接口仍 float32。完整入口改为脚本 11（09 已转发），最新结果是 `reports/latest_r1ab.json`。下文保留初版设计说明，初版 534 向量结果不能替代新验收。

这是按 SOP 第 1 阶段实现的主机数值基线，不是可直接驱动机械臂的绘画程序。Python 完成名义 FK/J、位置+笔轴任务、有界迭代；C++ 提供可送 HLS 的 5×5 WLS Cholesky 单步核。真实结果以运行后生成的 `ACCEPTANCE.md` 为准。

## 使用

在 PowerShell Core 执行：

```powershell
& 'D:\SO101_Z20_Lab\scripts\09_verify_r1a.ps1'
& 'D:\SO101_Z20_Lab\scripts\10_r1a_hls.ps1' -Stage prepare
```

第一条冻结源码副本，运行 Python 测试、生成配对数据、执行 Python IK 和 MSVC C++ 数值门禁、保存所有失败。成功应输出 `R1A_HOST_GATE_PASS`，最新结果入口是 `D:\SO101_Z20_Lab\reports\latest_r1a.json`。每次运行另建目录，历史结果不会覆盖。

第二条只从通过哈希核验的源码和同一份向量准备 HLS 工程，应输出 `R1A_HLS_PREPARED_NOT_SIMULATED`，不代表仿真已完成。具备经核对版本的工具后，传入实际 launcher 的完整路径：

```powershell
# 以下 ToolExe 是占位；必须替换成实际安装路径。
& 'D:\SO101_Z20_Lab\scripts\10_r1a_hls.ps1' -Stage csim -ToolExe 'D:\AMD\<version>\...\vitis_hls.bat'
```

之后的 `csynth`、`cosim`、`export` 依次包含前序阶段。脚本不会安装 AMD 工具，也不会生成或下载 Z20 overlay；工具返回 0 仍要检查本轮报告、测试结果和导出接口。

单独在本目录试算（纯软件，无串口）：

```python
import json
from r1a.model import Model
from r1a.solve import solve
model = Model.load('config/nominal_so101.json')
cfg = json.load(open('config/contract.json'))
q_target = [0.2, -0.3, 0.5, -0.2, 0.1]
pose, _ = model.evaluate(q_target)  # 仅用于生成这个演示目标。
result = solve(model, pose[:3, 3], pose[:3, :3] @ model.tool_axis,
               [0.1, -0.2, 0.4, -0.1, 0], cfg)
print(result.status, result.q_solution)
```

只有 `status == 'OK'` 才存在 `q_solution`。`q_last` 是诊断状态，失败时不能当作有效结果使用。即使数值 `OK` 也没有运动授权或轨迹认证。

## 架构和本轮改变

```mermaid
flowchart LR
  T[目标笔尖 XYZ + 单位笔轴方向] --> P[Python: FK / 任务误差 / 雅可比]
  P --> R[Python float64 WLS 参照]
  P --> C[C++ float32 Cholesky 单步核]
  R --> B[有界迭代 / 限位 / 位置与倾角分别验收]
  C -. 后续 HLS 后端集成 .-> B
  V[冻结输入 + 独立 SVD 参考] --> C
  V --> R
```

已实现的是 Python 完整迭代和 C++ 单步配对门禁。C++ 尚未接入 Python 完整迭代，PL 路径尚未综合。后续 PS 仍负责路径标定、轨迹状态机和串口，PL 只计算，不直接连 USB BusLinker。

1. 修正上游非单位权重只作用于右端的行为，明确 W 和 mu 的含义。它是正确性修复，不是首创算法。
2. 用位置+笔轴方向任务代替任意六维位姿；位置、倾角分别验收，不能靠降低权重假成功。
3. 冻结模型、初值、目标、异常输入和阈值，在同口径下比较 Python/C++，失败输出无效、所有迭代有界并检查限位。

解析雅可比、Cholesky、热启动已有成熟先例。轨迹恢复、整次 IK 下沉、批量提交仍是后续可测方向，本轮不宣称已实现或有加速收益。

## 数学合同

所有位置用 m，关节用 rad。`config/contract.json` 是本轮运行配置：

```text
es = S e, Js = S J
min 0.5*(es - Js*dq)' W (es - Js*dq) + 0.5*mu*dq'dq
(Js' W Js + mu I)dq = Js' W es
W >= 0, S > 0, mu > 0
```

W 输入是对角元素，不能再次平方；mu 是直接正则项，不能再次平方。`rhs_only` 使用未加权左端、加权右端，仅用于消融；S=1 时对照上游原始单步公式。它不等于完整 R0 HLS/迭代复现。

笔轴误差为 `n_target - n(q)`，雅可比下三行为 `-skew(n) J_angular`；三行方向误差只有两个独立约束。夹角由 `atan2(norm(cross), dot)` 计算。相反方向可能停滞，所以单独保留反向测试；没有靠残差变小替代物理验收。

默认工具偏移为零、笔轴为局部 +X，这是显式仿真假设。该轴与第 5 轴重合，当前任务一般只有秩 4，滚转不影响笔尖或笔轴；不能保证任意 XYZ+方向可达。更改真实笔夹方向、长度后，需新模型 ID、工具标定和完整门禁，不能悄悄改假设。

成功门槛为仿真位置 <= 0.1 mm、倾角 <= 5°。这不是实物精度承诺；真实限位、舵机零位/方向、工具和纸面坐标均待标定。

## 可复现与边界

每轮 `source/` 保存执行源码，`vectors.json/txt` 保存 512 个正常配对向量和插入的异常/重入调用；输入先量化成 float32，再用 float64 SVD/直接法形成参考。随机种子固定且写入数据集。288 个 IK 目标使用独立的目标/初值随机源：256 个名义 FK 目标、32 个独立笛卡尔目标；每例两种加权公式共用其余条件。

`STAGNATION`、`LIMIT_STALL`、`MAX_ITER` 都是不成功；搜索失败不构成不可达证明。只有输出是否有效、阈值与边界等确定性质是本轮自动门禁，IK 成功率是实测描述，不是预先保证。

原始日志、逐例结果、哈希、工具版本和数值指标由验收脚本输出。这里不会把 MSVC 执行称为 HLS C 仿真，不会把 x86 时间称为 ARM/FPGA 延迟。

## 资源与接口

C++ 使用固定 6×5/5×5 小数组、串行 Cholesky 与 float32；无外部动态内存或完整 IK 的三角函数。架构避免先复制多个昂贵浮点核，适合先在 220 DSP、53,200 LUT、106,400 FF、140 BRAM36 的 Zynq-7020 上测资源，再决定复用/并行度。是否装得下、II、Latency、DSP/LUT/FF/BRAM 和 10 ns 时序是否达到均 **待测**，当前不填估计为实测。

HLS 接口选择同一 `control` bundle 的 AXI-Lite 数组/标量。J[30]、e[6]、W[6]、S[6]、mu 和 mode 共 50 个 32 位输入（200 B）；输出 dq[5] 20 B、整数返回状态 4 B，另有控制协议开销。不得推断每次实际总线传输次数或耗时。地址和数组布局以本轮生成的 IP driver/header、component.xml/HWH 为准，尚无板端驱动或硬编码偏移。

输入 0/1 模式分别是 WLS/旧公式消融；返回 0=OK、1=非法输入、2=数值故障。每次开始清零输出，成功才发布完整结果。PS 后续应依顺序写全部输入、启动、等待带超时的完成、读状态再读 dq；结果带上软件请求 ID，禁止使用超时/失败或上一请求的数据。

下一阶段优先 R1b（首点进入、连续线条/圆弧、热启动、恢复和逐点轨迹验收），其后才按同一合同做 HLS 与 Z20 集成。真实运动仍需 PING、位置读取、限位核对、单关节小范围和短直线逐级验证。

来源：[上游固定提交](https://github.com/E1pco/Hardware-Accelerated_System_for_IK_Solution_Based_on_LeRobot/tree/ab4207c87a4317d835adb914ca9e4db7948e6aa3)。文件级登记在实验根目录 `references/UPSTREAM_REFERENCE_20260924.md`；原始参考文件和声明保持不变。
