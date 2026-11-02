# robots/tcb705/ —— 模型与配置

| 文件 | 用途 |
|---|---|
| `model_source/tcb705.urdf` | 天链官方 TCB705 URDF |
| **`profile.armvision_joint.json`** | **实机配置（当前）**：控制器 DH 模型（`kinematics.source: controller_dh`，与反馈相差 ≤0.02 mm）、竖直笔落笔法兰 Z **219.3**、joint 模式（本地关节角 → `hmcRobotFree`）、0.5 mm 细分、帧数上限 80 万、**归位姿态** `execution.web_program.home` |
| `profile.armvision_web.json` | 旧的 Web 整程序配置（cartesian，控制器自己解 IK，落笔 214.31 是倾斜笔数据），保留作参考 |
| `profile.armvision.json` | 原 ArmVision 导入值（落笔 206.31，对当前笔会压纸），保留作参考 |
| `profile.demo.json` | 离线演示（模拟），不代表实机 |
| `profile.example.json` | 字段示例 |
| `calibration/tcb705_calibration_20261018.json` | 2026-10-18 标定记录 |

板子上实际读取的是 `/home/xilinx/tcb705_data/tcb705.machine.json`，内容与 `profile.armvision_joint.json` 对应（由 joint 发布的激活脚本安装）。改配置时两边都要改，并重启 `tcb705-ui`。

`execution.web_program` 里的执行设置（速度、分段、归位等）不进入配置指纹，修改后不需要重新标定；`planning`、`paper`、模型参数会进入指纹，修改后旧计划会被拒绝执行。
