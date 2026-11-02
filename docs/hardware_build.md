# FPGA 重建

目标器件为 **XC7Z020CLG400-2**，原工程使用 Vivado / Vitis **2024.2**。此版本与指南推荐版本不同，复现时按原版本构建；升级工具应重新验证。PS DDR/MIO/时钟来自本项目实际板卡参考平台，不可替换为其他板卡的默认值。

## 七轴 FP32 核

在仓库根目录，使用短英文构建路径：

```powershell
./scripts/build_tcb705_parallel_fp32_hls.ps1 -BuildDirectory C:/fpga_build/moyun_hls -Profile controller_throughput -Stage all
./scripts/build_tcb705_parallel_fp32_hls.ps1 -BuildDirectory C:/fpga_build/moyun_hls -Profile contract -Stage all
./scripts/build_tcb705_parallel_fp32_vivado.ps1 -HlsDirectory C:/fpga_build/moyun_hls -ProjectDirectory C:/fpga_build/moyun_platform -Stage all
```

原脚本中的工具安装路径为 `D:/Xilinx/.../2024.2`，按本机安装修改。平台脚本引用 `hw/vendor/md0700r`、`hw/ip/vision` 与既有基础 IP；这些源文件和打包描述保留，工具中间缓存已清除。音频集成入口见 `hw/audio/`，最终 IOBUF 修正版的实现数据在 `hw/reports/audio_iobuf_20261027/`。

当前 HLS 源码、合约与仿真说明在 `hls_source/tcb705_parallel_fp32/README.md`；完整平台重建与 OOC 验证入口在 `hw/parallel/`。该目录的源脚本是实际构建入口，README 命令不会自动下载到板子。

## 发布匹配

Git 保存平台 JSON、寄存器元数据与来源哈希；bit/hwh/xsa/dcp/dtbo 由构建工具生成，不提交本机生成二进制。将同次构建匹配的 bit/hwh 和外设文件放回对应 overlay 后，逐项比对清单并运行：

```bash
python skills/pynq-release-audit/scripts/audit_overlay.py overlay/tcb705_audio_iobuf_20261027/platform.json
```

源码刚克隆时报告缺少二进制是预期状态；完成重建与组装后才应全部匹配。不可将不同版本的 bit、hwh、寄存器或 DDR 板级配置混用。
