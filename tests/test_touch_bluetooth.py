"""Pairing UI protocol and its six-digit, time-limited confirmation boundary."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from scripts.touch_bluetooth import pending_confirmation, read_status, send_command, show_bluetooth


class BluetoothProtocolTests(unittest.TestCase):
    def setUp(self):
        # The Windows test interpreter may lack AF_UNIX; transport is mocked here.
        family = patch('scripts.touch_bluetooth.socket.AF_UNIX', 1, create=True)
        family.start()
        self.addCleanup(family.stop)

    def test_status_missing_invalid_or_too_large_is_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'status.json'
            self.assertFalse(read_status(path)['receiver_ready'])
            for raw in ('bad json', '[]', ' ' * 65537):
                path.write_text(raw, encoding='utf-8')
                self.assertFalse(read_status(path)['receiver_ready'])
            path.write_text('{"receiver_ready": true}', encoding='utf-8')
            self.assertTrue(read_status(path)['receiver_ready'])

    def test_six_digits_and_unexpired_request_required(self):
        pending = dict(request_id='r1', passkey='001234', expires_at=101)
        self.assertEqual(pending_confirmation({'pending': pending}, now=100)['passkey'], '001234')
        self.assertIsNone(pending_confirmation({'pending': pending}, now=101))
        for invalid in ('1234', '1234567', 'xxxxxx', '１２３４５６'):
            self.assertIsNone(pending_confirmation({'pending': dict(pending, passkey=invalid)}, now=100))
        self.assertIsNone(pending_confirmation({'pending': dict(pending, request_id='')}, now=100))

    def test_pairing_is_always_120_seconds_and_reads_fragmented_response(self):
        connection = MagicMock()
        connection.recv.side_effect = [b'{"ok":', b'true}\n']
        connection.__enter__.return_value = connection
        with patch('scripts.touch_bluetooth.socket.socket', return_value=connection):
            self.assertTrue(send_command('pair', seconds=10000)['ok'])
        payload = json.loads(connection.sendall.call_args.args[0])
        self.assertEqual(payload, dict(command='pair', seconds=120))
        connection.settimeout.assert_called_once_with(1.5)

    def test_confirmation_keeps_request_id_and_rejection(self):
        connection = MagicMock(); connection.recv.return_value = b'{"ok":true}\n'
        connection.__enter__.return_value = connection
        with patch('scripts.touch_bluetooth.socket.socket', return_value=connection):
            send_command('confirm', request_id='specific-request', accept=False)
        self.assertEqual(json.loads(connection.sendall.call_args.args[0]),
                         dict(command='confirm', request_id='specific-request', accept=False))

    def test_error_and_unterminated_reply_are_reported(self):
        for chunks, expected in (([b'{"ok":false,"error":"expired"}\n'], RuntimeError),
                                 ([b''], OSError), ([b'x' * 65537], ValueError)):
            connection = MagicMock(); connection.recv.side_effect = chunks
            connection.__enter__.return_value = connection
            with patch('scripts.touch_bluetooth.socket.socket', return_value=connection):
                with self.assertRaises(expected): send_command('pair')

    def test_unknown_command_never_connects(self):
        with patch('scripts.touch_bluetooth.socket.socket') as socket:
            with self.assertRaises(ValueError): send_command('execute')
            socket.assert_not_called()


class BluetoothWindowTests(unittest.TestCase):
    def test_window_preview_and_close_never_start_work_or_stop_receiver(self):
        import tkinter as tk
        import time
        from types import SimpleNamespace
        from bluetooth_inbox import BluetoothInbox
        from test_bluetooth_inbox import image_bytes
        from test_studio_jobs import DeferredThreads
        try: root = tk.Tk()
        except tk.TclError as exc: self.skipTest(str(exc))
        try:
            root.withdraw()
            with tempfile.TemporaryDirectory() as directory:
                inbox = BluetoothInbox(directory)
                inbox.import_bytes(image_bytes(), source_name='测试.png')
                app = SimpleNamespace(root=root, bluetooth_inbox=inbox,
                                      _drawing_busy=Mock(return_value=False), _use_bluetooth_image=Mock())
                pending = dict(request_id='r1', device_name='安卓手机', passkey='001234', expires_at=time.time()+120)
                status = dict(adapter_name='SO101-Draw', powered=True, receiver_ready=True, pending=pending)
                threads = DeferredThreads()
                with patch('scripts.touch_bluetooth.threading.Thread', threads.thread), \
                        patch('scripts.touch_bluetooth.read_status', return_value=status), \
                        patch('scripts.touch_bluetooth.send_command') as command:
                    win = show_bluetooth(app)
                    threads.run_next(); root.update()
                    def descendants(widget):
                        for child in widget.winfo_children():
                            yield child
                            yield from descendants(child)
                    labels = [str(w.cget('text')) for w in descendants(win) if w.winfo_class() == 'TLabel']
                    self.assertTrue(any('001234' in text for text in labels))
                    buttons = {str(w.cget('text')): w for w in descendants(win) if w.winfo_class() == 'TButton'}
                    self.assertEqual(str(buttons['数字一致，确认'].cget('state')), 'normal')
                    app._use_bluetooth_image.assert_not_called()
                    buttons['关闭'].invoke()
                    self.assertIsNone(app._bluetooth_window)
                    command.assert_not_called()
        finally:
            root.destroy()


if __name__ == '__main__': unittest.main()
