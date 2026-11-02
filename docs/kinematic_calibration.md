# 多点运动学标定与舵机辨识

当前使用方式（2026-10-13）：用户选择暂时沿用原标定，板端启用1.10.1版既有标定兼容路径，因此以下多点采样暂不作为使用前提。新方案的速度优化与协调抬笔保持启用；原标定精度未被重新验证。等方便时再按本文采样，应用新的多点结果会自动退出旧标定兼容路径。

对应《机械臂糖画_画画速度与质量优化方案》的 Q1、Q2、Q4、V3。完整的软件行为、基准和物理待办见 [新方案实施说明](NEW_SUGAR_SCHEME.md)。本文件的离线模块和 CLI 只处理已保存数据，不打开串口、不自动移动机械臂、不覆盖正在使用的 machine.json。设置界面的采集向导会读取实机编码器；只有用户点击“应用标定结果”并确认后才保存配置。

2026-10-13 状态：求解和异常拒绝已做数值测试，真实27姿态、舵机单位/负载/时延及新版本实物绘画验收仍需采集。示例数据和离线预测不代表这些实物项目已完成。

## 先完成真实接触采样

1. 底座调平，固定笔座及纸张。用尺量腕部模型原点到笔尖的轴向长度作为初值；此算法假设笔尖在 `L * tool_axis_local` 上，不同时拟合横向安装偏移。
2. 在纸上布置 3×3 网格，100 mm 边长的格点为 x/y 各 −50、0、50 mm。9 点覆盖 100×100 mm；如要覆盖画框之外，增大模板边长，并先确认机械臂可达。
3. 每点人工轻触三次：竖直、前倾约 10–20°、后倾约 10–20°。记录真实静止编码器读数，不能用目标计数或 FK 生成值替代。每点至少三个采样、pitch 变化至少 5°；9 点至少 27 组。
4. 建议另采集中心之外至少四处独立点，标为 `split: validation`。不能复制训练读数；没有独立点时输出 `PENDING`，不伪称验证通过。
5. 拟合通过后应用待审配置，再重新完成四点标定及轻触检查。旧四点数据与改变后的零位/TCP 不兼容，程序会清除。四点残差建议 ≤2 mm；新糖画执行门控拒绝 >5 mm。

界面入口为设置/调试页的“多点零位与笔长标定”。选取采样项、手动摆放并确认轻触后点“记录当前位置”；可以导入/导出草稿，全部采好后点“拟合与检查”。真实 ACCEPT 才能点“应用标定结果”。应用后重新四点，之前的预测和运动计划必须重新生成。界面不会自动完成27次接触，模型/零位在采集中变化时需要重新采集。

## 文件格式与命令

```powershell
python scripts/kinematic_calibration.py template --side-mm 100 --output captures.json
python scripts/kinematic_calibration.py fit --machine machine.json --captures captures.json --report fit-report.json --candidate machine.calibration-candidate.json
```

`template` 生成 27 行、编码器值为 null 的模板。必须用真实采样替换 null。根对象格式如下，示意计数不代表已测量：

```json
{
  "schema": "so101-kinematic-captures-v1",
  "source": "measured",
  "initial_pen_length_mm": 95,
  "captures": [
    {
      "counts": {"1": null, "2": null, "3": null, "4": null, "5": null},
      "xy_mm": [-50, -50],
      "pose_label": "vertical",
      "split": "fit"
    }
  ]
}
```

界面或采集器接入以下纯函数：

- `capture_template(side_mm=100)`：得到空采集表。
- `fit_calibration(machine, dataset)`：返回完整 ACCEPT/REJECT 报告，不改输入。
- `make_candidate(machine, dataset, report=None)`：仅真实测量 ACCEPT 生成新配置副本。更改 ID2/3/4 整数零位、轴向 TCP 与刚性纸面；清旧四点、落笔补偿置零、`checks.kinematics=false`，等待重新四点与实物确认。
- `validate_acceptance(machine)`：检查真实标定、配置指纹和全部拟合残差；没有独立点仍允许标定 ACCEPT，但保留 PENDING。
- `assert_sugar_calibration(machine, require_four_point=True)`：再检查四点配置及超差限制；不是机械运动的全部检查替代品。
- `fit_pen_axis(machine, captures)`：可选，用至少 3 个外部水平仪确认竖直的姿态估计笔轴。每项必须声明 `source: measured`、`externally_vertical_confirmed: true` 和完整 counts；误差须 ≤0.5°。改变笔轴后必须重新 Q1/Q2，不可直接继续旧计划。

## 求解与验收含义

求解参数为三个关节加性角度修正、笔长、纸面平移三维和旋转三维，共 10 项。固定 ID1（与纸面 yaw 规约）和 ID5 零位。模型定义为：

`q_i = direction_i * (count_i - zero_count_i) * 2π / 4096`

拟合得到 `delta_q_i` 后：

`zero_new_i = round(zero_old_i - direction_i * delta_q_i / (2π/4096))`

因此不同舵机 direction 的符号不同，不能统一把角度修正直接加到零位。拟合的连续零位和写入配置的整数零位均重新计算残差。

- 使用 Numpy 批量 FK 与有界、多初值 Levenberg–Marquardt，不依赖 SciPy。
- ID2/3/4 修正界限 ±15°，笔长 0–200 mm，纸面平移相对初值 ±200 mm，旋转向量各轴 ±30°。
- 保留所有点，不通过丢弃坏点掩盖超差；任一拟合/独立验证点误差超过 1.5 mm，即 REJECT。
- 检查 10 参数局部雅可比满秩及条件数；退化姿态、边界解、未收敛均拒绝。
- ACCEPT 仅表示采样模型拟合达到指标，不证明机械间隙、真实重力竖直、笔压、加速后动态精度已合格。程序不宣称仅凭编码器能验证真实笔尖位置。
- `source: simulation` 可以数值 ACCEPT，但 `applicable_to_hardware=false`，不能生成实机配置候选。

## 离线仿真示例

`examples/calibration/example_captures.simulation.json` 是 27 训练点加 12 独立验证点的数值样本；配套 `machine.simulation.json` 是初始名义模型，不是当前板子的机参数。ID2/3/4 注入已知零位偏差，笔长 95 mm，加入计数噪声及整数量化。

```powershell
python scripts/kinematic_calibration.py fit --machine examples/calibration/machine.simulation.json --captures examples/calibration/example_captures.simulation.json --report simulation-report.json
python -m unittest discover -s tests -p test_kinematic_calibration.py -v
```

仿真只证明算法可恢复注入参数、异常数据会拒绝；不能把样例数值抄到实机。

## 速度单位、静态负载和滞后辨识

```powershell
python scripts/identify_servo_dynamics.py --samples servo-measurements.json --report servo-fit-report.json
```

根格式为 `schema: so101-servo-identification-v1`，`source: measured` 或 `simulation`，数组字段如下：

| 字段 | 一项需要的数据 | 使用要求 |
| --- | --- | --- |
| `speed_samples` | `joint_id, speed_code, distance_counts, elapsed_s, steady_window:true` | 每关节 ≥3 段、≥2 个速度码；仅取匀速区间，排除加减速。通过原点拟合 rad/s 每速度码。 |
| `acceleration_samples` | `joint_id, acceleration_code, measured_rad_s2` | 每关节 ≥3 段、≥2 个加速度码；加速度由真实速度曲线测得，不能由预设参数填回。 |
| `load_samples` | `tip_m:[x,y,z], stationary:true, settled_s, target_counts:{...}, measured_counts:{...}` | 至少中心+四角五点、二维覆盖、稳定 ≥0.5 s；补偿为目标减实测。任何补偿 >32 count 应调查机械原因。 |
| `delay_samples` | `joint_id, time_s:[...], target_counts:[...], measured_counts:[...], bias_counts, bias_independently_measured:true` | 每关节独立时序、≥20 个单调时间点、跨度 ≥1 s；用已测静态偏差消除匀速下偏差与延迟的歧义。 |
| `verified_registers` | 全关节共同或按 ID 分组的 `firmware:{major,minor}, velocity_unit, maximum_acceleration, acceleration_multiplier` | 必须来自舵机回读，固件与单位寄存器用于执行前再次核对。 |

速度/加速度拟合最大相对误差要求 ≤15%，各关节公共单位差异 ≤15%；不同型号或单位不一致时不擅自统一。滞后拟合范围 0–0.2 s，边界解和 RMS >3 count 不通过。

输出 `execution_candidate` 与执行器接口一致：`servo_profile`、`load_bias_counts`、`joint_delay_s`。辨识脚本输出的所有补偿默认 `enabled:false`，逐帧速度默认关闭；缺少真实数据、加速度辨识或完整寄存器身份时，`units_verified` 保持 false。此脚本不自动填加速度码；需依据真实验证范围选码，ID2/3/4 使用相同码，再通过低速空画验收。CLI 报告不能直接替代整份 machine.json。

配置迁移与辨识输出要区分：迁移会请求 `frame_speed_enabled:true`，但在单位未验证且 `unverified_policy: preserve_static` 时，执行器仍回退到旧地址42同步位置包和固定速度码，不写加速度；这不是已完成逐帧同步标定。选择 `reject` 时则拒绝执行。不能在这种固定速度回退状态下宣称已达到50 Hz真实跟随或离线预测的绘画速度。

启用逐帧速度前，还要核对速度码/加速度码上限是否足以覆盖轨迹关节上限；执行器不会把超范围码裁剪后继续。负载或时延在不同笔座、工作范围、供电及姿态下可能变化，更换安装或测量条件后要重新辨识。`measurement_id` 关联这次输入数据，不是外部精度验收证书。

速度示例是计数/秒测量；STS 地址41、46或代码数值本身不是“已验证单位”的证据。仿真输入绝不会把 `calibrated` 或 `units_verified` 置为 true。
