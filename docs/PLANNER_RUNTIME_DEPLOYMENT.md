# Planner v2：Zynq 板端部署

此版本运行时只有 Zynq PS 与 PL。桌面电脑用于生成和传输发布包，不参与轨迹规划。

## 发布包与硬件

生成命令：

```text
python scripts/build_delivery.py --mode planner --platform-dir dist/planner_platform_20261011 --require-hardware --output dist/so101_planner_runtime.zip
```

ZIP 顶层为 `so101_planner_runtime`。其中 `overlay/planner_platform` 包含同一版本的 bit、HWH、寄存器映射、工件哈希与 `platform.json`。PYNQ MMIO 显示和 PL GT911 触摸使用用户态服务，不应用旧 PS I²C 触摸 DTBO，也不替换内核或 BOOT 文件。发布包不包含旧的 `install_z20.sh`、`enable_pl.sh` 等 target v1 部署入口。

发布包状态保留 `board_acceptance=NOT_RUN`。构建成功并不代表某一块板已通过验收；实际板端安装和独立核验的记录应另外保存。

## 从当前 target 平台迁移

先解压到一个新的、最终保留的目录。不要覆盖旧运行目录、共享数据或校准文件。以下命令中的 `NEW` 必须替换为该发布目录。

```bash
cd NEW/so101_planner_runtime
sudo bash deploy/install_planner.sh \
  --previous-runtime /home/xilinx/so101_releases/release_md0700r_20261010_1972f8f6/so101_target_runtime \
  --profile /home/xilinx/.config/so101/runtime.target.json \
  --data-dir /home/xilinx/so101_data_work107 \
  --backup /home/xilinx/so101_deploy_planner_20261011 \
  --prepare-only
```

准备阶段校验文件哈希，继承旧版 PYNQ Python 运行环境，用板上 g++ 构建 FP64 native 几何库，并检查依赖和库加载。此阶段不停止服务，也不加载 FPGA。

准备通过后，使用相同命令并去掉 `--prepare-only`。备份目录必须不存在。安装只支持已有、可恢复的 target 平台迁移到 planner；不是任意旧系统的一键修复程序。

安装顺序：

1. 查询当前任务，存在活动任务就退出。备份现有配置、服务信息和校准文件。
2. 依次停止触摸、显示、工作台和平台服务；验证进程已退出，确认没有遗留 PL 在途标记。
3. 记录共享数据哈希。生成独立的新运行配置，保留旧配置中的云端、网络等选项，仅替换加速器与加载策略。
4. 先启动平台服务，加载新 bitstream，并执行不涉及舵机的 IK、FK 与 DDR 自检；工作台和显示只附着到已加载的平台。
5. 启动工作台、显示、触摸服务，检查 planner 后端、显示帧完成、触摸服务状态和校准文件哈希，然后启用开机服务。

原 `cloud.conf` 和 USB host 依赖保留，新 `zzzz-planner.conf` 更新有效可执行路径。安装保持之前明确启用的 `--allow-motion` 设置；加 `--disable-motion` 可关闭该功能。安装脚本本身不打开舵机串口、不发送运动或执行轨迹的请求。

## 故障与回退

失败时先停止候选服务。只有确认进程已正常退出、且 PL 没有在途 DMA 标记，才恢复被安装器修改的配置并加载旧 target 平台。校准与共享数据不会由回退逻辑覆盖。旧发布目录始终保留。

如果服务被强杀、DMA 排空未知或存在遗留标记，脚本会记录 `RECOVERY_REQUIRED_SERVICES_STOPPED`，停止自动重载 FPGA。不能删除标记后强行重试；应在停止相关服务的状态下检查记录并完成安全复位/重启。不能在加速器仍访问 DDR 时释放内存或更换 bitstream。

`--backup` 目录中的 `install.json` 记录阶段、原服务状态、被修改文件及回退结果。该目录权限为 0700，可能含原有私密配置，不应作为公开报告发布。

## 验收范围

安装成功的状态为 `INSTALLED_NO_MOTION_SMOKE_PASS`，只表示本次运行的核自检、服务和显示帧检查通过。手动触摸交互、整图轨迹规划时间、重启启动以及实体绘画是不同的验收项目，必须按实际结果记录，不能由 ZIP 构建或服务状态推断。
