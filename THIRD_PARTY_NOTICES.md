# 第三方来源与分发范围

根目录 MIT 许可适用于项目独立实现，不改变以下材料的原许可。

| 材料 | 来源与许可 | 仓库处理 |
|---|---|---|
| Make Me a Hanzi 派生 3500 字轨迹 | skishore/makemeahanzi，字形来自 Arphic；Arphic Public License | 保留 `data/calligraphy/APL-English.txt`、`COPYING.makemeahanzi` 与来源表；JSONL 入库，SQLite 本地重建 |
| 七轴机器人 URDF | `robots/tcb705/model_source/` 中的原来源与 LICENSE | 原许可文件保留，现场参数仅作样例参考 |
| ArmVision 图像处理 | 用户提供 `ArmVision2.0_source_20260917.rar` | 两个原文件与 `vendor/armvision/ORIGIN.json` 保留；未将其推定改授 MIT |
| SO-101 历史参考核 | E1pco/Hardware-Accelerated_System_for_IK_Solution_Based_on_LeRobot，MIT | `vendor/e1pco/` 保留来源与文件头；不当作七轴当前核 |
| Vitis solver | AMD Vitis Libraries，Apache-2.0 | `vendor/vitis_solver/` 保留原许可 |
| HCCR MobileNetV2 | Ismantic/Handwritten v0.1.1，源码记录为 Apache-2.0；CASIA-HWDB1.1 训练 | ONNX 与类别表保留；来源、转换与校验值见 `user_gui/hwr.py`，外部模型不改授 MIT |
| AMD / 板卡 IP、生成 HDL | AMD 工具与板卡参考工程 | 保留文件头和元数据；须使用相应工具许可重建，不由根目录 MIT 替代 |
| 华成 SDK | 厂商 SDK V2.4.1 | 未发布厂商二进制和头文件；从厂商取得后按 `native/README.md` 配置 |
| 字体派生可选模板与书体库 | 原项目含系统字体及开放字体模板 | 未发布字体与模板二进制；用 `tools/build_style_glyphs.py` 和合法取得的字体本地重建 |
| 海报与封面 | 内置 imagegen 创作主视觉，项目脚本排版 | 标注为概念视觉；字体由本机合法字体渲染，不在仓库分发字体文件 |

`TCB705_SOURCES.json`、各 `ORIGIN.json`、原版权头以及各目录中的许可文件共同构成逐文件来源记录。原 SDK、字体和完整冻结证据保留在用户本机原始工程，未被本次整理修改。
