"""Receive paired Android Bluetooth OPP pictures; never issue robot commands.

Run under dbus-run-session: obexd uses this private session bus, while the
adapter and numeric-comparison pairing agent use the system bus.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BLUEZ = 'org.bluez'
OBEX = 'org.bluez.obex'
PROPS = 'org.freedesktop.DBus.Properties'
OBJECTS = 'org.freedesktop.DBus.ObjectManager'
DEVICE = 'org.bluez.Device1'
ADAPTER = 'org.bluez.Adapter1'
TRANSFER = 'org.bluez.obex.Transfer1'
SESSION = 'org.bluez.obex.Session1'
OPP_UUID = '00001105-0000-1000-8000-00805f9b34fb'
MAX_BYTES = 32 * 1024 * 1024
EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}


def safe_label(value, limit=160):
    return ''.join(c for c in str(value) if c.isprintable())[:limit]


def validate_offer(properties, device, maximum=MAX_BYTES):
    """Header checks are preliminary; the inbox verifies the actual image."""
    if not device.get('Paired') or not device.get('Trusted'):
        raise ValueError('请先在板子屏幕上确认手机配对')
    name = safe_label(properties.get('Name', ''))
    mime = str(properties.get('Type', '')).lower().split(';', 1)[0]
    suffix = Path(name.replace('\\', '/')).suffix.lower()
    if suffix not in EXTENSIONS:
        raise ValueError('仅接收 JPG、PNG、WebP、BMP 或静态 GIF 图片')
    if mime and not (mime.startswith('image/') or mime == 'application/octet-stream'):
        raise ValueError('文件类型不是图片')
    size = properties.get('Size')
    if size is not None and (int(size) <= 0 or int(size) > maximum):
        raise ValueError('单张图片必须在 32 MiB 以内')
    return dict(source_name=name, size=None if size is None else int(size))


class Receipts:
    """Keep partial files invisible and commit only an explicit OBEX complete."""
    def __init__(self, directory, inbox, maximum=MAX_BYTES):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.inbox, self.maximum, self.active = inbox, maximum, {}

    def discard_old_partials(self):
        for path in self.directory.glob('*.part'):
            if path.is_file() or path.is_symlink():
                path.unlink()

    def begin(self, transfer, properties, device):
        offer = validate_offer(properties, device, self.maximum)
        if transfer in self.active:
            raise ValueError('前一张图片尚未接收完毕，请稍后重试')
        if len(self.active) >= 2:
            raise ValueError('已有图片正在接收，请稍后重试')
        if shutil.disk_usage(self.directory).free < (offer['size'] or self.maximum) + 8 * 1024 * 1024:
            raise ValueError('存储空间不足，无法接收图片')
        path = self.directory / (uuid.uuid4().hex + '.part')
        self.active[transfer] = dict(offer, path=path,
            sender=str(device['Address']), started=time.monotonic(), transferred=0)
        return str(path)

    def abort(self, transfer):
        receipt = self.active.pop(transfer, None)
        if receipt:
            try:
                receipt['path'].unlink()
            except FileNotFoundError:
                pass

    def complete(self, transfer):
        receipt = self.active.pop(transfer, None)
        if receipt is None:
            return None
        path = receipt['path']
        try:
            if path.is_symlink() or path.resolve().parent != self.directory:
                raise ValueError('接收文件路径无效')
            size = path.stat().st_size
            if not 0 < size <= self.maximum:
                raise ValueError('接收文件大小无效')
            if receipt['size'] is not None and size != receipt['size']:
                raise ValueError('图片未完整接收')
            return self.inbox.import_file(path, source_name=receipt['source_name'],
                                          sender=receipt['sender'])
        finally:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


class Receiver:
    def __init__(self, args, dbus, glib, inbox):
        self.args, self.dbus, self.glib = args, dbus, glib
        self.system, self.session = dbus.SystemBus(), dbus.SessionBus()
        self.loop = glib.MainLoop()
        self.receipts = Receipts(args.staging, inbox)
        self.receipts.discard_old_partials()
        self.pending, self.approved = None, {}
        self.pairing_deadline = 0.0
        self.adapter_path = None
        self.obex_process = None
        self.stopping = False
        self.fatal_error = False
        self.ready = False
        self.owner_bluez = self.owner_obex = None
        self.listener = None
        self.state = dict(schema='so101-bluetooth-v1', adapter_name=args.name,
            address='', powered=False, receiver_ready=False, last_error='',
            pairing_until=0, pending=None, received_count=0, last_received=None,
            active_transfers=0)
        args.run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def properties(self, bus, name, path):
        return self.dbus.Interface(bus.get_object(name, path, introspect=False), PROPS)

    def objects(self):
        return self.dbus.Interface(self.system.get_object(BLUEZ, '/', introspect=False),
                                   OBJECTS).GetManagedObjects()

    def publish(self):
        state = dict(self.state, receiver_ready=self.ready and self.state['powered'],
                     active_transfers=len(self.receipts.active), updated_at=time.time())
        if self.pending:
            state['pending'] = {k: self.pending[k] for k in
                                ('request_id', 'device_name', 'address', 'passkey', 'expires_at')}
        else:
            state['pending'] = None
        target = self.args.run_dir / 'status.json'
        temporary = target.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(state, stream, ensure_ascii=False)
        os.chmod(str(temporary), 0o600)
        os.replace(str(temporary), str(target))

    def error(self, message):
        self.state['last_error'] = safe_label(message, 400)
        print(self.state['last_error'], flush=True)
        self.publish()

    def adapter_set(self, key, value):
        self.properties(self.system, BLUEZ, self.adapter_path).Set(
            ADAPTER, key, value, signature='ssv')

    def device(self, path):
        return self.properties(self.system, BLUEZ, path).GetAll(DEVICE)

    def trusted_device(self, path):
        value = self.device(path)
        if (value.get('Paired') and path in self.approved and
                self.approved[path] > time.monotonic()):
            self.properties(self.system, BLUEZ, path).Set(
                DEVICE, 'Trusted', True, signature='ssv')
            value['Trusted'] = True
            del self.approved[path]
        return value

    def authorize_push(self, transfer):
        properties = self.properties(self.session, OBEX, transfer).GetAll(TRANSFER)
        session = self.properties(self.session, OBEX, properties['Session']).GetAll(SESSION)
        remote = str(session['Destination']).upper()
        if str(session['Source']).upper() != self.state['address'].upper():
            raise ValueError('接收请求来自其他适配器')
        for path, interfaces in self.objects().items():
            device = interfaces.get(DEVICE, {})
            if (str(device.get('Address', '')).upper() == remote and
                    str(device.get('Adapter', '')) == self.adapter_path):
                destination = self.receipts.begin(str(transfer), properties,
                                                  self.trusted_device(str(path)))
                self.state['last_error'] = ''
                self.publish()
                return destination
        raise ValueError('发送设备尚未配对')

    def transfer_changed(self, interface, changed, invalidated, path=None):
        path = str(path)
        if interface != TRANSFER or path not in self.receipts.active:
            return
        receipt = self.receipts.active[path]
        try:
            if 'Transferred' in changed:
                receipt['transferred'] = int(changed['Transferred'])
                if receipt['transferred'] > self.receipts.maximum:
                    self.cancel_transfer(path)
                    raise ValueError('传入图片超过 32 MiB，已取消')
            status = str(changed.get('Status', ''))
            if status == 'complete':
                record = self.receipts.complete(path)
                if record:
                    self.state['last_received'] = {key: str(record.get(key, '')) for key in
                                                   ('id', 'filename', 'source_name', 'received_at')}
                    self.state['received_count'] += 1
                    self.state['last_error'] = ''
            elif status == 'error':
                self.receipts.abort(path)
                raise ValueError('蓝牙传输中断，请从手机重新发送')
            self.publish()
        except Exception as exc:
            self.receipts.abort(path)
            self.error(exc)

    def interfaces_removed(self, path, interfaces):
        if TRANSFER in interfaces and str(path) in self.receipts.active:
            self.receipts.abort(str(path))
            self.error('蓝牙连接已断开，未完成的图片未加入接收箱')

    def cancel_transfer(self, path):
        try:
            self.dbus.Interface(self.session.get_object(OBEX, path, introspect=False),
                                TRANSFER).Cancel()
        finally:
            self.receipts.abort(path)

    def request_confirmation(self, device_path, passkey, reply, reject):
        if time.monotonic() >= self.pairing_deadline or self.pending:
            raise ValueError('请先在屏幕上开启配对，且一次只配对一台手机')
        value = self.device(device_path)
        self.pending = dict(request_id=uuid.uuid4().hex, device_path=str(device_path),
            device_name=safe_label(value.get('Alias', value.get('Address', '手机'))),
            address=str(value.get('Address', '')), passkey='%06d' % int(passkey),
            expires_at=time.time() + 45, deadline=time.monotonic() + 45,
            reply=reply, reject=reject)
        self.publish()

    def reject_pending(self, message='配对已取消'):
        pending, self.pending = self.pending, None
        if pending:
            pending['reject'](self.PairRejected(message))
        self.publish()

    def control(self, command):
        action = command.get('command')
        if action == 'status':
            self.publish()
            return dict(ok=True)
        if action == 'pair':
            if not self.ready or not self.state['powered']:
                raise ValueError('蓝牙接收服务尚未就绪')
            self.adapter_set('PairableTimeout', self.dbus.UInt32(120))
            self.adapter_set('DiscoverableTimeout', self.dbus.UInt32(120))
            self.adapter_set('Pairable', True)
            self.adapter_set('Discoverable', True)
            self.pairing_deadline = time.monotonic() + 120
            self.state['pairing_until'] = time.time() + 120
            self.state['last_error'] = ''
        elif action == 'stop_pair':
            self.close_pairing()
        elif action == 'confirm':
            pending = self.pending
            if (not pending or command.get('request_id') != pending['request_id'] or
                    time.monotonic() > pending['deadline']):
                raise ValueError('配对请求已失效，请在手机上重试')
            if command.get('accept') is not True:
                self.reject_pending('用户拒绝配对')
            else:
                self.pending = None
                self.approved[pending['device_path']] = time.monotonic() + 120
                pending['reply']()
        else:
            raise ValueError('不支持的蓝牙操作')
        self.publish()
        return dict(ok=True)

    def close_pairing(self):
        self.pairing_deadline = 0
        self.state['pairing_until'] = 0
        if self.adapter_path:
            self.adapter_set('Discoverable', False)
            self.adapter_set('Pairable', False)
        self.reject_pending()

    def control_worker(self):
        while not self.stopping:
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with client:
                client.settimeout(2)
                try:
                    _, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET,
                                                        socket.SO_PEERCRED, struct.calcsize('3i')))
                    if uid not in (0, os.getuid()):
                        raise ValueError('不允许的本机用户')
                    raw = b''
                    while b'\n' not in raw:
                        part = client.recv(1024)
                        if not part:
                            raise ValueError('蓝牙请求不完整')
                        raw += part
                        if len(raw) > 4096:
                            raise ValueError('蓝牙请求过长')
                    command = json.loads(raw.split(b'\n', 1)[0].decode('utf-8'))
                    if not isinstance(command, dict):
                        raise ValueError('蓝牙请求格式无效')
                    done, response = threading.Event(), {}
                    def execute(command=command, done=done, response=response):
                        try:
                            response.update(self.control(command))
                        except Exception as exc:
                            response.update(ok=False, error=safe_label(exc, 300))
                        done.set()
                        return False
                    self.glib.idle_add(execute)
                    if not done.wait(2):
                        raise ValueError('蓝牙服务响应超时')
                except Exception as exc:
                    response = dict(ok=False, error=safe_label(exc, 300))
                try:
                    client.sendall((json.dumps(response, ensure_ascii=False) + '\n').encode('utf-8'))
                except OSError:
                    pass

    def tick(self):
        try:
            now = time.monotonic()
            if self.obex_process.poll() is not None:
                raise RuntimeError('蓝牙文件服务退出，正在重启')
            if self.pairing_deadline and now >= self.pairing_deadline:
                self.close_pairing()
            if self.pending and now >= self.pending['deadline']:
                self.reject_pending('配对确认超时')
            for path in list(self.approved):
                if now > self.approved[path]:
                    del self.approved[path]
                else:
                    try:
                        self.trusted_device(path)
                    except self.dbus.DBusException:
                        self.approved.pop(path, None)
            for path, receipt in list(self.receipts.active.items()):
                oversized = (receipt['path'].exists() and
                             receipt['path'].stat().st_size > self.receipts.maximum)
                if now - receipt['started'] > 600 or oversized:
                    self.cancel_transfer(path)
                    self.error('图片接收超时或大小超限，已取消')
            adapter = self.properties(self.system, BLUEZ, self.adapter_path).GetAll(ADAPTER)
            self.state['powered'] = bool(adapter.get('Powered'))
            self.publish()
            return True
        except Exception as exc:
            self.error(exc)
            self.fatal_error = True
            self.loop.quit()
            return False

    def owner_changed(self, name, old, new):
        if name in (BLUEZ, OBEX) and old and str(old) != str(new):
            self.error('蓝牙服务连接已变化，正在重新初始化')
            self.fatal_error = True
            self.loop.quit()

    def start(self):
        self.owner_bluez = str(self.system.get_name_owner(BLUEZ))
        adapters = [(str(path), value[ADAPTER]) for path, value in self.objects().items()
                    if ADAPTER in value]
        if not adapters:
            raise RuntimeError('未发现蓝牙控制器，请检查模块驱动')
        self.adapter_path, adapter = sorted(adapters)[0]
        self.state['address'] = str(adapter['Address'])
        self.adapter_set('Powered', True)
        self.adapter_set('Alias', self.args.name)
        self.state['powered'] = True
        self.close_pairing()
        PairAgent, ObexAgent, self.PairRejected = make_agents(self.dbus)
        self.pair_agent = PairAgent(self)
        pair_manager = self.dbus.Interface(self.system.get_object(BLUEZ, '/org/bluez'),
                                           'org.bluez.AgentManager1')
        pair_manager.RegisterAgent(self.pair_agent.path, 'DisplayYesNo')
        pair_manager.RequestDefaultAgent(self.pair_agent.path)
        self.obex_process = subprocess.Popen([self.args.obexd, '--nodetach',
            '--plugin=bluetooth,opp,filesystem', '--root=' + str(self.args.staging)])
        for _ in range(100):
            if self.session.name_has_owner(OBEX):
                break
            if self.obex_process.poll() is not None:
                raise RuntimeError('obexd 启动失败')
            time.sleep(0.05)
        else:
            raise RuntimeError('obexd 未连接会话总线')
        self.owner_obex = str(self.session.get_name_owner(OBEX))
        self.obex_agent = ObexAgent(self)
        self.session.add_signal_receiver(self.transfer_changed, dbus_interface=PROPS,
            signal_name='PropertiesChanged', bus_name=OBEX, path_keyword='path')
        self.session.add_signal_receiver(self.interfaces_removed, dbus_interface=OBJECTS,
            signal_name='InterfacesRemoved', bus_name=OBEX)
        self.dbus.Interface(self.session.get_object(OBEX, '/org/bluez/obex'),
                            'org.bluez.obex.AgentManager1').RegisterAgent(self.obex_agent.path)
        for bus in (self.session, self.system):
            bus.add_signal_receiver(self.owner_changed, dbus_interface='org.freedesktop.DBus',
                signal_name='NameOwnerChanged', bus_name='org.freedesktop.DBus')
        socket_path = self.args.run_dir / 'control.sock'
        if socket_path.exists():
            socket_path.unlink()
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(socket_path))
        os.chmod(str(socket_path), 0o600)
        self.listener.listen(4)
        self.listener.settimeout(1)
        threading.Thread(target=self.control_worker, daemon=True).start()
        self.ready = True
        self.publish()
        self.glib.timeout_add_seconds(1, self.tick)

    def close(self):
        self.stopping, self.ready = True, False
        if self.listener:
            self.listener.close()
        try:
            self.close_pairing()
        except Exception:
            pass
        if self.obex_process and self.obex_process.poll() is None:
            self.obex_process.terminate()
            try:
                self.obex_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.obex_process.kill()
                self.obex_process.wait(timeout=3)
        for path in list(self.receipts.active):
            self.receipts.abort(path)
        self.publish()


def make_agents(dbus):
    class PairRejected(dbus.DBusException):
        _dbus_error_name = 'org.bluez.Error.Rejected'

    class PushRejected(dbus.DBusException):
        _dbus_error_name = 'org.bluez.obex.Error.Rejected'

    class PairAgent(dbus.service.Object):
        path = '/so101/bluetooth/pair_agent'

        def __init__(self, receiver):
            self.receiver = receiver
            super().__init__(receiver.system, self.path)

        def check(self, sender):
            if str(sender) != self.receiver.owner_bluez:
                raise PairRejected('Unexpected caller')

        @dbus.service.method('org.bluez.Agent1', in_signature='ou', out_signature='',
                             async_callbacks=('reply', 'reject'), sender_keyword='sender')
        def RequestConfirmation(self, device, passkey, reply, reject, sender=None):
            try:
                self.check(sender)
                self.receiver.request_confirmation(str(device), passkey, reply, reject)
            except Exception as exc:
                reject(PairRejected(str(exc)))

        @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='',
                             sender_keyword='sender')
        def AuthorizeService(self, device, service, sender=None):
            self.check(sender)
            value = self.receiver.trusted_device(str(device))
            if str(service).lower() != OPP_UUID or not value.get('Paired') or not value.get('Trusted'):
                raise PairRejected('Only paired image senders are allowed')

        @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='',
                             sender_keyword='sender')
        def RequestAuthorization(self, device, sender=None):
            self.check(sender)
            raise PairRejected('请使用支持数字确认的手机进行配对')

        @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='s',
                             sender_keyword='sender')
        def RequestPinCode(self, device, sender=None):
            self.check(sender)
            raise PairRejected('旧式 PIN 配对不受支持，请使用安卓手机数字确认')

        @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='u',
                             sender_keyword='sender')
        def RequestPasskey(self, device, sender=None):
            self.check(sender)
            raise PairRejected('请从安卓手机发起数字确认配对')

        @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='',
                             sender_keyword='sender')
        def Cancel(self, sender=None):
            self.check(sender)
            self.receiver.reject_pending()

        @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='',
                             sender_keyword='sender')
        def Release(self, sender=None):
            self.check(sender)
            self.receiver.fatal_error = True
            self.receiver.loop.quit()

    class ObexAgent(dbus.service.Object):
        path = '/so101/bluetooth/push_agent'

        def __init__(self, receiver):
            self.receiver = receiver
            super().__init__(receiver.session, self.path)

        def check(self, sender):
            if str(sender) != self.receiver.owner_obex:
                raise PushRejected('Unexpected caller')

        @dbus.service.method('org.bluez.obex.Agent1', in_signature='o', out_signature='s',
                             sender_keyword='sender')
        def AuthorizePush(self, transfer, sender=None):
            self.check(sender)
            try:
                return self.receiver.authorize_push(str(transfer))
            except Exception as exc:
                self.receiver.error(exc)
                raise PushRejected(str(exc))

        @dbus.service.method('org.bluez.obex.Agent1', in_signature='', out_signature='',
                             sender_keyword='sender')
        def Cancel(self, sender=None):
            self.check(sender)

        @dbus.service.method('org.bluez.obex.Agent1', in_signature='', out_signature='',
                             sender_keyword='sender')
        def Release(self, sender=None):
            self.check(sender)
            self.receiver.fatal_error = True
            self.receiver.loop.quit()

    return PairAgent, ObexAgent, PairRejected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path('/home/xilinx/so101_data_work107'))
    parser.add_argument('--run-dir', type=Path, default=Path('/run/so101-bluetooth'))
    parser.add_argument('--name', default='SO101-Draw')
    parser.add_argument('--obexd', default='/usr/lib/bluetooth/obexd')
    args = parser.parse_args()
    args.staging = args.data_dir / '.bluetooth_staging'
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    from gi.repository import GLib
    from bluetooth_inbox import BluetoothInbox
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    receiver = Receiver(args, dbus, GLib, BluetoothInbox(args.data_dir / 'bluetooth_images'))
    def stop(signum, frame):
        receiver.loop.quit()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        receiver.start()
        receiver.loop.run()
        return 1 if receiver.fatal_error else 0
    except Exception as exc:
        receiver.error(exc)
        return 1
    finally:
        receiver.close()


if __name__ == '__main__':
    raise SystemExit(main())
