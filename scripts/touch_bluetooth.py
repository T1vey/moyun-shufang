"""Touch-friendly Bluetooth inbox and local pairing confirmation, with no motion."""
import json
from pathlib import Path
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk

from scripts.touch_ui import fit_window

STATUS_PATH = Path('/run/so101-bluetooth/status.json')
CONTROL_PATH = Path('/run/so101-bluetooth/control.sock')


def read_status(path=STATUS_PATH):
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError('status too large')
        status = json.loads(raw.decode('utf-8'))
        if not isinstance(status, dict):
            raise ValueError('invalid status')
        return status
    except (OSError, ValueError):
        return dict(powered=False, receiver_ready=False, pending=None,
                    last_error='蓝牙接收服务尚未就绪')


def send_command(command, *, control_path=CONTROL_PATH, **fields):
    if command not in ('pair', 'confirm', 'stop_pair', 'status'):
        raise ValueError('不支持的蓝牙命令')
    payload = dict(fields, command=command)
    if command == 'pair':
        payload['seconds'] = 120
    family = getattr(socket, 'AF_UNIX', None)
    if family is None:
        raise RuntimeError('蓝牙配对控制仅在板端运行')
    with socket.socket(family, socket.SOCK_STREAM) as connection:
        connection.settimeout(1.5)
        connection.connect(str(control_path))
        connection.sendall((json.dumps(payload) + '\n').encode('utf-8'))
        raw = bytearray()
        while b'\n' not in raw:
            chunk = connection.recv(4096)
            if not chunk:
                raise OSError('蓝牙服务未返回结果')
            raw.extend(chunk)
            if len(raw) > 65536:
                raise ValueError('蓝牙服务返回内容过大')
    result = json.loads(bytes(raw).split(b'\n', 1)[0].decode('utf-8'))
    if not isinstance(result, dict) or not result.get('ok'):
        raise RuntimeError(str(result.get('error', '蓝牙操作失败')) if isinstance(result, dict) else '蓝牙操作失败')
    return result


def pending_confirmation(status, now=None):
    pending = status.get('pending')
    now = time.time() if now is None else now
    if not isinstance(pending, dict):
        return None
    try:
        code = str(pending.get('passkey', ''))
        if (not isinstance(pending.get('request_id'), str) or not pending['request_id'] or
                len(code) != 6 or not code.isascii() or not code.isdecimal() or
                float(pending['expires_at']) <= now):
            return None
    except (TypeError, ValueError, KeyError):
        return None
    return dict(pending, passkey=code)


def show_bluetooth(app):
    previous = getattr(app, '_bluetooth_window', None)
    if previous is not None and previous.winfo_exists():
        previous.lift()
        return previous
    root = app.root
    win = tk.Toplevel(root)
    app._bluetooth_window = win
    win.title('蓝牙收图')
    fit_window(win, root, 1000, 550)
    win.transient(root)
    area = ttk.Frame(win, padding=10)
    area.pack(fill='both', expand=True)
    status_var = tk.StringVar(value='读取蓝牙状态…')
    ttk.Label(area, textvariable=status_var, wraplength=950).pack(fill='x')
    pairing = ttk.Frame(area)
    pairing.pack(fill='x', pady=5)
    message_var = tk.StringVar(value='安卓手机：先配对，再在相册中选择图片 → 分享 → 蓝牙 → 选择本板。')
    ttk.Label(area, textvariable=message_var, wraplength=950).pack(fill='x')
    confirmation = ttk.LabelFrame(area, text='配对确认', padding=6)
    confirm_var = tk.StringVar(value='没有待确认的配对请求')
    ttk.Label(confirmation, textvariable=confirm_var, font=('DejaVu Sans', 14, 'bold'),
              wraplength=720).pack(side='left', fill='x', expand=True)
    confirmation.pack(fill='x', pady=5)
    body = ttk.Frame(area)
    body.pack(fill='both', expand=True, pady=5)
    listing = ttk.Frame(body)
    listing.pack(side='left', fill='both', expand=True)
    tree = ttk.Treeview(listing, columns=('time', 'name'), show='headings', selectmode='browse', height=5)
    tree.heading('time', text='接收时间'); tree.column('time', width=165, stretch=False)
    tree.heading('name', text='原图片名'); tree.column('name', width=220)
    scroll = ttk.Scrollbar(listing, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side='left', fill='both', expand=True); scroll.pack(side='right', fill='y')
    right = ttk.Frame(body, width=360)
    right.pack(side='right', fill='both', padx=(10, 0))
    preview = ttk.Label(right, text='收到图片后在这里预览', anchor='center')
    preview.pack(fill='both', expand=True)
    details = ttk.Label(right, text='', wraplength=350)
    details.pack(fill='x')
    footer = ttk.Frame(area); footer.pack(fill='x')
    count = ttk.Label(footer, text='接收箱为空'); count.pack(side='left')
    state = dict(closed=False, command_busy=False, polling=False, records={}, pending=None,
                 timer=None, signature=None, status={})

    def selected():
        ids = tree.selection()
        return state['records'].get(ids[0]) if ids else None

    def update_buttons():
        busy = state['command_busy']
        pending = state['pending']
        accept.configure(state='normal' if pending and not busy else 'disabled')
        reject.configure(state='normal' if pending and not busy else 'disabled')
        ready = state['status'].get('powered') and state['status'].get('receiver_ready')
        pair.configure(state='normal' if ready and not busy else 'disabled')
        stop_pair.configure(state='normal' if ready and not busy else 'disabled')
        use.configure(state='normal' if selected() and not app._drawing_busy() else 'disabled')

    def preview_selected(_event=None):
        record = selected()
        if record is None:
            preview.configure(image='', text='收到图片后在这里预览'); preview.image = None
            details.configure(text=''); update_buttons(); return
        try:
            from PIL import Image, ImageOps, ImageTk
            verified = app.bluetooth_inbox.get(record['id'])
            with Image.open(verified['path']) as source:
                thumbnail = ImageOps.exif_transpose(source).convert('RGB')
                thumbnail.thumbnail((330, 190))
            photo = ImageTk.PhotoImage(thumbnail, master=win)
            preview.configure(image=photo, text=''); preview.image = photo
            details.configure(text='%s\n%d × %d 像素' %
                              (record['source_name'] or record['filename'], record['width'], record['height']))
        except (OSError, ValueError) as exc:
            preview.configure(image='', text='无法预览：' + str(exc)); preview.image = None
            details.configure(text='')
        update_buttons()

    def request(command, **fields):
        if state['command_busy']:
            return
        state['command_busy'] = True; update_buttons()
        def worker():
            try:
                send_command(command, **fields)
                message = {'pair': '已开放配对 120 秒，请在手机蓝牙列表中选择本板。',
                           'confirm': '已提交配对确认结果。', 'stop_pair': '已关闭新设备配对。'}.get(command, '操作完成')
            except (OSError, ValueError, RuntimeError) as exc:
                message = '蓝牙操作失败：' + str(exc)
            def done():
                if state['closed']:
                    return
                state['command_busy'] = False
                message_var.set(message); update_buttons()
            try: root.after(0, done)
            except (RuntimeError, tk.TclError): pass
        threading.Thread(target=worker, daemon=True).start()

    def confirm(accepted):
        pending = pending_confirmation(state['status'])
        if pending is not None:
            request('confirm', request_id=pending['request_id'], accept=accepted)

    def use_selected():
        record = selected()
        if record and app._use_bluetooth_image(record):
            close()

    pair = ttk.Button(pairing, text='允许手机配对（120 秒）', command=lambda: request('pair'))
    pair.pack(side='left')
    stop_pair = ttk.Button(pairing, text='关闭配对', command=lambda: request('stop_pair'))
    stop_pair.pack(side='left', padx=6)
    reject = ttk.Button(confirmation, text='拒绝', command=lambda: confirm(False))
    reject.pack(side='right', padx=4)
    accept = ttk.Button(confirmation, text='数字一致，确认', command=lambda: confirm(True))
    accept.pack(side='right', padx=4)
    use = ttk.Button(footer, text='使用此图片', command=use_selected)
    use.pack(side='right', padx=5)

    def close():
        state['closed'] = True
        if state['timer'] is not None:
            try: root.after_cancel(state['timer'])
            except tk.TclError: pass
        app._bluetooth_window = None
        win.destroy()
        # The receiver is an independent service and continues after closing this window.

    ttk.Button(footer, text='关闭', command=close).pack(side='right', padx=5)
    win.protocol('WM_DELETE_WINDOW', close)
    tree.bind('<<TreeviewSelect>>', preview_selected)

    def apply_snapshot(status, records):
        if state['closed']:
            return
        state['polling'] = False; state['status'] = status
        pending = pending_confirmation(status); state['pending'] = pending
        name = str(status.get('adapter_name') or 'SO101')
        ready = status.get('powered') and status.get('receiver_ready')
        try: remaining = max(0, int(float(status.get('pairing_until', 0)) - time.time()))
        except (ValueError, TypeError): remaining = 0
        text = ('%s · 可以接收已配对手机的图片' % name) if ready else '%s · 接收服务未就绪' % name
        if remaining: text += ' · 允许新设备配对：剩余 %d 秒' % remaining
        elif ready: text += ' · 新手机请先点击“允许手机配对”'
        if status.get('last_error'): text += '\n' + str(status['last_error'])[:220]
        status_var.set(text)
        confirm_var.set(('%s\n%s  ← 请核对手机显示的六位数字' %
                         (pending.get('device_name') or pending.get('address') or '手机', pending['passkey']))
                        if pending else '没有待确认的配对请求')
        signature = tuple((r['id'], r['sha256']) for r in records)
        if signature != state['signature']:
            old = selected(); old_id = old['id'] if old else None
            state['signature'] = signature
            tree.delete(*tree.get_children()); state['records'] = {r['id']: r for r in records}
            for record in records:
                tree.insert('', 'end', iid=record['id'], values=(record['received_at'][:19].replace('T', ' '),
                                                               record['source_name'] or record['filename']))
            count.configure(text='已接收 %d 张；选择后再点击“使用此图片”' % len(records))
            identity = old_id if old_id in state['records'] else records[0]['id'] if records else None
            if identity: tree.selection_set(identity); tree.focus(identity)
            preview_selected()
        update_buttons()
        state['timer'] = root.after(1000, poll)

    def poll():
        if state['closed'] or state['polling']:
            return
        state['polling'] = True
        def worker():
            status = read_status()
            try: records = app.bluetooth_inbox.records()
            except OSError as exc:
                records = []; status['last_error'] = '读取接收箱失败：' + str(exc)
            try: root.after(0, lambda: apply_snapshot(status, records))
            except (RuntimeError, tk.TclError): pass
        threading.Thread(target=worker, daemon=True).start()
    update_buttons(); poll()
    return win
