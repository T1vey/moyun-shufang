# FP32 版本板端部署、自检与规划测速记录（2026-10-24）

板子：ZYNQ7020，`xilinx@192.168.2.99`，Linux 5.4.0-xilinx-v2020.2。全程没有执行、使能、归位或任何机械臂运动。

## 1. 版本与路径

| 项目 | 值 |
|---|---|
| 新发布目录（当前运行） | `/home/xilinx/tcb705_releases/20261024_fp32_r1/ZYNQArm` |
| 平台清单 | `.../20261024_fp32_r1/ZYNQArm/overlay/tcb705/platform.json`，build_id `tcb705-parallel-fp32-20261024` |
| 上一版本（保留，可回滚） | `/home/xilinx/tcb705_releases/20261024_vision_r1/ZYNQArm` |
| 切换备份 | `/home/xilinx/tcb705_deploy_backups/20261024_fp32_r1/`（五个服务原配置、上一启动回执、标定哈希、上一版本路径） |
| 新增 systemd drop-in | 五个服务各一个 `zzzzzzzzzzzzzzzzzzz-fp32.conf` |
| 检查与测速材料（板上） | `/home/xilinx/fp32_check/` |

## 2. 切换前补丁（能力缓存）

- `lineart_backend.py`：`capability()` 缓存键加入 boot_id 内容和小型 ready 回执的 SHA256，只读这两个小文件。
- `tests/test_lineart_capability.py`：新增 `test_identity_changes_invalidate_even_with_coarse_file_timestamps`。
- 已同步到新发布目录，SHA256 板上与本地一致：`b0eb1e45…eeda22`、`e4a32297…a7a826`。原文件备份 `/home/xilinx/fp32_check/*.before_patch`。部署记录 `build/tcb705/fp32_deployment_20261024/expected.json` 已更新这两项哈希，详见同目录 `cache_patch_20261024.json`。
- 测试：本机 94/94 通过；板上 94/94 通过（xilinx 用户，umask 022，见 `board_tests_umask022.log`）。在 xilinx 默认 umask 0002 下，`test_lineart_attachment.test_every_access_rehashes_bytes_receipt_and_process` 报错（`board_tests.log`）：该测试只把临时回执的属主伪装成 root，却保留真实的组可写权限，触发了回执权限保护。属于测试的运行环境依赖，产品代码与本补丁无关。
- 平台文件检查：`PLATFORM_FILES_PASS tcb705-parallel-fp32-20261024`。

## 3. 切换方式

切换由用户以 sudo 执行 `/home/xilinx/fp32_check/select_fp32.py`（逻辑与 `scripts/deploy_fp32_20261024.py select()` 相同；另外把 `FP32_CHECK_PASS.json` 放入发布目录，并去掉发布目录的组/其他写权限，原先很多文件为 666），随后正常重启。没有热加载 FPGA。Claude 没有读取或输入 sudo 密码。

## 4. 重启后验收（已加载并自检通过）

| 项目 | 结果 |
|---|---|
| `/home/xilinx/ZYNQArm` | 指向 `20261024_fp32_r1` |
| so101-platform / tcb705-ge-pl / tcb705-ui / so101-md0700r / so101-gt911 | 全部 active，NRestarts 均为 0 |
| 实际加速时钟 | `TCB705_PHYSICAL_CLOCK_HZ 99999999.0` |
| FP32 逆解协议自检 | `TCB705_FP32_IK_PROTOCOL_SELF_TEST_PASS`（3 行合法 IK、取消、拒绝错误模型；几何残差未评估） |
| 视觉核自检 | `VISION_BOOT_SELFTEST_PASS` |
| 平台 | `PLATFORM_READY tcb705-parallel-fp32-20261024` |
| 应用后端 | `ik_backend = ZYNQ_PL_7R_BATCH` |
| 线稿 | 无 lineart 核，`capability()` 返回 CPU（4 ms） |
| 内核日志 | 无 AXI 超时；仅有开机常见的 SPI flash / regulatory.db 提示 |
| 标定 | `735b3325…afb2`，与部署前一致 |
| 密钥 | `secrets.local.json`、`runtime.target.json`、`vision_cloud.local.json` 未改动 |

ready 回执文件为 root 600，未以 root 读取其内容；其 PASS 由平台服务日志 `PLATFORM_READY` 证明。

**屏幕颜色和触摸需用户在实物上确认；真实机械臂绘画测试不在本次范围，未进行。**

## 5. 规划测速（不运动）

输入：`examples/motion_portrait.paths.json`（8 笔人像），使用板上实际 `tcb705.machine.json`（归位起点，无控制器 I/O）。注意：在实机配置下为 **4744 个节点**，与 10-18 历史测速（1569 节点、另一配置）不可直接比较。

| 方式 | 规划总耗时（热） | 逆解 | 运行时 FK 复核 | 4 ms 帧数 |
|---|---:|---:|---|---:|
| 旧代码 vision_r1，CPU 逆解 | 11.36 s（首次 13.66） | 0.51 s | 42 批 / 42,687 探针 | 177,866 |
| 新代码 fp32_r1，CPU 逆解 | 6.28 s（首次 8.77） | 0.50 s | 无 | 177,866 |
| 新代码 fp32_r1，FPGA FP32 逆解（服务实际路径） | 9.23 s（服务启动后首次 21.99） | 2.41 s（75 批） | 无 | 184,767 |

服务实际路径一次 9.23 s 的分解：FPGA 逆解 2.41 s；其余规划 CPU 6.41 s（曲线、重定时、4 ms 时间表展开）；下发前关节段准备 0.21 s；接口约 0.2 s。服务启动后第一次规划另有 `pl_session_attach_s` 12.74 s 一次性附着开销。

结论：
1. 去掉运行时 FK 复核带来约 1.8 倍提速（同为 CPU 逆解，11.36 s → 6.28 s）。
2. 当前 FPGA FP32 逆解在整图规划里**比 ARM 原生 C++ 逆解慢**：2.41 s 对 0.50 s。每批 64 点平均约 32 ms（约 2000 点/秒），远低于核级 RTL 仿真的 116,104 点/秒，说明瓶颈在每批的 PS 调度、DDR 缓存维护和结果解析，而不是 PL 计算。
3. 因此目前服务实际路径（9.23 s）比直接用 CPU 逆解（6.28 s）慢约 3 秒。FPGA 计算结果与 CPU 结果的关节分支不同（时间表 739 s 对 711 s），不是逐点相同的输出。
4. 剩余主要开销是 4 ms 时间表展开（约 18 万帧）与重定时，见 `docs/板端分工_FPGA资源与规划耗时审计_20261024.txt` 第六节 P2。

数据：`plan_bench_fp32.json`、`cpu_vision_r1.json`、`cpu_fp32_r1.json`；脚本 `bench_plan_api.py`、`bench_plan_cpu.py`。

## 5b. 图库最复杂的一幅：CPU 逆解与 FPGA 逆解对比

按 GUI 相同流程（`vision.convert`，fine，faithful，长边 100 mm）在板上提取全部 18 张本地/云端线稿（`library_scan.json`），最复杂的是 `cloud_images/20261018_141735_173791_seedream_51703845.png`：393 笔、1303 段、画线 1634 mm（CPU 提取 36.7 s，平台无 lineart 核）。在实机配置下为 21,680 个节点，即交付报告离线回放用的 21,679 目标轨迹。同一新代码，各两次：

| 指标 | CPU 逆解（离线 plan_cpu） | FPGA FP32 逆解（服务 API） |
|---|---:|---:|
| 规划总耗时 | 27.05 s / 24.97 s | 37.94 s / 40.57 s |
| 逆解耗时 | 2.25 s（339 批） | 11.09 s / 11.38 s（339 批，0 回退） |
| 逆解速率 | ≈9,600 点/秒 | ≈1,950 点/秒（≈33 ms/批） |
| 其余规划 CPU | ≈22.3 s | ≈25.4 s |
| 4 ms 帧数 | 616,446 | 638,062 |
| 规划画图时长 | 2465.8 s | 2552.2 s |
| 关节段准备 | — | 0.90 / 0.93 s，21,679 段 |

结论与 8 笔人像一致：FPGA 路径在整图规划中更慢，逆解慢约 5 倍，且 FP32 选出的连续分支使计划时长多 3.5%、帧数多 3.5%。服务 API 的 `pl_session_attach_s` 字段沿用服务启动后第一次的附着值（12.74 s），本测试不是首次附着，未计入。数据：`complex_pl.json`、`complex_cpu.json`。

## 6. 回滚

以 root：删除五个服务目录下的 `zzzzzzzzzzzzzzzzzzz-fp32.conf`，把 `/home/xilinx/ZYNQArm` 指回 `/home/xilinx/tcb705_releases/20261024_vision_r1/ZYNQArm`（见备份 `previous_release.txt`），`systemctl daemon-reload`，正常重启。不删除历史发布、用户数据或标定。
