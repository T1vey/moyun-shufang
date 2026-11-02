# tcb705/ —— TCB705 核心包

ZYNQ 本地七轴规划 + 把规划结果下发给控制器。单位：模型内部 m / rad / s；控制器接口 mm / 度。

## 按流程阅读

| 顺序 | 模块 | 作用 |
|---|---|---|
| 1 | `config.py` | 读取/校验机器配置；`digest()` 生成冻结计划的配置指纹；`readiness()` 判断能否实机执行 |
| 2 | `calibration.py` | ArmVision 标定（A/B 范围、落笔 Z、UVW）→ 纸面坐标系；`assert_model_ready()` 实机规划门槛 |
| 3 | `model.py` | 读 URDF，调用 C++ 核心做 FK / 雅可比 / IK；`from_sdk()`/`to_sdk()` 做关节角换算 |
| 4 | `planner.py` | **整幅规划**：笔画排序 → 抬笔/移动/落笔 → 0.5 mm 细分 → 连续 IK → C2 重定时 → FK 几何与碰撞校验 → 4 ms 帧校验 → 预测图 |
| 5 | `planning_batches.py` | 每次 64 个目标点的 IK 批次：**板上发给 FPGA（`PLChain`），每个结果由 CPU FP64 复核**；失败退回 CPU |
| 6 | `accel_contract.py` `accel_runtime.py` `planning_session.py` `accel_selftest.py` | FPGA 七轴核的 DDR ABI、平台挂载、独占会话、自检 |
| 7 | `collision.py` | 胶囊体自碰撞检查（有 C++ 版时走 `model.self_collision_batch`，结果与 numpy 版一致） |
| 8 | `artifact.py` | 冻结计划：模拟模式写 `plan.json` + `trajectory.bin` + `nodes.json`（SHA256 校验）；**实机模式 `freeze()` 留在内存，不写文件**；`preview_svg()` 精简预测图 |
| 9 | `web_control.py` | 控制器 Web 客户端（端口 8010）：登录、状态/关节/位姿、自动/手动、下载/启动程序、停止、恢复 |
| 10 | `web_executor.py` | **执行器**：归位 → 节点 → `hmcRobotFree`（或 `hmcLine`）程序 → 分段下发 → 监控 → 归位 → 恢复手动；停止后也归位 |
| 11 | `bridge.py` | 实机入口：`web_start()` 读控制器当前关节（未启用归位时用作规划起点）；`execute()` 选择模拟或实机执行 |
| 12 | `workbench.py` | 接到原糖画坊 HTTP 任务框架（图片/笔画/规划/执行任务）；启用归位时从归位关节规划，不读控制器 |

## 标定与诊断

| 模块 | 作用 |
|---|---|
| `kinematic_fit.py` | 由关节角/位姿样本拟合本地 URDF 与控制器的映射（符号、零位、基座、TCP），带留出检验和镜像解检查 |
| `commissioning.py` | 坐标核对、TCP 定点法（只读） |
| `armvision_feedback.py` `armvision_import.py` | 只读读取控制器位姿；从 ArmVision 配置导入数值 |
| `ethernet.py` `ge_pl_contract.py` | 网口/PL 网卡检查 |

## 两种执行模式（`execution.web_program`）

| 设置 | 含义 |
|---|---|
| `mode: cartesian`, `ik_role: planning_only` | 本地 IK（FPGA）负责规划与校验；下发控制器坐标，**控制器自己解 IK**。只需纸面标定 |
| `mode: joint`, `ik_role: execution`（**当前**） | 下发本地 IK 的 7 个关节角（`hmcRobotFree`）。需要 `sdk_mapping_verified`（完整关节标定），否则代码拒绝 |

其他关键设置：`draw_speed_pct` / `air_speed_pct`（程序速度 %）、`max_blocks`（每段程序块数）、`uvw: current`（执行时保持控制器当前笔姿态）。这些设置不进入配置指纹，修改后不必重新规划。

## 2026-10-18 更新

- `collision.py`：`check_batch()` 向量化碰撞检查（与逐个检查结果完全一致），规划总耗时 8.69 s → 0.92 s。
- `model.py`：`model_corrections` 连杆几何修正（每关节 ≤20 mm / 0.05 rad），CPU 与 FPGA 都使用修正后的模型。
- `kinematic_fit.py`：`fit(..., geometry=True)` 同时拟合连杆几何。URDF 主尺寸已与结构图核对一致（270/230/153 mm）。
- `web_executor.py`：joint 模式执行前检查关节插补偏离（画线 ≤0.05 mm，空中 ≤1 mm）。
- `calibration.py`：`planning.canvas_fit: contain` 保持图片比例并居中（web 配置默认）。

## 2026-10-18 下午更新

- **归位** `execution.web_program.home`（`{enabled, joint_degrees, speed_pct}`，仅 joint 模式）：规划从归位关节出发；执行时先 `go_home()`（竖直抬起 → 到归位点 → 归位关节），画完与停止后也归位。当前归位点：纸面中心 (-434.50, 6.41)，法兰 Z 319.3（离纸 100 mm），笔竖直。
- **画的过程不被软件打断**（启用归位时）：偏离、Z 下限、无进展、超时只记 `WARN_*`，读位置失败自动重试；只在板上停止（`CancelledByUser`）或控制器自身停止（`CONTROLLER_HALTED`）时结束。未启用归位的配置保持原来的保护行为。
- **实机计划不写文件**：`artifact.freeze()` + `execute(..., frozen=(doc, nodes))`，仍核对配置指纹与模型哈希；只保留最近 3 份内存计划。
- **规划提速**（输出逐字节不变）：C++ 新增 `tcb_self_collision_batch`、`tcb_sample_rows`，批处理在两个 A9 核上并行；人像 23.6 s → 12.5 s。
- **FPGA 在 GUI 规划中生效**：`accel_runtime.ensure_event_loop()` 给规划线程共用一个 asyncio 循环（之前因缺事件循环退回 CPU）。
- **帧数上限** 15 万 → 80 万（`config.py` 校验与各配置 `max_frames`）；规划峰值约 0.53 KB/帧。
- **预测图精简** `artifact.simplify()`（0.02 mm），人像预测图 2.2 MB → 9 KB。
