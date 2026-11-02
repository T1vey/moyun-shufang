"""Receiver lifecycle and pairing policy without Bluetooth hardware or motion."""
import json
import io
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.bluetooth_receiver import MAX_BYTES, Receiver, Receipts, validate_offer
from bluetooth_inbox import BluetoothInbox


DEVICE = dict(Paired=True, Trusted=True, Address='01:02:03:04:05:06')


class ReceiverPolicyTests(unittest.TestCase):
    def test_unpaired_and_untrusted_senders_rejected(self):
        offer = dict(Name='photo.jpg', Type='image/jpeg', Size=100)
        for change in ({'Paired': False}, {'Trusted': False}):
            with self.assertRaises(ValueError):
                validate_offer(offer, dict(DEVICE, **change))

    def test_reject_non_images_and_oversize_before_receiving(self):
        for offer in (dict(Name='run.py', Type='image/png'),
                      dict(Name='photo.png', Type='text/plain'),
                      dict(Name='huge.png', Size=MAX_BYTES + 1),
                      dict(Name='empty.jpg', Size=0)):
            with self.assertRaises(ValueError):
                validate_offer(offer, DEVICE)
        self.assertIsNone(validate_offer(dict(Name='a.jpg'), DEVICE)['size'])

    def test_partial_not_imported_cancel_cleans_and_same_transfer_can_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = Mock()
            receipts = Receipts(directory, inbox)
            first = Path(receipts.begin('/transfer1', dict(Name='a.jpg', Size=3), DEVICE))
            first.write_bytes(b'123')
            inbox.import_file.assert_not_called()
            receipts.abort('/transfer1')
            self.assertFalse(first.exists())
            second = Path(receipts.begin('/transfer1', dict(Name='a.jpg', Size=3), DEVICE))
            self.assertNotEqual(first, second)
            second.write_bytes(b'456')
            receipts.complete('/transfer1')
            inbox.import_file.assert_called_once_with(second, source_name='a.jpg',
                                                       sender=DEVICE['Address'])
            self.assertFalse(second.exists())
            receipts.complete('/transfer1')
            self.assertEqual(inbox.import_file.call_count, 1)
            third = Path(receipts.begin('/transfer1', dict(Name='a.jpg', Size=3), DEVICE))
            third.write_bytes(b'789')
            receipts.complete('/transfer1')
            self.assertEqual(inbox.import_file.call_count, 2)

    def test_size_mismatch_and_decoder_rejection_clean_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = Mock()
            receipts = Receipts(directory, inbox, maximum=16)
            path = Path(receipts.begin('/x', dict(Name='a.png', Size=4), DEVICE))
            path.write_bytes(b'123')
            with self.assertRaises(ValueError): receipts.complete('/x')
            inbox.import_file.assert_not_called()
            self.assertFalse(path.exists())
            path = Path(receipts.begin('/x', dict(Name='a.png'), DEVICE))
            path.write_bytes(b'not really image')
            inbox.import_file.side_effect = ValueError('Invalid pixels')
            with self.assertRaises(ValueError): receipts.complete('/x')
            self.assertFalse(path.exists())
            self.assertEqual(receipts.active, {})

    def test_remote_path_is_never_used_for_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            receipts = Receipts(directory, Mock())
            path = Path(receipts.begin('/x', dict(Name='../../escape.jpg'), DEVICE))
            self.assertEqual(path.parent, Path(directory).resolve())
            self.assertEqual(path.suffix, '.part')
            self.assertNotIn('escape', path.name)

    def test_restart_only_cleans_private_partials(self):
        with tempfile.TemporaryDirectory() as directory:
            partial = Path(directory) / 'old.part'; partial.write_bytes(b'x')
            other = Path(directory) / 'keep.png'; other.write_bytes(b'y')
            receipts = Receipts(directory, Mock())
            receipts.discard_old_partials()
            self.assertFalse(partial.exists())
            self.assertTrue(other.exists())

    def test_actual_inbox_commit_only_after_complete_and_invalid_pixels_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = BluetoothInbox(Path(directory) / 'library')
            receipts = Receipts(Path(directory) / 'staging', inbox)
            stream = io.BytesIO()
            Image.new('RGB', (16, 12), 'red').save(stream, format='PNG')
            raw = stream.getvalue()
            path = Path(receipts.begin('/x', dict(Name='手机.png', Size=len(raw)), DEVICE))
            path.write_bytes(raw)
            self.assertEqual(inbox.records(), [])
            saved = receipts.complete('/x')
            self.assertEqual(inbox.get(saved['id'])['path'].read_bytes(), raw)
            self.assertFalse(path.exists())
            path = Path(receipts.begin('/x', dict(Name='假图片.png'), DEVICE))
            path.write_bytes(b'not an image')
            with self.assertRaises((OSError, ValueError)): receipts.complete('/x')
            self.assertEqual(len(inbox.records()), 1)
            self.assertFalse(path.exists())


class PairConfirmationTests(unittest.TestCase):
    def receiver(self):
        receiver = object.__new__(Receiver)
        receiver.pending = None
        receiver.approved = {}
        receiver.pairing_deadline = time.monotonic() + 120
        receiver.device = Mock(return_value=dict(DEVICE, Alias='Android'))
        receiver.publish = Mock()
        receiver.PairRejected = ValueError
        return receiver

    def test_confirmation_waits_for_current_screen_request(self):
        receiver = self.receiver()
        reply, reject = Mock(), Mock()
        receiver.request_confirmation('/device', 42, reply, reject)
        self.assertEqual(receiver.pending['passkey'], '000042')
        reply.assert_not_called()
        with self.assertRaises(ValueError):
            receiver.control(dict(command='confirm', request_id='stale', accept=True))
        reply.assert_not_called()
        identifier = receiver.pending['request_id']
        receiver.control(dict(command='confirm', request_id=identifier, accept=True))
        reply.assert_called_once_with()
        reject.assert_not_called()
        self.assertIsNone(receiver.pending)
        self.assertIn('/device', receiver.approved)

    def test_rejection_and_timeout_never_approve_device(self):
        receiver = self.receiver()
        reply, reject = Mock(), Mock()
        receiver.request_confirmation('/device', 123456, reply, reject)
        identifier = receiver.pending['request_id']
        receiver.control(dict(command='confirm', request_id=identifier, accept=False))
        reject.assert_called_once()
        reply.assert_not_called()
        self.assertEqual(receiver.approved, {})
        receiver.pairing_deadline = time.monotonic() - 1
        with self.assertRaises(ValueError):
            receiver.request_confirmation('/device', 123456, reply, reject)

    def test_trust_requires_both_screen_approval_and_successful_bond(self):
        receiver = self.receiver()
        receiver.system = Mock()
        properties = Mock()
        receiver.properties = Mock(return_value=properties)
        receiver.device.return_value = dict(DEVICE, Paired=False, Trusted=False)
        receiver.approved['/device'] = time.monotonic() + 100
        self.assertFalse(receiver.trusted_device('/device')['Trusted'])
        properties.Set.assert_not_called()
        receiver.device.return_value = dict(DEVICE, Paired=True, Trusted=False)
        self.assertTrue(receiver.trusted_device('/device')['Trusted'])
        properties.Set.assert_called_once_with('org.bluez.Device1', 'Trusted', True, signature='ssv')
        self.assertNotIn('/device', receiver.approved)


if __name__ == '__main__':
    unittest.main()
