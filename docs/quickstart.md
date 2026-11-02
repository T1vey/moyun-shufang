# 快速开始

## 桌面模拟

建议 Python 3.11 与 PowerShell 7（Linux 使用 bash）。从仓库根目录执行：

```bash
python -m venv .venv
# PowerShell 7
./.venv/Scripts/Activate.ps1
python -m pip install -r requirements-public-demo.txt
python scripts/prepare_public_data.py
python scripts/run_tcb705.py --simulation --profile robots/tcb705/profile.demo.json --data-dir build/demo --web-port 8095 --backend-port 8785
```

Linux 激活命令为 `source .venv/bin/activate`。浏览器打开 `http://127.0.0.1:8095/`。`--simulation` 是必须显式保留的演示参数；它使用模拟接口，不发送真实机械臂运动。

## 规划与字库

3500 字 JSONL 为版本化源数据，SQLite 由 `scripts/prepare_public_data.py` 从同一数据无损生成。可选书体、硬笔 SQLite、音频和字体模板不在源码包内；相应功能需按各目录文档准备。默认楷书与核心界面可先独立验证。

需要本地七轴规划时，安装 g++ 后执行 `python scripts/build_tcb705.py --cxx /path/to/g++`，生成 `build/tcb705/` 中的 CPU 核；不加 `--sdk` 的桌面构建无须安装华成 SDK。缺少动态库会影响需要原生几何的功能，单纯启动网页不等于完成规划验证。

## 离线回归

```bash
python scripts/verify_public_release.py
python -m unittest discover -s tests -p test_tcb_fp32_contract.py
python -m unittest discover -s tests -p test_glyph_library_integrity.py
python scripts/check_public_desktop.py
```

本次实际执行的模块、通过数量和环境记录在 `docs/public_release_validation.json`，历史测试结果保留各自日期和版本。

## 板端部署

硬件：XC7Z020CLG400-2、实际板卡匹配的 PS DDR/MIO/时钟、MD0700R/GT911，以及 TCB705 控制器。硬件重建见 `hardware_build.md`。生产配置与标定由现场设备持有者填写，不能用示例纸面高度直接操作实物。

云端图生图从 `config/cloud.seedream.example.json` 等模板配置；API 凭据放在忽略的 `config/secrets.local.json`。商业 SDK 与板端动态库由本地构建准备。既有 `deploy/` 脚本保持原接口，执行前替换示例地址并阅读其作用范围。

运动验收顺序：通信连通与位置读取、限位/纸面/笔长核对、单轴小范围、短线、完整作品。软件停止与物理急停都需现场可用。毛笔提按使用高度模板，当前不是力传感器闭环。
