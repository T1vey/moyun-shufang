# docs/ —— 文档索引

## TCB705（当前项目）

按时间顺序，从最新开始读：

| 文档 | 内容 |
|---|---|
| **`TCB705_改动记录_20261018.md`** | **今天的全部改动**：一键画画、归位、不中断绘画、手机提示词、规划提速、FPGA 生效、板上备份位置 |
| `TCB705_线稿图库与统一界面_20261018.md` · `TCB705_本地线条图界面_20261018.md` | 本地线稿图库与界面 |
| `TCB705_规划提速_20261018.md` | 规划器 CPU 提速（输出逐字节不变） |
| `TCB705_joint部署_20261018.md` · `TCB705_v2c部署与测速_20261018.md` | joint 发布部署、v2c FPGA 核部署与测速 |
| `CODEX_交接提示词_20261018.md` · `CODEX_板端部署提示词_20261018.md` | 交给 Codex 的交接与部署提示词 |
| **`TCB705_电脑直连驱动与50mm画线_20261017.md`** | **机械臂怎么动起来的**：有效的控制流程、实测结果、落笔高度修正、待查问题 |
| `TCB705_SDK控制调用复核_20261017.txt` | SDK 控制调用复核、只读逆解试算 |
| `TCB705_接口成功但不运动_离线核查_20261017.txt` | “接口成功但不动”的离线排查（SDK 与固件版本不匹配等） |
| `TCB705_GE_PL网口实现与验证_20261017.md` | PL 千兆网口实现与验证 |
| `TCB705_FPGA与CPU批量加速_20261017.md` | FPGA 七轴 IK 与 CPU 批处理加速、速度对比 |
| `TCB705_网口与坐标联调准备_20261017.md` | 网口与坐标联调准备 |
| `TCB705_开发与部署说明.md` | 实现范围、格式、配置、部署 |
| `TCB705_板端部署记录_20261017.md` | 板端部署记录 |
| `TCB705_ArmVision标定说明.md` + `TCB705_ArmVision标定界面.png` | ArmVision 标定流程 |
| `TCB705_验证记录.txt`、`TCB705_*_report.json`、`validation/` | 测试与验证报告 |

桌面上的《TCB705机械臂驱动实现说明.docx》是机械臂驱动部分的完整讲解（含代码），由 `build/tcb705/doc_build/make_doc.js` 生成。

## SO101 旧方案（参考）

以下文档描述的是之前的 SO101 舵机机械臂，不适用于 TCB705。`scripts/build_delivery.py` 按路径打包它们，所以保留在原位置：

`CLOUD_IMAGE_LIBRARY.md`、`CONTACT_PLANE.md`、`DELIVERY.md`、`DEPLOYMENT.md`、`DRAWING_*.md`、`FEEDBACK_DRAWING.md`、`MD0700R_STANDALONE.md`、`MOTION_SMOOTHNESS.md`、`NEW_SUGAR_SCHEME.md`、`PEN_TRANSITIONS.md`、`PLANNER_*.md`、`PLANNING_SPEED.md`、`TARGET_IK_VIVADO_2024.md`、`four_point_calibration.md`、`kinematic_calibration.md`。

`legacy/`：原项目 README（`README_SO101_source.md`）和历次替换前的 README（`README_旧版_20261017.md`、`README_旧版_20261018.md`、`user_gui_README_旧版_20261018.md`）。
