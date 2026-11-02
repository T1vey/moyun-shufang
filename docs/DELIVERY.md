# SO101 Z20 完整目标 IK：软件与硬件交付

版本：0.9-target-delivery，2026-10-03；工具：Vivado / Vitis HLS 2024.2。运行环境：厂家 Z20 PYNQ 2.7、ARMv7、Python 3.8 及以上。

## 1. 已配套完成的范围

新完整目标 IK 的软件后端、规划调用、起始姿态求解、CLI、运行配置、状态查询、计时文件、PC 网关、部署入口和打包清单已连接。软件检查 HWH 内实际 IP/寄存器地址与 JSON 映射一致，并在有 artifact 哈希时校验 bit/hwh/map。数值结果仍由 PS 独立 FK 检查。

运动执行保留现有 audit 继续模式，同时提供 explicit strict 模式。串口读取失败只保留上一次真实测量和时间，不拿目标计数作为反馈；陈旧测量不参与新的笔尖精度判断、不被当作终点到位。最终报告区分 execution_finished、task_complete、feedback_fresh、settled 和 tracking_qualified。

控制页面显示总规划耗时、IK 耗时及预计运动时长，提供 timing.json 下载。执行结果分别显示终点确认、跟踪是否合格、反馈或目标写入失败次数，以及自动归位结果；质量未确认时显示提示。

运行包只包含明确选定的入口、规划器、vendor、页面、模板、示例和检查工具。排除个人密钥、machine 实测配置、logs、saved_plans、备份、主机 DLL、历史 bitstream 和 Vivado 临时文件。真正的标定存放在板卡数据目录，由用户自己的 machine.json 管理。

## 2. 编译 FPGA

打开：`C:\fpga_build\so101_target_2024_1003\vivado\so101_target_ik.xpr`。

在 Vivado 2024.2 运行综合、实现、Generate Bitstream。完成且时序通过后执行：

```tcl
source [file normalize "[get_property DIRECTORY [current_project]]/../src/export_after_bitstream.tcl"]
```

输出目录 `C:\fpga_build\so101_target_2024_1003\export` 内应同时有 `drawing_target.bit`、`drawing_target.hwh` 和 `drawing_target.registers.json`。不要取旧核文件补足三件套。详细硬件参数见 [Vivado 说明](TARGET_IK_VIVADO_2024.md)。

可搬移工程包为 `dist/so101_vivado_2024.zip`，含实际 `.xpr`、生成的 HDL、完整 HLS IP 仓库、板卡预设及寄存器映射。保持其目录结构，解压到英文路径后打开 `so101_target_2024/vivado/so101_target_ik.xpr`。已在另一目录用 Vivado 2024.2 实际打开验证，IP 仓库跟随移动、所有工程源文件存在，综合与实现仍未启动。导出位置将是所打开工程目录的上一层 `export/`。

## 3. 生成交付包

在源码根目录 `D:\zhiliao\newFPGA\SO101_FPGA_ArmSystem` 执行：

```powershell
python scripts/build_delivery.py
```

输出 `dist/so101_target_runtime.zip` 和 `.zip.sha256`。未编译 bitstream 时，这个包明确标为 `SOFTWARE_READY_AWAITING_USER_BITSTREAM`，可运行 PS 模式和软件检查，target 启动会报告缺少 bit/hwh。

编译完成后生成含硬件文件的交付包：

```powershell
python scripts/build_delivery.py --overlay-dir C:\fpga_build\so101_target_2024_1003\export --require-hardware
```

它生成 `PACKAGE_MANIFEST.json`、`RELEASE_STATUS.json` 及 `overlay/drawing_target.artifacts.json`。文件配套齐全仍只表示编译产物可交付，板上验收状态仍是 NOT_RUN。

解压后运行：

```bash
python3 scripts/verify_package.py
python3 scripts/doctor.py
python3 scripts/run_board.py --profile config/runtime.ps.json --check
```

这些命令不加载 FPGA、不发送舵机指令。实际 `.zip.sha256` 应先与收到的 ZIP 文件摘要核对。仅在收到可信来源的包后运行其脚本。

源码工作区的摘要清单可用 `python scripts/build_delivery.py --source-manifest` 更新，然后运行 `python scripts/verify_package.py`。修改源码后需重新测试并打包，不能只更新哈希就当作验收通过。

## 4. 板端安装与启动

解压包顶层目录为 `so101_target_runtime`。在板卡登录用户下执行：

```bash
cd so101_target_runtime
SO101_PYTHON=/usr/local/share/pynq-venv/bin/python3 bash deploy/install_z20.sh --offline --profile target
```

安装脚本从包内 `dependencies/pynq_wheels` 离线安装六个固定版本的纯 Python 依赖；ezdxf 也已打成通用 Python wheel。离线模式要求板卡已有 venv/pip、numpy/scipy/Pillow/OpenCV/scikit-image 及 PYNQ 环境，doctor 会明确报告缺失模块。若板卡有网络，可去掉 `--offline`：数值和图像二进制包使用 Ubuntu apt；纯 Python 依赖仍取随包 wheel，不通过 pip 更新板卡 numpy/scipy/OpenCV。

本版采用 ezdxf 0.17.2，以适配厂家 NumPy 1.17；图片提取本身会内部使用 DXF，因此 ezdxf 为必需依赖。[该版本依赖说明](https://pypi.org/project/ezdxf/0.17.2/)；[svgpathtools 1.6.1](https://pypi.org/project/svgpathtools/1.6.1/)。

安装 target 时会先停止已有 workbench/upstream 服务，执行无舵机 IO 的 85 组板上数值检查，再安装并启动 `so101-workbench.service`。检查失败不安装候选服务，并尝试恢复此前运行的服务。PYNQ 会在加载 overlay 时配置 PL 和时钟，依据 [PYNQ 2.7 Overlay 文档](https://pynq.readthedocs.io/en/v2.7.0/pynq_package/pynq.overlay.html)。

target 服务以 root 运行以访问 PL，PS 模式以登录用户运行；数据和标定放在 `~/so101_data`，可用 `SO101_DATA_DIR` 显式改路径。不会把 config 模板覆盖到该目录的 `machine.json`。从原系统迁移时，把原有有效 `logs/machine.json` 复制到该数据目录，保持实际标定不变。

需要开放真实运动时，在安装命令末尾显式加 `--allow-motion`。服务启动本身不执行绘画；网页仍按已有流程选择实物模式、核对标定和舵机通信。

手动验证或运行：

```bash
sudo .venv/bin/python -B scripts/run_board.py --profile config/runtime.target.json --check
sudo .venv/bin/python -B scripts/run_board.py --profile config/runtime.target.json --data-dir ~/so101_data --allow-motion
```

手动运行前停止已有服务，避免两个进程同时访问舵机或 PL。PS 对照模式改成 `config/runtime.ps.json`，不指定 overlay。target 缺失、ABI 错误、HWH 地址不匹配或超时会明确失败，不自动改用 PS。

## 5. 从 Windows 上传

在源码或运行包根目录执行：

```powershell
.\deploy\deploy_z20.ps1 -BoardIP 192.168.2.99 -Python python -OverlayDir C:\fpga_build\so101_target_2024_1003\export -Offline -AllowMotion
```

使用标准 SSH 身份认证；用户名默认 xilinx，可用 `-UserName` 修改。每次上传放到独立 `~/so101_releases/release_.../so101_target_runtime`；数据目录不随代码发布替换。失败会保留该版本供诊断，不打印“部署成功”。只做 PS 比较时使用 `-Profile ps`，省略 `-OverlayDir`。

脚本运行时才实际上传、加载 PL 和重启服务。本次代码修改没有自动连接板卡或执行这些操作。

## 6. PC 云端与控制页

电脑安装浏览器网关依赖：

```powershell
python -m pip install -r requirements-workbench.txt
.\deploy\tunnel.ps1 -BoardIP 192.168.2.99
```

保持 SSH 转发终端打开。在另一个终端运行：

```powershell
.\launch_pc.ps1 -Python python -CloudConfig config/cloud.example.json -SecretsFile config/secrets.local.json
```

打开 `http://127.0.0.1:8765`。cloud.example.json 是模板，按现有服务的 API endpoint/model 配置后使用；密钥放私有 `.local.json` 或环境变量，不进入交付包，也不发送给板卡。没有云端配置时仍可上传已有线稿或使用预设测试。

页面上传照片、生成线稿、提取笔画；可将 PC 已提取的毫米路径经 `/api/strokes` 交给板端。板端使用同一入口规划、保存轨迹、读取反馈并执行。`/api/status` 可核对当前 `PL_z20_ik_target`、硬件文件摘要、会话是否 faulted；`/job/<id>/timing.json` 返回完整规划阶段耗时。云端请求耗时不算作 IK 加速。

## 7. 机器配置与执行策略

`config/machine.example.json` 仍是未标定模板。使用实际关节 ID、模型零位计数、方向、限位、工具笔尖和纸面坐标；已有检查字段不能由打包脚本替用户填 true。

新增配置段：

```json
"execution": {
  "guard_policy": "audit",
  "max_feedback_s": 0.2,
  "max_lateness_s": 0.2,
  "settle_timeout_s": 30
}
```

未指定时保持 audit：速度、反馈延迟、跟随偏差、笔尖偏差和终点残差记录到审计日志，继续模式保留。选 strict 时，上述超限立即停止后续目标并尝试保持当前位置。两种模式均保留取消、限位、输入验证、位置模式及扭矩检查；串口连续写失败达到既有上限也会失败。audit 的 DONE 表示作业处理结束，精度是否合格须看 task_complete、settled 和 tracking_qualified。

新核固定 nominal 五关节连杆与轴；笔尖偏移、工具轴、关节限位可由配置输入。更改连杆长度/轴方向须重新生成匹配硬件。不得用放宽精度或改舵机速度作为规划性能改善。

## 8. 最终验收

主机验证已完成：规划器 38 项、全应用 117 项通过（含新目标接口、故障语义、文件完整性、解压包独立启动和网关到完整目标规划的联调）；全应用测试使用两个原生 DLL，没有跳过。随包六个纯 Python wheel 已离线安装到独立目录并用于全应用回归，未替换电脑全局安装。59 个运行包 Python 文件通过 Python 3.8 语法检查；这不代替真实 ARMv7/PYNQ 运行验证。

1. 当前主机回归输出与打包测试见 `reports/target_ik/`；运行包摘要检查通过。
2. Vivado 实现满足 100MHz 时序、无阻断 DRC，并配套导出 bit/hwh/map。
3. 板端 `scripts/check_target_overlay.py` 85 组通过，没有会话 faulted；不驱动舵机。
4. 用同一条人像 paths、机器配置和起始计数分别运行 `benchmark_target_ik.py --backend ps` 与 `--backend target`；比较成功率、最终误差、阶段时间和总规划中位数。
5. 小范围实物绘画核对毫米误差、取消、串口故障与终点状态；保存日志、实测图和板上报告。

第 2–5 项需要你编译及实际板卡，当前不宣称已完成整机上板验收。软件包可以交付编译与集成，最终实物交付以这些报告为准。
