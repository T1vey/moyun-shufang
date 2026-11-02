"""NetworkManager STA controls; never change wired Ethernet profiles."""
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import ttk
from scripts.touch_ui import fit_window


def wifi_devices():
    result = subprocess.run(['nmcli', '-t', '-f', 'DEVICE,TYPE', 'device', 'status'],
                            capture_output=True, text=True, timeout=10, check=True)
    return [line.rsplit(':', 1)[0] for line in result.stdout.splitlines()
            if line.endswith(':wifi')]


def connect_wifi(device, ssid, password):
    if device not in wifi_devices() or not ssid or '\n' in ssid or '\n' in password:
        raise ValueError('请选择无线接口并填写有效 SSID')
    # --ask reads the secret from stdin, keeping it out of process arguments/logs.
    completed = subprocess.run(['nmcli', '--ask', '--wait', '35', 'device', 'wifi',
                                'connect', ssid, 'ifname', device, 'private', 'yes'],
                               input=password + '\n', capture_output=True, text=True, timeout=45)
    if completed.returncode:
        raise RuntimeError('连接失败，请检查密码、信号和 NetworkManager 授权（退出码 %d）' % completed.returncode)


def show_network(root):
    win = tk.Toplevel(root); win.title('Wi-Fi 网络')
    fit_window(win, root, 850, 500)
    area = ttk.Frame(win, padding=18); area.pack(fill='both', expand=True)
    status = tk.StringVar(value='选择无线接口，填写路由器 SSID 和密码。已保存网络可留空密码。')
    ttk.Label(area,textvariable=status,wraplength=780).pack(fill='x',pady=8)
    values = []
    if shutil.which('nmcli'):
        try: values = wifi_devices()
        except Exception: status.set('无法读取 NetworkManager 状态')
    else: status.set('尚未安装 NetworkManager')
    fields=[]
    for label, secret in [('无线接口',False),('SSID',False),('密码',True)]:
        ttk.Label(area,text=label).pack(anchor='w')
        field=ttk.Combobox(area,values=values,state='readonly') if not fields else ttk.Entry(area,show='*' if secret else '')
        field.pack(fill='x',pady=5);fields.append(field)
    if values: fields[0].set(values[0])
    else: status.set('未检测到无线接口，请先检查 USB 模块与驱动。')
    def apply():
        device,ssid,password=[f.get() for f in fields]
        fields[2].delete(0,'end');button.configure(state='disabled');status.set('连接中…')
        def worker():
            try: connect_wifi(device,ssid,password); message='Wi-Fi 已连接。云端调用前请确认系统时间正确。'
            except Exception as e: message=str(e)
            def done():
                if win.winfo_exists():status.set(message);button.configure(state='normal')
            try: root.after(0,done)
            except RuntimeError: pass
        threading.Thread(target=worker,daemon=True).start()
    button=ttk.Button(area,text='连接 Wi-Fi',command=apply,state='normal' if values else 'disabled');button.pack(pady=10)
    if hasattr(root,'so101_keyboard'):
        ttk.Button(area,text='输入键盘',command=root.so101_keyboard.show).pack(pady=5)
    ttk.Button(area,text='关闭',command=win.destroy).pack()
