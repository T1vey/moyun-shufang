# GE_PL restoration for the 50 mm line test

Date: 2026-10-17 (Asia/Shanghai).

- Host project: `D:/zhiliao/TCB705_ZYNQ-10-15/ZYNQArm`.
- Board release reused: `/home/xilinx/tcb705_releases/20261017_ge_pl_r2/ZYNQArm`.
- Vivado project source: `hw/vivado_ge_pl`; no new synthesis, implementation, or XSA generation in this run. No Git commit identity was established.
- Programmed bitstream: release `overlay/tcb705_ge_pl/tcb705_planner.bit`, SHA-256 `686b60086234a93d6b33dfaea35286fa1e616788b9b25ea4314208c7cf594149`.
- Manifest build ID: `tcb705_ge_pl_20261017_r1` (artifact build ID; the release directory is r2).
- Firmware/ELF: existing SD-booted Linux, kernel `5.4.0-xilinx-v2020.2`; no new PS ELF or BOOT.BIN installed.
- Restored matching HWH/manifest, FPGA image and Linux device-tree/driver using the staged release's checked platform loader and fixed GE_PL starter.
- Hardware smoke: PASS, three IK targets and 1024 full seven-axis FK rows.
- GE_PS: `eth0`, `192.168.2.99/24`, PC connection, carrier 1.
- GE_PL: `eth1`, `192.168.4.23/24`, controller `192.168.4.4`, carrier 1 after the user confirmed cabling.
- Runtime service overrides restored display, touch and application against this release. Permanent boot selection was not changed.
- Backup: `/home/xilinx/tcb705_deploy_backups/web50_restore_ge_pl_20261017`.

Commands/results are recorded in `build/tcb705/deployment/web50_restore_ge_pl.sh` and `web50_restore_ge_pl.log`. Reconnection and final read-only verification are in `web50_reconnect_readonly_connected.log` and `web50_readonly_after_block.log`.

Robot test status: NOT EXECUTED. Automatic approval rejected the local command that would prepare and offline-test the Web manual-power/motion script, returning only `blocked by policy`. No retry through another tool and no enable or motion command was sent in this run. The subsequent read-only check showed servo state `0`, no active alarms, no application job, and unchanged coordinates across three samples. The requested 50 mm line has not been drawn.

## SDK reconnection requested by the user

The board subsequently reconnected through `libxoip.so` to `192.168.4.4:8001`. This was a read-only SDK diagnostic, not an alternate execution of the denied motion operation.

- Runtime SDK `V2.4.1`; controller `1.9.71-main.aarch64.TIANLIAN.26c8ffa`.
- Seven joint angles and six Cartesian pose values read successfully.
- Global enable `0`, robot 1 enable `0`, motion state `0`, paused `0`.
- Soft emergency-stop query succeeded and reported normal; protection enabled; no active alarms; global speed `10`.
- HMI detach status `0`; alarm-suppression mask `0`. HMI state alone does not establish the cause of earlier non-motion.
- FK query returned failure with no result; both EtherCAT OP queries failed. Failed queries do not establish that the bus is out of OP.
- Tool and workspace IDs `0`, with no returned calibration points. This does not validate the physical pen TCP or paper plane.
- No enable, motion, mode change, alarm clear, HMI detach, or protection change was sent.

Evidence: `build/tcb705/deployment/sdk_reconnect_probe_20261017.log` and `sdk_readonly_status_20261017.log`. SDK diagnostics are in `sdk_readonly_status.cpp` and `sdk_readonly_status.sh` in the same directory. The SDK/controller version pairing remains below the SDK manual's stated minimum controller version and requires vendor confirmation or a matched package. The 50 mm drawing test remains unexecuted.

## Read-only drive-state investigation, 2026-10-17

- User confirmed the cables had not been disconnected and that this physical robot previously moved using the original ArmVision drawing application.
- Management continued through board Wi-Fi `10.217.38.90`; GE_PL `eth1` remained carrier 1 at `192.168.4.23`, with controller `192.168.4.4:8001` reachable. A Windows management Ethernet link report must not be described as the robot being unplugged.
- Confirmed the diagnostic process loaded the expected ARM32 library (SHA-256 `adcacf19bc8efe1666b4c86d5a527836bebda67d9130c356fced9d8aeb49567e`), without `LD_PRELOAD`.
- Confirmed an established SDK TCP connection after a completed query. Earlier socket filtering missed the bracketed IPv4-mapped IPv6 address; the corrected log is `sdk_drive_callback_sockets_readonly_20261017.log`. Established TCP does not itself validate the streaming RPC.
- Read-only SDO 0x6041:00 requests were accepted, but no valid drive statusword was returned. Tests with no application-side filtering and a separate raw `/sdo/update` observer each waited 10 seconds without a corresponding event. No production process callback was changed.
- No fault or readiness conclusion can be inferred from missing callbacks. SDK/controller event compatibility, subscription delivery, controller publication and drive-side response remain unresolved possibilities.
- Current global enable and robot enable were 0; motion state 0; joints unchanged. No enable, motion, mode change, alarm clear, HMI detach, or protection change was sent.
- Supplied ArmVision source uses a Web program-start workflow for drawing, with mode preparation and a servo-state check. This differs from the earlier direct SDK line request. User confirmation makes this a useful reference but does not prove that the supplied source version matches the exact historical executable/configuration.

Further evidence and static SDK findings are recorded in `docs/TCB705_SDK控制调用复核_20261017.txt`. Actual actuation remains untested after the prior automatic approval rejection; the 50 mm line has not been drawn.

## Vision 平台切换与重启，2026-10-24

- 按用户要求执行已暂存发布的 `deploy/tcb705/vision/select_boot.py`，随后重启；执行前后台与界面均空闲。
- 发布：`/home/xilinx/tcb705_releases/20261024_vision_r1/ZYNQArm`；本地/板上切换脚本 SHA256 一致，STAGE_PASS 存在，平台文件校验通过。
- bit：该发布的 `overlay/tcb705/tcb705_planner.bit`，SHA256 `256eb0191a47521b36f6c0a81e6907750d7350c7871eb0289301277bebb9be3e`。本次使用已暂存平台，未重建 Vivado/XSA/ELF 或更换 Linux 启动镜像。
- 命令输出 `VISION_SELECTED_FOR_NEXT_BOOT`，并成功提交重启。boot_id 从 `0f56c183-b81e-4af5-9774-750227eec56f` 变为 `ed1ccefa-7d9a-487b-8be9-aa8edd4a4133`。
- 当前启动回执：`build_id=tcb705_vision_20261024_r1`，`self_test=PASS`，boot_id 与本次启动一致；启动日志含 `VISION_BOOT_SELFTEST_PASS`。
- so101-platform、tcb705-ui、so101-md0700r、so101-gt911、tcb705-ge-pl 全部 active，WorkingDirectory 均指向新发布。8095/8785 HTTP 均正常。
- 标定文件 SHA256 与切换前备份一致。备份：`/home/xilinx/tcb705_deploy_backups/20261024_vision_r1`；回退脚本位于新发布 `deploy/tcb705/vision/rollback.py`，回退选择后须重启。
- 本次没有发送机械臂运动指令。证据：`build/tcb705/deployment/select_vision_reboot_20261024.log`、`verify_vision_boot_20261024.log`。

## FP32 平台切换与重启，2026-10-24

- 按用户指定执行 `/home/xilinx/fp32_check/select_fp32.py` 后重启，切换前后台空闲、手写会话 CLOSED、界面 idle。
- 发布：`/home/xilinx/tcb705_releases/20261024_fp32_r1/ZYNQArm`；平台文件校验通过。使用暂存的 `overlay/tcb705/tcb705_planner_fp32.bit`，本次未重建 Vivado/XSA/ELF。
- 已收到 `FP32_SELECTED_FOR_NEXT_BOOT`。新 boot_id：`5c63df2a-1e6a-4ade-9606-e66047f608ea`。
- 当前启动回执：build_id `tcb705-parallel-fp32-20261024`，ABI `tcb705-planner-fp32-v2`，self_test PASS；与本次启动匹配。视觉启动自检也通过。
- 五个服务全部 active，WorkingDirectory 均指向 FP32 发布；8095 界面及 8785 后端 HTTP 正常，标定文件摘要与切换前一致。
- 备份：`/home/xilinx/tcb705_deploy_backups/20261024_fp32_r1`。日志：`build/tcb705/deployment/select_fp32_reboot_20261024.log`、`verify_fp32_boot_20261024.log`。
- 本次未发送机械臂运动指令。

## 五种书体发布切换，2026-10-25

- 已执行用户给出的 `/home/xilinx/styles_check/select_styles.py`，收到 STYLES_SELECTED_FOR_NEXT_BOOT 后重启。
- 当前发布：`/home/xilinx/tcb705_releases/20261025_styles_r1/ZYNQArm`；新 boot_id `3c0658e1-443a-4076-b4ac-98badb4bfeaf`。
- 继续使用 FP32 平台 `tcb705-parallel-fp32-20261024` / `tcb705-planner-fp32-v2`，本次启动回执自检 PASS；未重建 FPGA/ELF。
- 五个服务全部 active 且 WorkingDirectory 指向 styles 发布；8095/8785 HTTP 正常，标定摘要与切换前备份一致。
- 实际 HTTP `/api/text/capabilities` 返回：楷书 3500、行书 3498、草书 3498、隶书 3498、篆书 3465；手机页面包含 writing-styles 控件及 text-writing.js。未操作实机书写。
- 备份：`/home/xilinx/tcb705_deploy_backups/20261025_styles_r1`。
- 日志：`build/tcb705/deployment/select_styles_reboot_20261025.log`、`verify_styles_boot_20261025.log`。
