# tests/ —— 测试

## TCB705（必须全部通过）

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_tcb705 tests.test_tcb705_web tests.test_tcb705_kinfit tests.test_tcb705_lineart_plan tests.test_user_gui_gallery tests.test_user_gui_workflow tests.test_cloud_gallery tests.test_cloud_transport
```

板子上（没有 `tests/__init__.py`，用 discover；低优先级运行，避免影响服务）：

```sh
cd /home/xilinx/tcb705_releases/20261018_joint_r1/ZYNQArm && nice -n 10 .venv/bin/python -B -m unittest discover -s tests -p 'test_tcb705*.py'
```

| 文件 | 覆盖 |
|---|---|
| `test_tcb705.py` | 七轴数值（FK/IK/雅可比）、整幅规划、冻结计划、模拟执行、HTTP 流程与安全门槛 |
| `test_tcb705_web.py` | Web 执行器（假控制器，不连硬件）：程序生成、合并、分段、上电下沉、模式门槛；**归位**、绘画中只报警不中断、停止后归位、读位置重试；内存计划与文件计划等价 |
| `test_tcb705_kinfit.py` | 关节标定拟合：用合成数据还原符号/零位/基座/TCP，拒绝分布不足的数据 |
| `test_tcb705_lineart_plan.py` | 本地线稿规划（鸭子、长图）、帧数上限、预测图精简、规划线程事件循环、板子浏览器 CSS 兼容；**C++ 与 numpy 结果逐位一致**（这 2 项只在重编过 C++ 核心的板子上运行，电脑上跳过） |
| `test_user_gui_workflow.py` | 界面任务流程：上传、确认、取消、访问边界；手机“画什么/模式/自己写”参数传到云端；云端错误码显示 |
| `test_user_gui_gallery.py` | 本地线稿图库：列表、缩略图、导入、本地线稿准备 |
| `test_cloud_gallery.py` `test_cloud_transport.py` | 云端图生图请求与线稿库（假接口，不花钱） |
| `test_tcb_*.py`、`test_armvision_calibration.py`、`test_ge_pl_contract.py` | FPGA 平台、会话、加速、ArmVision 标定、PL 网口（`scripts/verify_tcb705.py` 会跑） |

## 共用模块与 SO101 旧测试

其余测试覆盖图像处理、云端、蓝牙、界面、计划存储，以及 SO101 旧方案。整理前后的结果完全一致：剩余 39 个测试文件中 32 个通过；以下 7 个在整理前就失败，与 TCB705 无关，原样保留：

`test_cartesian_feedback.py`、`test_drawing_size.py`、`test_four_point_calibration.py`、`test_md0700r_packaging.py`、`test_pen_transitions.py`、`test_planner_platform.py`、`test_workbench.py`（42 项中 1 项出错）。

`fixtures/` 是测试数据。没有被任何地方引用的旧测试已移到 `_archive/tests/`。
