# SO101 Z20 触摸屏绘画工程

适用硬件：正点原子 Z20（Zynq-7020）、MD0700R 1024×600 屏幕、GT911 触摸、ATK USB Wi-Fi 与蓝牙模块。板端环境为 PYNQ 2.7，硬件工具链为 Vivado / Vitis HLS 2024.2。

当前用户流程：**手机扫码传图 → 自动云端生成线稿 → 自动笔画提取与 PL 加速规划 → 显示静态预测图 → 用户在板子上确认 → 机械臂绘画**。默认 Wi-Fi 为 ESP8200（密码 12345678）。右上角“设置”打开原调试控制台，其中可返回用户界面。蓝牙收图和电脑端入口继续保留。详见 [糖画坊用户界面](user_gui/README.md)。

## 常用入口

| 要做什么 | 入口 |
|---|---|
| 使用板端用户界面 | 开机显示糖画坊；入口 `scripts/run_user_gui.py`，扫码后自动准备，板上确认后开始 |
| 设置与调试 | 用户界面右上角“设置”；原控制台入口 `scripts/run_touch_gui.py` |
| 安卓手机传图 | 控制台“蓝牙收图”，配对 `SO101-Draw`；见 [蓝牙使用说明](deploy/bluetooth/README.md) |
| 启动电脑 GUI | 双击 `run_studio.bat` |
| 离线查看电脑界面和图片库 | `python scripts/arm_studio.py --target-drawing --offline --no-tunnel` |
| 启动电脑网页网关 | `launch_pc.ps1`，访问 `http://127.0.0.1:8765` |
| 查看当前显示与触摸部署 | [PYNQ 显示与 GT911](deploy/pynq-md0700r/README.md) |
| 查看轨迹规划与绘画预测 | [规划说明](docs/PLANNING_SPEED.md)、[绘画预测](docs/DRAWING_PREDICTION.md) |
| 运行本地回归 | `powershell -File run_tests.ps1 -RequireNative`，需安装对应 Python 依赖 |

当前板端通过 `so101-workbench`、`so101-md0700r`、`so101-gt911` 和 `so101-bluetooth` 服务运行。维护已部署系统时以当前显示与触摸部署说明为准。

2026-10-13 新方案将用户绘画统一为“糖画连续”模式：弧长计时、连续空移、50 Hz 下发、共同高度曲线的竖直升降和有误差界限的笔画平滑。用户选择暂时沿用既有标定，1.10.1版已支持当前标定兼容使用；此选择不等于通过新的精度验收。日后可用新增的多点零位与笔长标定改善模型，并重做四点纸面校正。实施细节、离线基准和现场待办见 [新糖画方案](docs/NEW_SUGAR_SCHEME.md)。

## 目录说明

| 位置 | 内容 |
|---|---|
| 根目录 `*.py` | 应用、云端图片、轨迹规划、IK 和运动模块；采用同级导入，保留在根目录 |
| `scripts/` | GUI、启动、诊断、基准测试和打包工具 |
| `user_gui/` | 最终板端糖画坊、手机上传页面和自动准备流程 |
| `config/` | 运行配置、标定模板及本机私有配置 |
| `deploy/pynq-md0700r/` | 当前 PYNQ 显示与 PL 触摸适配 |
| `deploy/bluetooth/` | 安卓蓝牙收图服务和安装说明 |
| `deploy/standalone/` | 早期独立桌面方案和无线安装工具，具体适用范围见相关说明 |
| `hw/md0700r/` | 显示与 GT911 的 FPGA 源码、Wi-Fi 与蓝牙驱动构建来源 |
| `hw/target_ik/`、`hls_source/` | 目标 IK 硬件工程脚本、IP、C++ 和数值验收向量 |
| `planner_source/`、`vendor/` | 规划器及图像处理依赖源码 |
| `dependencies/`、`models/` | 离线 Python 依赖和手部跟随模型 |
| `web/`、`examples/` | 网页资源与输入示例 |
| `tests/` | 应用与规划接口回归测试 |
| `build/` | 仅保留 native 数值测试库、实际轨迹回归输入和四点标定验证记录 |
| `dist/` | 当前软件包、现役硬件与驱动，以及完整 Vivado 基础工程存档 |
| `reports/` | 验收结果、性能汇总和必要复现输入；大型重复规划输出已归档 |
| `docs/` | 功能、标定、编译和历史方案说明 |
| `ik_solver/`、`overlay/`、其余 `hw/` 子目录 | 仍被旧硬件后端与手部跟随示例引用的配套内容 |

本机 API 配置在 `config/secrets.local.json`；板端私有配置在 `/home/xilinx/.config/so101/secrets.local.json`。运行包不包含这些私有配置。板端图片和机器标定数据位于 `/home/xilinx/so101_data_work107`。

## 当前交付文件

| 内容 | 路径 |
|---|---|
| 新方案软件及 planner 硬件交付包 | `dist/so101_sugar_fast_feedback_recovery_20261013.zip` 及 `.sha256` |
| planner 现役硬件平台 | `dist/planner_platform_20261011/` |
| 较早 target 软件包 | `dist/so101_target_runtime.zip` 及 `.sha256` |
| 现役屏幕、GT911 与 IK 硬件全套导出 | `dist/md0700r_touch_hardware_20261010/` |
| Wi-Fi 驱动 | `dist/wifi_rtl8733bu_5.4.0_20261010/` |
| 蓝牙模块、固件与构建记录 | `dist/bluetooth_20261010/` |
| 原始完整目标 IK Vivado 工程存档 | `dist/so101_vivado_2024.zip`，是早期 IK 基础工程，不含后续屏幕与 GT911 集成 |

当前触摸硬件源码与重建步骤见 [GT911 工程说明](hw/md0700r/gt911_pl/README.md)。`drawing_target.bit`、`.hwh`、`.registers.json`、`.artifacts.json` 必须成套使用。根 `overlay/` 保留旧 IK 示例配套件，当前触摸屏制品取自上表目录。

重新打包当前软件及硬件：

```powershell
python -B scripts/build_delivery.py --source-manifest --mode planner --platform-dir dist/planner_platform_20261011 --require-hardware --output dist/so101_sugar_fast_feedback_recovery_20261013.zip
python -B scripts/verify_package.py
```

运行包包含当前显示与蓝牙服务源码；无线内核模块仍在各自的 `dist` 目录中单独保留。打包成功表示文件与哈希校验通过，不代表在新板卡上完成安装或验收。

## 验证记录

2026-10-10 的显示、触摸、Wi-Fi/API、蓝牙收图、AI 响应修复及预览关闭按钮记录分别在 `reports/md0700r_deploy_20261010/`、`reports/api_wifi_20261010/`、`reports/bluetooth_20261010/`、`reports/cloud_response_fix_20261010/` 和 `reports/preview_close_20261010/`。其中蓝牙已确认一次安卓实传；整套最终配置的断电重启和持续绘画验收仍需实机完成。

`docs/MD0700R_STANDALONE.md` 保留早期内核 DRM 方案；当前已部署系统使用 PYNQ 帧缓冲显示与 PL GT911，见当前部署说明。旧 LM/单步 IP 和手部跟随示例也继续保留，但不属于当前触摸绘画链路。

## 整理与恢复

2026-10-11 整理时，旧 `app/` 副本、历史 `backups/`、旧运行包、一次性构建与大型规划输出已移出主工程。恢复备份在工程同级的 `_cleanup_backup_20261011_152940/`，其中 `archived/` 保留原目录层级，`before.json` 保存整理前文件哈希，`originals/` 保存本次修改前的文件。

需要历史文件时，按原相对路径从备份取回；`restore.ps1` 默认只列出恢复内容，使用 `-Apply` 才恢复，而且不会覆盖现有文件。Python 缓存与空 Vivado 临时目录可自动再生成。清理统计见 `reports/project_cleanup_20261011/summary.json`。
