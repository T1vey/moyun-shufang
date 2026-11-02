# Z20 交付版部署

本版统一使用 [DELIVERY.md](DELIVERY.md) 中的打包、部署、电脑网关和板上验收流程。

硬件编译步骤见 [TARGET_IK_VIVADO_2024.md](TARGET_IK_VIVADO_2024.md)。

板端新核为 `z20_ik_target_0`；启动参数为 `--ik-engine wls --pl-mode target --overlay overlay/drawing_target.bit`，或使用 `scripts/run_board.py --profile config/runtime.target.json`。

原 `--use-hw` 参数已不适用。不要将旧 LM bitstream 与 target 的 hwh/寄存器映射混用。
