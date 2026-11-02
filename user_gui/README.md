# user_gui/ —— 糖画坊界面（板子屏幕 + 手机）

2026-10-22：手机扫码页“毛笔写字”字库已扩为一级常用 3500 字，40～70 mm、现代横排和分页。该入口通过专用 `/api/text/*` 接口取得当前任务的开始权限；原照片流程仍在屏幕确认。详情见 [3500 字库扩展](../docs/3500字库扩展_使用与验证_20261022.md)。

> 上一版说明保存在 [docs/legacy/user_gui_README_旧版_20261018.md](../docs/legacy/user_gui_README_旧版_20261018.md)。

## 两个页面

| 页面 | 地址 | 谁用 | 文件 |
|---|---|---|---|
| 屏幕页 | `http://127.0.0.1:8095/`（板子屏幕以 `?kiosk=1` 打开） | 板子触摸屏；电脑可经 SSH 隧道访问 | `static/desktop.*`、`gallery.*`、`local-lineart.css`、`base.css` |
| 手机上传页 | `/upload?t=<配对码>`（`/m` 同） | 手机扫屏幕右侧二维码 | `static/mobile.*` |
| 设置 / 调试 | `/debug` | 屏幕页右上“设置” | `static/tcb-debug.*` |

通用控制、设置和 SDK 接口仍只接受本机请求并校验屏幕令牌。图片上传和配对手机的文字专用接口对局域网开放；文字任务校验手机归属、当前预览、同源和重复请求编号。

## 流程

**本地线稿（屏幕页）**：“选择本地线条图” → 图库（缩略图、搜索、大图预览）→“使用这张线稿”→ **“一键画画”** → 本地提取中心线（faithful 模式，保持图片比例）→ 七轴规划 → 规划完成**自动开始**绘制（页面自己调用 `/api/workflow/start`，不再点确认）。

**手机照片**：选 **画什么**（人物 / 物体 / 山水 / 自己写）与 **模式**（简略 / 细节）→ 拍照或选图 → 上传 → 云端生成线稿 → 提取 → 规划 → 屏幕显示预测图 → 在屏幕上点 **“确认并开始绘制”**。手机不能直接启动运动。

两条路都可以在屏幕上 **“停止绘画”**：停下后机械臂自动归位（见 `tcb705/web_executor.py`）。

## 文件分工

| 文件 | 作用 |
|---|---|
| `display_server.py` | 网页服务：二维码与配对、手机上传（`/api/upload`，带 `subject` / `detail` / `prompt` 参数）、图库接口 `/api/lineart-library*`、本地线稿 `/api/lineart-library/prepare`、状态推送、仅本机的控制接口 |
| `workflow.py` | 任务状态机：上传 → 云端（或本地线稿）→ 提笔画 → 规划 → 预测图 → 开始 → 完成/取消；`BoardPipeline` 调用后端 `app.py`（8785） |
| `lineart_library.py` | 本地线稿图库：汇总 `<data-dir>/lineart_library/`、`<data-dir>/cloud_images/`、`~/Pictures/SO101/CloudImages/`，缩略图、导入 |
| `netinfo.py` | 网卡检测，生成二维码地址 |
| `timeline.py` | 每个任务的时间线（上传、云端、提取、规划各花多久） |
| `static/desktop.js` | 屏幕页逻辑：一键画画、自动开始、停止 |
| `static/gallery.js` | 图库弹窗（板子屏幕上隐藏“导入线稿”，因为没有窗口管理器，系统文件框关不掉） |
| `static/mobile.js` | 手机页：取景、画什么/模式选择（记在手机本地）、上传 |
| `static/sugar.js` | 糖画动画 |

每个任务的文件在 `<data-dir>/user_gui_jobs/<任务号>/`：`input`（原图）、`paths/`（笔画）、`timeline.json`，手机任务还有 `cloud_request.json`（当时的主题、模式、提示词长度，不含密钥）。

## 板子屏幕的浏览器限制

板子屏幕是 Xvfb 上的 **WebKitGTK 2.28**（约等于 Safari 13），由 `scripts/user_gui_kiosk.py` 打开，触摸由 `so101-gt911` 转成鼠标点击。写页面时注意：

- 不支持 CSS `inset`、flex 的 `gap`、`:has()`，`Array.prototype.at()`；用 `top/right/bottom/left` 和 margin 代替（`gallery.css` 末尾有 `@supports not (inset:0)` 兜底）。
- 软件渲染很慢：大 SVG 会卡死页面。预测图由 `tcb705/artifact.py` 的 `simplify()` 精简（人像约 9 KB）。
- 没有窗口管理器：不要在屏幕页弹系统对话框（文件选择等）。
- 页面文件服务端不缓存：改了 `static/` 不用重启服务，屏幕上点“设置”再“返回”即可重新加载。

## 运行

板子上由 `tcb705-ui` 服务启动（`scripts/run_tcb705.py`：后端 `app.py` 端口 8785 + 本服务端口 8095），屏幕由 `so101-md0700r` 服务显示。电脑上离线运行见根目录 README §2.3。

电脑访问板子屏幕页（公钥 SSH 本地转发）：

```powershell
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8095:127.0.0.1:8095 xilinx@10.217.38.90
```

注意：转发占用电脑的 127.0.0.1:8095，同时在电脑上跑演示要换端口。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_user_gui_workflow tests.test_user_gui_gallery tests.test_cloud_gallery tests.test_cloud_transport
```

使用假的后端和假的云端，不会驱动机械臂，也不会调用付费接口。`user_gui/tests/` 是本目录自带的旧测试。
