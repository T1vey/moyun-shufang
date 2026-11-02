# TCB705 · ZYNQ7020 绘画机械臂（糖画坊）

2026-10-24：新增 **FP32 七轴流水逆解、100 MHz 完整平台及独立 AXI 读写通道**；图案预览直接显示云端线稿，删除运行时重复 FK 复核，并在无 lineart IP 时直接选 CPU。源码、编译文件、实际测试范围见 [本次交付记录](hw/reports/parallel_fp32_20261024/README.md)。本次版本尚未部署到板子；下方旧版本板测结果不代表本次 FP32 版本。

2026-10-22 新增 **300 字手机扫码毛笔书写**：40～70 mm 字号、标准笔顺、从左到右横排、自动换行分页、每页归位与换纸确认。详见 [使用与验收说明](docs/300字扫码书写_使用与验收_20261022.md)。本轮已完成工程和离线验证，尚未部署到板子。

2026-10-20 新增线稿提取 PL 工程与 CPU 原生加速，构建、验证和部署说明见 [线稿 PL 加速实施说明](docs/线稿PL加速实施说明.md)。独立 Vivado 工程位于 `hw/vivado_lineart/tcb705_lineart.xpr`，具体编译及板端验收状态以构建验收报告为准。

用 ZYNQ7020 控制天链 TCB705 七轴机械臂画画：

```
线稿图 / 手机照片 ─► 提取笔画 ─► ZYNQ 本地七轴规划（FPGA 加速逆解） ─► 关节角程序下发控制器 ─► 机械臂画画
```

> 上一版 README 保存在 [docs/legacy/README_旧版_20261018.md](docs/legacy/README_旧版_20261018.md)，更早的在同目录。

---

## 1. 现在能做什么（2026-10-18）

| 能力 | 状态 |
|---|---|
| 板子屏幕选本地线稿 → **一键画画** | ✅ 规划完自动开始画；开始前和结束后都自动归位 |
| 手机扫码上传照片 → 云端生成线稿 → 画 | ✅ 手机上可选 **人物 / 物体 / 山水 / 自己写**，以及 **简略 / 细节** 模式 |
| 本地七轴规划 + FPGA 逆解 | ✅ 板上实测：人像（5267 节点）规划 12 s；输出与纯 CPU 逐字节一致 |
| joint 模式执行（本地关节角 → `hmcRobotFree`） | ✅ 控制器 DH 模型与反馈相差 ≤0.02 mm |
| 画的过程中不被软件打断 | ✅ 只有板上“停止”、急停或控制器自身报警会让它停；停止后自动归位 |

已知限制见 [§7 常见问题](#7-常见问题)。今天的全部改动见 [docs/TCB705_改动记录_20261018.md](docs/TCB705_改动记录_20261018.md)。

---

## 2. 怎么用

### 2.1 板子屏幕：画本地线稿（最常用）

1. 点右上 **“选择本地线条图”** → 图库里点一张看大图 → **“使用这张线稿”**。
2. 点 **“一键画画”**。规划十几秒到几十秒，**规划完机械臂立即开始动，不再确认**。
3. 机械臂先**自动归位**（纸面中心上方 100 mm、笔竖直），画完再回到归位点。
4. 中途要停：点 **“停止绘画”**（会停下并自动归位），或拍急停。

> 点“一键画画”之前确认有人守在急停旁、周围无人。

### 2.2 手机：拍照让它画

1. 手机连 **ESP8200** Wi-Fi，扫板子屏幕右侧二维码（地址形如 `http://10.217.38.90:8095/upload?t=…`）。
2. 选 **画什么**（人物 / 物体 / 山水 / 自己写）和 **模式**（简略：笔画少；细节：线更多、画更久）。
3. 拍照或选图 → **“上传并自动处理”**。板子调用云端生成线稿、提取笔画并规划。
4. 板子屏幕出现预测图后，在**板子上**点 **“确认并开始绘制”**（手机这条路仍需在板上确认）。

提示词写在 [cloud.py](cloud.py)：通用部分（简略 / 细节两套）+ 主题部分，“自己写”的内容也会加上通用部分，保证能画出来。

### 2.3 电脑上离线演示（不连机械臂）

```powershell
run_tcb705_demo.bat
```

浏览器打开 `http://127.0.0.1:8095/`（模拟模式，不发送任何运动）。若 8095 已被 SSH 隧道占用，用
`.\.venv\Scripts\python.exe scripts\run_tcb705.py --simulation --profile robots\tcb705\profile.demo.json --data-dir build\tcb705\demo_ui --web-port 8097 --backend-port 8787`。

### 2.4 运行测试

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_tcb705 tests.test_tcb705_web tests.test_tcb705_kinfit tests.test_tcb705_lineart_plan tests.test_user_gui_gallery tests.test_user_gui_workflow tests.test_cloud_gallery tests.test_cloud_transport
```

（2026-10-18：133 项通过，2 项跳过——那 2 项比对 C++ 新函数，电脑上的 DLL 没有重编，只在板上运行。）

---

## 3. 板子

| 项目 | 值 |
|---|---|
| 地址 | Wi-Fi `wlan0` **10.217.38.90**（ESP8200）；网线 `eth0` 192.168.2.99（接电脑）；`eth1` 192.168.4.23 → 控制器 **192.168.4.4:8010** |
| 当前发布 | `/home/xilinx/tcb705_releases/20261018_joint_r1/ZYNQArm` |
| 实际使用的配置 | `/home/xilinx/tcb705_data/tcb705.machine.json`（joint 模式、落笔 Z 219.3、归位姿态、帧数上限 80 万） |
| 数据目录 | `/home/xilinx/tcb705_data/`：`lineart_library/` 导入的线稿、`cloud_images/` 云端线稿、`user_gui_jobs/` 每次任务 |
| 服务 | `tcb705-ui`（后端 8785 + 界面 8095）、`so101-md0700r`（屏幕）、`so101-gt911`（触摸）、`so101-platform`（开机加载 FPGA） |

常用命令（电脑上执行；重启需要输入板子 xilinx 的 sudo 密码）：

```bash
ssh -t xilinx@10.217.38.90 "sudo systemctl restart tcb705-ui"
```

```bash
ssh xilinx@10.217.38.90 "systemctl is-active tcb705-ui so101-md0700r so101-gt911; cat /sys/class/net/eth1/carrier; ping -c 2 192.168.4.4"
```

```bash
ssh xilinx@10.217.38.90 "journalctl -u tcb705-ui --since -30min --no-pager | tail -40"
```

- 改了 `.py` 后要重启 `tcb705-ui`；只改 `user_gui/static/` 下的网页文件不用重启，页面刷新即可（板子屏幕：点“设置”再“返回”）。
- 部署新执行器：`sh deploy/tcb705/deploy_web_executor.sh 192.168.2.99`；joint 发布的激活/回滚见 [deploy/README.md](deploy/README.md)。

---

## 4. 整体流程

```
本地线稿（板子图库）           手机照片
      │                          │ cloud.py：通用提示词 + 主题/自写 → seedream 图生图
      └──────────┬───────────────┘
                 ▼
  vision.py / stroke_paths.py   提取中心线笔画 → paths.json
                 ▼
  tcb705/planner.py             从固定归位姿态出发：笔画排序 → 抬落笔 → 0.5 mm 细分
                                → 七轴连续 IK（planning_batches：板上 FPGA，CPU 逐点复核）
                                → C2 重定时 → FK/碰撞校验（C++ 核心） → 4 ms 帧校验 → 预测图
                 ▼              实机模式：规划结果留在内存，不写文件（artifact.freeze）
  tcb705/web_executor.py        归位 → 关节节点合并成 hmcRobotFree 程序块 → 下发执行 → 监控（只记警告）
                                → 归位 → 切回手动
                 ▼
         TCB705 控制器 192.168.4.4:8010 → 机械臂
```

界面这一层：`user_gui/display_server.py`（网页服务）+ `user_gui/workflow.py`（任务状态机）+ `user_gui/static/`（屏幕页、手机页）。

---

## 5. 目录地图

### 5.1 主线（看这些就够了）

| 目录 / 文件 | 内容 |
|---|---|
| [`tcb705/`](tcb705/README.md) | **核心包**：模型、规划、FPGA 调度、执行器、控制器通信 |
| [`user_gui/`](user_gui/README.md) | **糖画坊界面**：板子屏幕页、手机上传页、本地线稿图库、任务流程 |
| [`robots/tcb705/`](robots/tcb705/README.md) | URDF 与配置（实机用 `profile.armvision_joint.json`） |
| `cloud.py` `cloud_gallery.py` | 云端图生图与提示词；云端线稿库 |
| `vision.py` `stroke_paths.py` `path_quality.py` | 图片 → 中心线笔画 |
| `native/tcb_planner/` | 七轴 C++ 核心（FK/IK/批处理、碰撞、帧采样），Windows 与 ARM 都编译 |
| [`hls_source/tcb705/`](hls_source/README.md) · [`hw/`](hw/README.md) · `overlay/tcb705/` | FPGA IK 核 HLS 源码 · Vivado 工程/比特流 · 板端平台清单 |
| `app.py` · `workbench.py` | 后端 HTTP 服务（`--robot tcb705`）与任务框架 |
| [`scripts/`](scripts/README.md) | 启动、构建、标定、画图等命令行脚本 |
| [`deploy/`](deploy/README.md) | 板端部署、激活/回滚、系统服务 |
| [`tests/`](tests/README.md) | 测试 |
| [`docs/`](docs/README.md) | 文档索引 |

### 5.2 其他目录

| 目录 | 内容 |
|---|---|
| [`build/`](build/README.md) | 生成物与实机记录（编译结果、联调日志、调试脚本）；不是源码 |
| `dist/` | 历次打包的发布 zip（约 400 MB），供回退或交付 |
| `config/` | 云端模型配置模板（`cloud.*.example.json`）；`secrets.local.json` 含密钥，**不要外传** |
| `tools/` | 板子辅助脚本：SSH、隧道、重启服务、PL 网口发现 |
| `web/` | `app.py` 自带的旧调试网页 |
| `reports/` | 上电记录 `bringup.md`（部分测试引用） |
| `examples/` | 示例图片与预览 |
| `vendor/huacheng/` | 华成 SDK 头文件与 ARM 库（现在用 Web 接口，不走 SDK） |
| `ik_solver/` `planner_source/` 及根目录多数 `*.py` | SO101 旧机械臂代码，被 `app.py` 旧分支引用，**TCB705 不使用，不能随意移动** |
| `NA/` | Vivado 生成的 `ps7_summary.html`（路径名为 NA），未被引用 |
| [`_archive/`](_archive/README.md) | 已归档的无引用文件，`python _archive/restore.py` 可全部还原 |

根目录模块的用途分组见 [docs/legacy/README_旧版_20261018.md](docs/legacy/README_旧版_20261018.md) §3.2。板端服务和部署脚本按这些路径运行，移动前先查引用。

---

## 6. 安全约定（当前行为）

- **一键画画会在规划完后自动开始运动**，没有二次确认；点之前必须有人守在急停旁、周围无人。手机上传那条路仍需在板上点“确认并开始绘制”。
- **绘画中软件不会主动中断**：偏离路径、低于下限、无进展、超时、读不到位置都只记警告。能让它停的只有：板上“停止绘画”、急停、控制器自身报警/伺服断电。代价是走偏时只能靠人停。
- **开始前自动归位**：从任何高度先竖直抬起、到归位点（纸面中心 Z 319.3、笔竖直），再开始；离纸不足 60 mm 只记警告不拒绝。**画完和停止后都自动归位**，再切回手动。
- 竖直笔落笔法兰高度 **Z = 219.3 mm**，规划不会低于它（214.31 是旧的倾斜笔数据，不能用）。
- 手动 ↔ 自动切换可能下沉 7～15 mm；画完停在 Z 319.3，下沉后仍高于 60 mm，下次可直接切换。
- 不清除报警、不改保护设置；运动请求不自动重试（只重试读取）。
- `config/secrets.local.json` 含密钥，不要外传；日志和界面只显示云端错误码，不记录原始说明、账号和网址。

---

## 7. 常见问题

| 现象 / 报错 | 原因 | 处理 |
|---|---|---|
| `START_ORIENTATION: 请先示教笔轴竖直…` | 旧流程从机械臂当前姿态规划，笔歪了就拒绝 | 现在从归位姿态规划，不应再出现；若出现，检查配置里 `execution.web_program.home.enabled` |
| `MODE_SWITCH_CLEARANCE` | 离纸不足 60 mm 时切模式（非归位流程，例如单独脚本） | 归位流程只记警告；单独脚本需先抬高 |
| `<urlopen error [Errno 113] No route to host>` | 板子连控制器的 `eth1` 没有链路 | `cat /sys/class/net/eth1/carrier` 为 0：查网线两端、控制器电源；今天出现过周期性断链 |
| `FRAME_BUDGET` | 轨迹超过帧数上限（80 万帧 ≈ 53 分钟） | 换简单的图或用简略模式；上限在 `tcb705/config.py` 与 `max_frames` |
| `CURVE_GEOMETRY … reduce sample_step_m` | 个别复杂线稿某段偏差略超 0.1 mm | 换图；根治需要规划器自适应细分（未做） |
| `图像服务拒绝请求（HTTP 400，错误码）` | 云端拒绝，错误码说明原因（敏感内容、参数、欠费等） | 按提示换照片 / 改描述；`HTTP 400` 无错误码时看 `user_gui_jobs/<任务>/cloud_request.json` 里当时的选项 |
| 板子屏幕点不动 | 浏览器在渲染很大的预测图（已修：预测图简化到约 9 KB）或被系统文件选择框挡住（已修：屏幕上不再显示“导入线稿”） | 板上 `journalctl` 看服务；必要时重启 `tcb705-ui` |
| 屏幕上的弹窗打不开 | 板子浏览器是 WebKitGTK 2.28，不支持部分新 CSS（如 `inset`） | 写 `user_gui/static/` 时避开新语法，`tests/test_tcb705_lineart_plan.py` 有检查 |
| 规划没用上 FPGA | 规划线程缺 asyncio 事件循环（已修） | 看规划结果 `metrics.ik_backend` 是否为 `ZYNQ_PL_7R_BATCH` |
