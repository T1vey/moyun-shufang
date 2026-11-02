# ArmVision 标定移植记录

2026-10-17。工程：`D:/zhiliao/TCB705_ZYNQ-10-15/ZYNQArm`。

## 已照搬的内容

以正在使用的软件 `D:/ArmVision2.0_User/backend/config/settings.yaml` 为数值来源。较旧的 `ArmVision2.0_source_20260917` 中范围不同，未用旧值覆盖现用值。实现依据为源码 `src/desktop/widget.cpp` 的 A/B 读取、范围排序、落笔姿态读取，以及 `backend/main.py` 的坐标转换；读取协议来自现用包 `backend/utils/tianlian_xoip_sender.py`。

| 原软件字段 | 导入值 | 含义 |
|---|---:|---|
| X/A、Y/A | -509.605、-67.854 mm | 初始显示最小角 |
| X/B、Y/B | -359.390、80.666 mm | 初始显示最大角 |
| 落笔 Z | 206.310 mm | 控制器世界坐标的纸面高度 |
| U、V、W | 180、0、0° | 控制器工具姿态 |
| 机器人 ID | 1 | 原软件机器人编号 |
| 抬笔高度 | 8 mm | 笔画间离纸高度 |
| 最后抬笔高度差 | 60 mm | 最后一笔离纸高度，从纸面算起 |
| 绘制速度 | 100% | 原控制器程序速度百分比，不是 100 mm/s |
| swap_xy | true | 按原软件交换图像和机械臂 X/Y 方向 |
| Tool / Coord / Extool | 0 / 0 / 0 | 原控制程序参数 |

X 跨度 150.215 mm、Y 跨度 148.520 mm。交换方向后的图像画布宽 148.5 mm、高 150.2 mm，按原 Qt 界面的规则保留一位小数；最终映射仍使用完整范围精度。原文件只保存排序后的范围，没有历史 A/B 采集顺序；再次采集时界面保留原始 A/B，保存范围时排序。

本次采用原软件 8/60 mm，替换了此前提出的 30 mm。单独的算法演示配置仍使用 30 mm，与实际配置和运行数据隔离。

绘制速度百分比作为原软件参数保留和保存，目前没有换算为新七轴规划器的物理速度；本地时间规划仍使用高级配置中的 draw_speed_m_s 和关节动态限制。控制器程序百分比与本地物理速度的对应关系未实测，不做假定换算。

## 使用方法

1. 双击 `run_tcb705.bat` 查看新界面，进入“设置”。默认展示上述导入值。
2. 需要重新采集时，以 `python scripts/run_tcb705.py --allow-real` 启动只读联调；在“控制器连接与坐标选项”填写实际控制器 IP 和 Web 端口。默认不猜测 IP。
3. 用机械臂原有示教器把笔尖移动到纸面范围的一个角，停稳，点“读取A点坐标”；到对角停稳，点“读取B点坐标”。点“保存标定参数”保存范围。
4. 把笔尖放到落笔位置，调整到需要的姿态并停稳，点“获取落笔点”。读取 Z、U、V、W 并保存当前表单。A/B 读取仅更新对应 X/Y，不从 A/B 的 Z 拟合斜面。
5. 保存后配置位于运行数据目录 `tcb705.machine.json`；重新打开会读取保存结果，旧计划须重新生成。没有第三个纸面点，也没有套用 SO101 的多点关节标定。

读取按钮只请求原软件相同的 `/api/user/login` 和 `/api/var/byname`，变量为 `r_world_fb_pos_<ID>_<0..5>_`。不使能、不点动、不下发运动。缺值或 NaN 报错，不把错误反馈当 0。登录沿用原软件默认账号；如控制器账号已修改，通过环境变量 `TCB_WEB_USER`、`TCB_WEB_PASSWORD` 设置，不写入界面配置或任务回执。

## 坐标计算保持一致

令 A/B 排序后为 x_min/x_max、y_min/y_max，图像坐标 (u,v) 采用 Y 向上，整幅画布为 W×H：

```text
swap_xy=true:
    X = x_max - (v / H) × (x_max - x_min)
    Y = y_min + (u / W) × (y_max - y_min)
    Z = z_table

swap_xy=false:
    X = x_min + (u / W) × (x_max - x_min)
    Y = y_min + (v / H) × (y_max - y_min)

笔间 Z = z_table + lift_mm          = 214.310 mm
结束 Z = z_table + final_lift_mm    = 266.310 mm
```

从主界面进入的笔画按整幅画布映射到标定矩形，不再固定裁成 100×100 mm 或按笔画外接框重新居中。输入若是图像 Y 向下，先统一为 Y 向上再做以上映射。路径最终仍在 ZYNQ 的七轴规划器中计算。

## 原软件标定与七轴模型的边界

复制完成的是纸面标定方法和已有参数。原 ArmVision 把世界坐标交给控制器，由控制器使用已有工具、零位和机械臂模型；新项目自行计算七轴逆解，还需确认这些控制器世界坐标与本地 URDF/TCP 的对应关系。A/B+Z/UVW 没有包含工具长度、关节零位或模型基座变换，不能据此称这些数据已标定。

当前导入配置仍标注模型/TCP/SDK 映射未核对，保留的 80 mm TCP 和起始关节值只是旧离线占位数据。未核对前，本地七轴规划明确提示原因，真实透传执行也没有开放。其他 UVW、Tool/Coord/Extool 可原样保存，但本地 IK 尚未支持时会拒绝规划，不强行使用 180/0/0。

现用 ArmVision 文件另有 axis_count=4 和第二机器人配置；它们不属于本次截图中机器人 1 的纸面标定，没有覆盖 TCB705 七轴模型。这些软件保存值是否仍匹配实际纸张、夹具和机器人，需要连接后核对；本轮未驱动或重新标定实体机械臂。

## 文件与复现

- `robots/tcb705/profile.armvision.json`：默认原软件参数，包含来源路径与 SHA256。
- `robots/tcb705/profile.demo.json`：独立算法演示，不含真实纸面参数。
- `tcb705/calibration.py`：A/B 排序、参数派生、坐标映射、姿态适配检查。
- `tcb705/armvision_feedback.py`：原软件 Web 只读反馈协议。
- `tcb705/armvision_import.py`：仅导入允许的数值字段，不复制云端密钥或整个配置。
- `tests/test_armvision_calibration.py`：原值、范围方向、采集、保存、8/60 mm 轨迹与模拟 Web 协议测试。

```powershell
.\.venv\Scripts\python.exe scripts/tcb705_profile.py validate
.\.venv\Scripts\python.exe scripts/tcb705_profile.py armvision --settings D:/ArmVision2.0_User/backend/config/settings.yaml --output build/tcb705/reimport.json
.\.venv\Scripts\python.exe scripts/verify_tcb705.py --output build/tcb705/verification_armvision
```

导入命令不覆盖已存在的输出文件；默认运行入口不修改原 ArmVision 工程。测试使用本机假控制器和明确的合成模型配置，不代表真实控制器通信或实体绘画通过。
