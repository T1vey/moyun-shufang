# R1a 修复与 R1b 连续绘画原型

范围：纯主机、名义 SO-101、离线规划。任何输出均 `physical_authorized=false`；没有串口/USB/电机指令执行功能。

## 快速使用

PowerShell Core 下完整重验：

```powershell
& 'D:\SO101_Z20_Lab\scripts\11_verify_r1ab.ps1'
& 'D:\SO101_Z20_Lab\scripts\10_r1a_hls.ps1' -Stage prepare
```

预期：第一条结束时 `R1AB_HOST_GATE_PASS`、`R1AB_EVIDENCE_VERIFIED`，最新运行在 `reports/latest_r1ab.json`；第二条 `PREPARED_NOT_SIMULATED`，不产生实测 FPGA 资源或时序。原 09 入口现转发到新门禁，历史 04/05/06 仍只测旧快照。

使用 Python 生成示例路径：

```powershell
Set-Location 'D:\SO101_Z20_Lab\work\r1a_20260924'
& 'D:\SO101_Z20_Lab\envs\host\Scripts\python.exe' -B -m r1b.cli --demo circle --out 'D:\SO101_Z20_Lab\releases\my_circle'
```

`--demo` 可选 `line`、`circle`、`two-strokes`。输出目录必须不存在；生成 `drawing.json`、`plan.json` 和 `preview.svg`。`OK` 只表示该名义模型的离线检查通过。失败时退出码 2，`commands=null`，保留诊断，不能拿部分轨迹继续执行。

使用经过本轮验收的 C++ DLL 后端：

```powershell
$run = (Get-Content 'D:\SO101_Z20_Lab\reports\latest_r1ab.json' -Raw | ConvertFrom-Json).run
Set-Location (Join-Path $run 'source')
& 'D:\SO101_Z20_Lab\envs\host\Scripts\python.exe' -B -m r1b.cli --demo two-strokes --validated-run $run --out 'D:\SO101_Z20_Lab\releases\my_cpp_drawing'
```

代码、模型和配置必须与受测运行一致；改变工作目录源码后不能继续借用旧运行的 DLL 验收。`--input` 可替换 `--demo`，读与生成的 `drawing.json` 相同结构。输入需声明 `units=m_rad`、纸面原点/单位法向、单位笔轴、独立初始关节 `q0` 和 strokes 列表。每笔 segments 只支持 line(start_m/end_m)、arc(center_m/u/v/radius_m/start_rad/sweep_rad)。不同笔画用 strokes 分开，同一笔画不允许断点。尚未接入 ArmVision 私有格式，需先明确它的单位、坐标和抬落笔语义。

## 架构

```text
SI 线/圆弧 + 名义纸面/笔轴 + 独立 q0
  → 按步距/弦高采样 → APPROACH / LOWER / DRAW / LIFT / TRAVEL
  → 前一有效解热启动的有界 IK
       Python: float32 输入 + float64 WLS
       C++ DLL: float32 输入/输出 + double 组装 + float Cholesky
  → 有限重试；每目标预算相同；失败后整批无效
  → 五次关节插值 + 关节/笛卡尔/倾角检查 + 速度/加速度解析上界
  → 仅仿真 plan.json / preview.svg
```

未来部署仍由 PS/Linux 负责路径、标定、安全状态机和总线，PL 仅是可选计算后端。主机 DLL 不是 FPGA，未提供可直接下载 bit/hwh。

## 四项修复如何验证

| 问题 | 修复 | 证据 |
|---|---|---|
| 改源码后用旧日志重新 PASS | 测前 inputs.json，逐阶段 receipt 链，报告只验证且拒绝覆盖；HLS 入口拒绝旧协议 | 修改源码/日志/缺失阶段/更换目录等负面测试 |
| NaN 参考被当成零误差 | 独立检查参考与所有容差有限性，显式错误处理 | 8 个损坏参考/容差用例必须 HARNESS_ERROR，退出码 2 |
| 成功被停滞覆盖/终态漏记 | 接受候选后下一循环先记录并判断成功，再检查停滞 | 审查 t214 参数变体和末次迭代达标回归 |
| 实际 IK 抵消误差遗漏 | double 组装法方程，保留 float32 分解/接口，保留原阈值 | 旧 534 + 旧审查 1,728 + 本轮真实迭代输入；完整 DLL IK 配对 |

输入冻结和 receipt 链防止无意版本混用，不能防止文件所有者恶意重写整个证据链；不称为数字签名。报告不会根据手动放进去的 PASS 字符串给未测源码发证。

## R1b 的设计边界

- 位置/方向/限位继续分别验收；笔轴默认 +X、端点为上游名义法兰，任务秩限制保持公开。
- 首点沿当前名义姿态到上方进场点分段求解；这不是真实读回姿态或碰撞规避。
- 跟踪使用前一有效解；恢复只改变数值初值，接受结果还要从原姿态检查连接段，禁止将随机初值当作可执行姿态。
- 基线每目标最多 120 次迭代；恢复最多 3×40。NUMERIC/INVALID_INPUT 不重试；取消、无解、插值误差、命令预算等都令整条轨迹失效。
- 轨迹采用逐段五次平滑启停。每段端点速度与加速度为零，可在尖角停顿，速度并非常量。最大关节速度为 `1.875×|dq|/T`，最大加速度为 `(10/√3)×|dq|/T²`。
- 几何检查覆盖每个发令采样时刻及额外分段点；这不是连续笛卡尔误差的形式证明，也没有机身/桌面/障碍物碰撞检测。
- 当前纸面/笔尖/限位是名义仿真设置，不能由小范围样本推出 A4 工作区或实物精度。

## 资源与后续

double 法方程组装提高了数值稳健性，但会改变 Zynq-7020 的 DSP/LUT/FF 与时序需求。使用固定小数组、未主动复制多核；资源占用、II、Latency、Fmax 全部待综合。若资源不足，后续应比较受控缩放/补偿累加/混合精度，不靠放宽测试掩盖错误。

本轮可报告的是正确性、可复现性和轨迹策略实现，不是首创 Cholesky/热启动，也不是已测加速。自然样本全部无需恢复时，只能说明恢复逻辑经故障注入验证，不能宣称成功率提高。

下一步是指定版本 AMD C 仿真→综合→RTL 联仿→Z20 专用 IP/overlay；同时进行真实工具、纸面和关节标定。实物运动仍须 PING、位置读取、限位核对、单关节小范围和短直线逐级验证。
