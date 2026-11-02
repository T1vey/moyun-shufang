# 安卓蓝牙图片接收

安卓手机原生“分享 → 蓝牙”通过经典蓝牙 OPP 发送图片到 `SO101-Draw`。
接收完成后进入控制台蓝牙接收箱；选图、路径规划和开始绘画仍由用户分别操作。
蓝牙服务不调用任何机械臂接口，也不依赖网络或云端 API。

## 软件与启动

目标环境：PYNQ Ubuntu 20.04，Python 3.8，BlueZ 5.53。
依赖 `bluez`、`bluez-obexd`、`dbus`、`python3-dbus`、`python3-gi`、`python3-pil`。
USB 蓝牙控制器驱动和对应固件必须已安装，`bluetoothctl list` 能列出适配器。
本安装脚本不替换内核、FPGA 比特流或触摸/显示服务。

在板端完整 runtime 中运行，可重复执行：

```sh
sudo sh deploy/bluetooth/install.sh /absolute/path/to/so101_target_runtime /home/xilinx/so101_data_work107
```

安装器保留图片和 BlueZ 配对记录，更新接收服务配置并重新启动服务。
服务以 `xilinx` 运行；`dbus-run-session` 创建专用 session bus，Python 启动同一
session 中的 `obexd --nodetach --plugin=bluetooth,opp,filesystem`。
适配器与配对 Agent 使用 system bus。没有 `--auto-accept`，只开放 OPP 服务。
蓝牙断连不会删除已完成图片，服务异常自动重启；启动会清理上次中断的 `.part`。

## 手机使用

1. 控制台打开“蓝牙收图”，点击“允许新设备配对”。两分钟内板子可被搜索。
2. 安卓设置中找到 `SO101-Draw`；核对两端六位数字并在两端确认。
3. 手机相册选择一张图片，选择“分享 → 蓝牙 → SO101-Draw”。
4. 接收箱出现图片后，选中并点击“使用此图片”。收到图片不会启动机械臂。

配对确认必须在 45 秒内完成，过期或拒绝均不保存信任。
只有本次用户批准并成功配对后才设为受信任设备。已配对手机在发现窗口结束后仍可发送。
手机若不提供蓝牙分享入口，可用其文件管理器的蓝牙发送功能。
支持 JPG、PNG、WebP、BMP 和静态 GIF；单张上限 32 MiB、1600 万像素。
不支持动画、HEIC 或文件夹。接收箱总量上限由 `bluetooth_inbox.py` 执行。

## 控制台接口

状态文件 `/run/so101-bluetooth/status.json`，控制 UNIX socket
`/run/so101-bluetooth/control.sock` 均只允许 `xilinx` 或 root 访问。
请求是一行 JSON，响应一行 `{ "ok": true }` 或 `{ "ok": false, "error": "..." }`。

```json
{"command":"pair","seconds":120}
{"command":"confirm","request_id":"状态中的唯一请求ID","accept":true}
{"command":"stop_pair"}
```

`pair` 固定开启 120 秒，重复点击重新计时；`confirm` 必须匹配当前未过期请求。
状态包含 `adapter_name,address,powered,receiver_ready,last_error,pairing_until,pending`，
其中 `pending` 为 null 或 `{request_id,device_name,address,passkey,expires_at}`。
`passkey` 是补齐前导零的六位字符串；所有显示时间都是 Unix 秒。
`received_count` 是本次服务启动后的成功数，持久图片列表以接收箱记录为准。

## 验证与诊断

```sh
systemctl status so101-bluetooth.service --no-pager
journalctl -b -u so101-bluetooth.service --no-pager -n 50
cat /run/so101-bluetooth/status.json
bluetoothctl show
```

必须实测同一手机连续两张图片、同名图片、发送中取消、重启服务后再次发送；
用手机确认配对与传图，不能把纯软件存储测试当成射频传输验收。
新手机未配对、图片超限、伪造后缀、解码失败均不得出现在接收箱。

## BlueZ 5.53 依据

- [OBEX Agent API](https://raw.githubusercontent.com/bluez/bluez/5.53/doc/obex-agent-api.txt)：AuthorizePush 指定暂存文件路径。
- [OBEX API](https://raw.githubusercontent.com/bluez/bluez/5.53/doc/obex-api.txt)：Transfer、Session 属性与完成状态。
- [配对 Agent API](https://raw.githubusercontent.com/bluez/bluez/5.53/doc/agent-api.txt)：DisplayYesNo 数字比较。
- [OPP 实现](https://raw.githubusercontent.com/bluez/bluez/5.53/obexd/plugins/opp.c)：同一会话可复用 Transfer 对象，逐次授权建立记录。
- [会话重置](https://raw.githubusercontent.com/bluez/bluez/5.53/obexd/src/obex.c)：完成后元数据会被清空，因此先缓存授权元数据。
- [文件处理插件](https://raw.githubusercontent.com/bluez/bluez/5.53/obexd/plugins/filesystem.c)：必须启用 filesystem 才有图片落盘处理。
