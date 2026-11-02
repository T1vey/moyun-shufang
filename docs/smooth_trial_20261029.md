# smooth 4 试用记录（2026-10-29，deploy21_smooth4）

## 为什么改

用户要求把所有书写功能的 smooth 统一改成 4 试一试：看书写是否更快、更流畅。效果不好时要能退回。

## 改之前 → 改之后（实际下发给机械臂的 smooth）

| 功能 | 改之前 | 改之后 |
|---|---|---|
| 名帖表演、诗词、春联、硬笔（固定速度） | 平缓弯处 3（≤45°），其余 0；队列 4 | 平缓弯处 **4**（≤45°），其余 0；队列 4 |
| 毛笔页面、字帖、手机文字页（界面速度） | 全部 0（队列 1，逐点停） | 平缓弯处 **4**（≤45°），其余 0；队列 4 |
| 图案、线条画（画笔，界面速度） | 全部 0（配置写 5，但队列 1 强制为 0） | 纸上平缓点 **4**，其余 0；队列 4 |
| 屏上手写 | 平缓弯处 3（≤20°），其余 0；队列 4 | 平缓弯处 **4**（≤20°），其余 0；队列 4 |
| 复位、开始前和结束后归位、停止后归位 | 0 | 0（不变） |
| 标定、测试脚本 | 0 | 0（不变） |

任何功能里，这些地方始终是 0（精确到位）：转角、笔画起点和终点、落笔和抬笔、规划的停顿点、所有空中移动。原因：混合过的空中接近动作曾经偏离 23.75 mm。

毛笔页面、字帖开了混合后，“低于纸面”的报警余量也自动从 0.5 mm 放宽到 1.0 mm，和表演模式一样（`web_executor.paper_margin`）。

## 改了哪些文件

| 文件 | 改动 |
|---|---|
| `tcb705/blend.py`（新） | 所有混合参数集中在这里；`TRIAL = True` 是试用开关 |
| `tcb705/workbench.py` | 表演参数改从 blend.py 读取；界面速度的运行也带上 PAGE_BLEND、LINEART_SMOOTH 和队列 4 |
| `handwriting/executor.py` | 手写的 BLEND 改从 blend.py 读取 |
| `tcb705/web_executor.py` | 线条画的空中移动也固定为 0（以前队列为 1，这条本来就不会生效） |
| `tests/test_blend_trial.py`（新） | 检查开关两种状态下的数值 |

板上路径：`/home/xilinx/tcb705_releases/20261025_styles_r1/ZYNQArm/`
改之前的备份：`/home/xilinx/styles_check/deploy21_smooth4_20261029/backup_before.tar`

## 怎么退回去

**方法 1：关掉开关（推荐，一行）**。所有功能回到改之前的数值：表演和手写 3，其余 0。

```bash
ssh xilinx@192.168.2.99 "cd /home/xilinx/tcb705_releases/20261025_styles_r1/ZYNQArm && sed -i 's/^TRIAL = True/TRIAL = False/' tcb705/blend.py && grep -n '^TRIAL' tcb705/blend.py"
```
然后重启板子。

**方法 2：只换数值**。例如改成 3 或 5：编辑板上 `tcb705/blend.py` 里的 `SMOOTH = 4`，然后重启。数值只能是 1–9。

**方法 3：完全还原文件**。恢复成部署前的样子：

```bash
ssh xilinx@192.168.2.99 "bash /home/xilinx/styles_check/deploy21_smooth4_20261029/restore.sh"
```
然后重启板子。restore.sh 会解开 backup_before.tar，把三个改过的文件放回原样，再把 blend.py 的开关设为 `TRIAL = False`。blend.py 不能删：13:07 UTC 另一个会话部署的 workbench.py 已经引用它，部署前的备份里也是这个版本。restore.sh 在板上的临时目录里试过，三个文件的校验都对得上。

## 试用时注意

- smooth 4 从没在实机上跑过（之前只用过 3），控制器每一级削掉多少毫米没有文档说明。
- 如果出现以下情况，就用方法 1 退回：笔画变细或变粗、转角被削圆、因为“低于纸面”而停止、或者明显抖动。
