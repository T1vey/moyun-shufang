# deploy/ —— 部署与板端服务

## 当前 joint 发布（2026-10-18）

`/home/xilinx/tcb705_releases/20261018_joint_r1/ZYNQArm` 已激活，机器配置采用 `profile.armvision_joint.json`；PL 网口持久地址为 `192.168.4.23/24`。机械臂尚未连接，本次仅部署，未执行运动。

激活脚本为 `tcb705/activate_joint_release.sh`，回滚脚本为 `tcb705/rollback_joint_release.sh`。激活使用排在现有配置之后的 `zzzzzzzzz-tcb705-joint.conf`，并验证实际 `ExecStart`；不修改 FPGA 和 GE_PL 服务。备份保存原机器配置、覆盖文件、网络地址及服务状态，具体回滚命令会在终端打印。详见 [部署记录](../docs/TCB705_joint部署_20261018.md)。

板上测试用 `python -m unittest discover -s tests -p 'test_tcb705*.py'`。需要重编时用 `.venv/bin/python scripts/build_tcb705.py --sdk`；不要使用调用 `getconf LONG_BIT` 的旧构建脚本。

| 目录 / 文件 | 用于 | 说明 |
|---|---|---|
| **`tcb705/`** | TCB705 板子 | 部署、FPGA 平台激活/回滚、PL 网口、检查脚本。新执行器部署用 `deploy_web_executor.sh` |
| **`pynq-md0700r/`** | TCB705 板子 | MD0700R 显示屏与 GT911 触摸服务 |
| `standalone/` | 板子 | `so101-platform` 等系统服务定义（**TCB705 板子的 FPGA 平台服务也用它，不要删**） |
| `bluetooth/` | 板子 | 蓝牙收图服务 |
| `deploy_z20.ps1`、`install_z20.sh`、`deploy_pynq.*`、`install_planner.sh`、`enable_pl.sh`、`tunnel.ps1` | SO101 旧方案 | 仍被旧打包脚本引用，保留 |

板子上运行的服务：`so101-platform`（开机加载 FPGA）、`tcb705-ui`（后端 + 界面，`--allow-real`）、`so101-md0700r`（显示）、`so101-gt911`（触摸）。

## 部署新执行器

```bash
sh deploy/tcb705/deploy_web_executor.sh 192.168.2.99
```

需要先能用密钥 SSH 登录板子。脚本会先在板子上备份被替换的文件（`/home/xilinx/tcb705_deploy_backups/web_executor_<时间>`），再复制、在板子上跑测试、安装 web 配置并重启 `tcb705-ui`。不会让机械臂运动。
