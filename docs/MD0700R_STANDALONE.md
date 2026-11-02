# 领航者 Zynq7020：MD0700R 1024×600 板端控制台

> 本文保留 2026-10-09 的早期内核 DRM 与设备树方案，供设计追溯。当前板端使用 2026-10-10 验证的 PYNQ 帧缓冲显示和 PL GT911 触摸，部署说明见 [当前显示与触摸](../deploy/pynq-md0700r/README.md)，当前制品见 [工程首页](../README.md)。下文的旧显示硬件和旧软件 ZIP 已移入工程外的整理备份；不要按本文的早期步骤覆盖当前系统。

本次目标是把 GUI、图片上传/下载、轮廓提取、规划及机械臂控制移到 PYNQ 板端。云端 AI 仍由原有接口完成。用户已确认七寸 1024×600；电脑暂未连接板卡，因此本次不执行上板安装、触摸或机械臂动作。

## 软件入口

`python3 scripts/run_touch_gui.py` 启动板端触摸界面，直接调用 `127.0.0.1:8765`，不建立 SSH 隧道。调试可加 `--windowed --offline --data-dir <临时目录>`。

- 1024×600 窗口/全屏、绘画页滚动按钮、日志页、常驻停止按钮、ASCII/数字触摸键盘。
- Wi-Fi 窗口通过 NetworkManager 连接路由器，只允许无线接口。密码从标准输入传递，不出现在命令参数或日志中。暂不提供企业认证、热点和中文输入法；云端预设提示词继续可用。
- 云端上传/下载沿用原接口；板端图片传输最长边限制为 1024，图片库在数据目录的 `cloud_images`。原图仍留在用户选择的位置。
- 四点标定草稿/快照写到数据目录 `gui_calibration`；继续使用现有 `machine.json`。不会恢复旧项目标定。
- 停止按钮继续调用原来的停止 API。关窗口不会偷偷执行归位，绘画运行时要求先停止。

## FPGA 加载方式的变化

RGB 屏由 PL 显示链路驱动，因此原来只含 IK 的比特流不能驱动这块屏。本次增加 LCD 帧缓冲、VTC、RGB 输出、动态像素时钟以及触摸 EMIO，保留 IK 地址 `0x40000000 / 64 KiB` 和 100 MHz 控制时钟。

开机 `so101-platform.service` 统一加载融合 bit + DTBO，执行不涉及串口的 IK 已知向量测试，再写入本次 boot ID/制品哈希凭据。工作台使用 `--pl-load-policy attach`，只映射 IK 寄存器，不再次下载 FPGA。凭据缺失或版本不一致直接报错，不回退到重新烧写。

Xorg 使用显示连接器对应的 DRM card，避免把 zocl 计算设备误当显示设备。关闭/重启 GUI 不影响平台加载。

## 离线构建

Vivado 2024.2，器件 xc7z020clg400-2。厂家工程来源为资料盘 `Linux驱动例程.rar/25_lcd_disp/vivado_prj/Navigator_7020.rar`。

```text
vivado -mode batch -source hw/md0700r/create_fused.tcl -tclargs <厂家Navigator_7020目录> <现有IK的IP目录> <全新输出目录>
vivado -mode batch -source hw/md0700r/build_fused.tcl -tclargs <输出目录/so101_md0700r.xpr>
```

Windows 若 Vivado 无输出退出，需在该进程设置 `PROCESSOR_ARCHITECTURE=AMD64`。脚本生成独立工程，不覆盖原来的可用 bit。构建输出包含时序、DRC、CDC、资源报告；板端验收前不能视为可用交付。

## Linux 内核与设备树

当前 PYNQ 原内核缺少完整 LCD DRM 配置。仅安装 Python GUI 无法点亮屏幕。`hw/md0700r/linux` 包含厂家时钟、PWM、LCD 驱动、配置片段、设备树以及集成脚本。

必须以**板卡当前 PYNQ 内核的完整源码、配置和补丁**为基础建立独立构建目录。不能用厂家整个根文件系统替换现有 PYNQ，也不能只凭同为“5.4”就安装模块。

1. 备份原启动文件、`/lib/modules`、现有数据目录；记录内核配置、启动方式、基础设备树符号及模块版本。
2. 在独立 kernel checkout 执行 `python3 prepare_kernel.py <kernel源码>`；合并原配置与 `display.config`，检查 `olddefconfig` 后各必需选项仍启用。
3. 使用 ARM 交叉工具链完整构建 zImage/modules，保留 PYNQ、USB host、CDC ACM、网络及现有驱动。建议独立 LOCALVERSION，连同全部配套模块交付，不与旧模块混用。
4. `sh build_dtbo.sh <kernel源码> <输出/display.dtbo>`。设备树引用 `clkc/intc/gpio0/i2c1`，必须先验证基础 DT 导出这些符号；必要时根据实机基础 DT 调整，不猜地址。
5. 当前触摸节点按 Goodix GT9271、I²C 地址 0x5d 配置，属于待实机确认项。若屏上芯片/地址不同，先核对标签与内核探测日志，再选择驱动，不能同时启用两个共用复位脚的触摸节点。

厂家示例帧缓冲复位已改为 GPIO bit 0，与设备树一致；复位先经过像素时钟域的 proc_sys_reset，同步释放后送到帧缓冲，避免直接从 AXI GPIO 跨域复位。

触摸连接：R19=SCL，P20=SDA，M19=复位，U19=中断。融合工程只有两个 EMIO GPIO，因此 Linux PS GPIO 偏移为 54/55，不能照搬厂家 11-GPIO 工程的 59/60。

厂家 1024×600 时序：51.2 MHz，H back/front/sync=140/160/20，V=20/12/3。保留厂家按 LCD ID 选择面板的逻辑。实际 ID、颜色、方向、触摸映射必须上板确认。

内核配置核对参考：[Xilinx 2020.2 DRM Kconfig](https://github.com/Xilinx/linux-xlnx/blob/xilinx-v2020.2/drivers/gpu/drm/xlnx/Kconfig)。本机目前无 Linux/WSL 构建环境，Linux 内核和 Wi-Fi ko 尚不能在此 Windows 环境完成真实编译验收。DTBO 已用 Vitis 自带 dtc 编译，但仍需与板卡基础 DT 合并验证。

## ATK USB Wi-Fi

已随代码保存用户资料盘 5.4.0 目录的 `RTL8733_WIFI.tar.gz` 及 SHA256。模块目标 `8733bu`，USB ID 0bda:b733。不使用无关 RTL8188 驱动。

在 Linux 中：

```text
python3 hw/md0700r/linux/build_wifi.py --kernel-build <完整kernel构建目录> --output <全新输出目录> --cross-compile arm-linux-gnueabihf-
sudo python3 deploy/standalone/install_wifi.py <WiFi构建输出目录>
```

构建要求 `.config`、`Module.symvers`、`include/config/kernel.release`，安装检查哈希与运行内核 vermagic。STA 联网由 NetworkManager 管理，保留以太网配置。现有用户名/云端密钥不放进发行包。

## 板端部署顺序（连接后执行）

1. 读取板端版本/设备树/屏幕与 Wi-Fi USB 信息，完成配套 Linux 构建和启动文件备份。先验证无机械臂动作的显示/触摸链路。
2. 安装轻量桌面依赖：`python3-tk python3-pil.imagetk xserver-xorg-core xserver-xorg-video-modesetting xserver-xorg-input-libinput lightdm openbox x11-xserver-utils fonts-noto-cjk network-manager`；检查发行版软件源提供的具体包名，不盲目升级整个系统。原项目 Python 依赖继续保留。
3. 把运行包放进新的 release 目录，保留 `/home/xilinx/so101_data_work107`。云端密钥放在 `/home/xilinx/.config/so101/secrets.local.json`，归 xilinx 所有，权限 0600。
4. 用 `package_platform.py` 将真实 bit/hwh/registers/dtbo 按实际内核版本封装为平台清单。禁止拿旧 IK bit 的哈希为融合 bit 签封。
5. `sudo python3 scripts/install_touch_desktop.py --platform-manifest <平台目录/platform.json>`。安装器备份原配置并设置下次启动服务，不当场重启服务或机械臂。
6. 维护状态下启用融合平台，验证内核日志和 IK 向量，再重启进入本地 GUI。首次出现错误先保留日志，按备份回退，不重刷数据分区。

## 验收标准

- 屏幕实际 1024×600、颜色与方向正确，四角触摸位置对应；主要按钮可触达。
- GUI 连续关闭/启动、后端重启时屏幕不中断，PL 不重新下载。
- Wi-Fi 能获取 IP、DNS 可用、系统时间同步；一次实际云端上传和图片下载成功。原图和结果断电后仍保留。
- 原标定值未改变；先断开舵机电源验证读取/规划，再由用户执行小范围绘画测试。
- 显示运行同时 IK 向量、规划和画图正常，记录内存峰值与 DDR 负载。

此文档明确区分代码完成、离线编译和实机通过；只完成前两项不能报告“已部署到板子”。

## 构建与验证边界

软件回归：规划器 47 项、应用 345 项通过（包括新增 7 项平台身份/不重载/Wi-Fi 密码处理测试及 1 项 Tk 布局测试）。1024×600 Tk 布局检查中绘画页、舵机页按钮未发生横向溢出，舵机页保存按钮可触达。此检查不替代 Linux 字体/触摸实测。

DTBO 编译存在一项覆盖片段根节点地址单元的上下文警告，需与实际基础 DT 合并后复查。面板外部 setup/hold、触摸响应、动态改频和 PYNQ 内核模块兼容性均须实机验收，不能仅用 FPGA 内部 WNS 通过代替。

最终融合工程：`C:\fpga_build\so101_md0700r_20261009_r4\so101_md0700r.xpr`。Vivado 2024.2 已生成 bit/HWH/XSA；51.2 MHz 像素时钟下内部 WNS=0.421 ns、WHS=0.048 ns，CDC Critical=0（保留 1 项厂家多位同步 Warning）。LUT 51.92%、FF 32.20%、BRAM 4.64%、DSP 45.45%。输出在 `dist/md0700r_hardware_20261009`，状态为编译完成、板端验收未运行。

软件包：`dist/so101_md0700r_software_20261009.zip`；硬件包：`dist/so101_md0700r_hardware_20261009.zip`。硬件包尚未绑定一个已编译验证的 PYNQ 内核，所以不生成可直接安装的 platform.json，避免误装。
