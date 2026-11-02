"""Offline process/GC/lease tests; these never import PYNQ or touch hardware."""
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import weakref

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_planner_accel_backend import FakeAllocator, FakeMMIO, REGS, ROOT, sample_inputs
from planner_accel_backend import PynqPlannerAccel, _INFLIGHT, _INFLIGHT_LOCK
from planner_accel_lease import acquire_planner_lease
import planner_accel_contract as contract


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline: raise AssertionError('test condition timed out')
        time.sleep(.01)


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = self.directory.name

    def test_same_physical_ip_is_exclusive_and_other_ip_is_independent(self):
        lease = acquire_planner_lease(0x40000000, self.path)
        self.addCleanup(lease.close)
        with self.assertRaises((OSError, RuntimeError)):
            acquire_planner_lease(0x40000000, self.path)
        with acquire_planner_lease(0x40010000, self.path): pass
        lease.close()
        with acquire_planner_lease(0x40000000, self.path): pass

    def test_subprocess_cannot_take_live_owner_lease(self):
        with acquire_planner_lease(0x40000000, self.path):
            child = subprocess.run([sys.executable, '-c',
                'from planner_accel_lease import acquire_planner_lease; '
                'import sys; acquire_planner_lease(0x40000000,sys.argv[1])', self.path],
                cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(child.returncode, 0)
        with acquire_planner_lease(0x40000000, self.path): pass

    def test_pending_context_defers_close_until_proven_drain(self):
        with acquire_planner_lease(0x40000000, self.path) as lease:
            lease.mark_inflight(7, 13)
            with self.assertRaisesRegex(RuntimeError, 'in-flight'): lease.close()
        self.assertTrue(lease.marker.exists()); lease.assert_owned()
        lease.mark_drained()
        self.assertFalse(lease.marker.exists())
        with self.assertRaises(RuntimeError): lease.assert_owned()
        with acquire_planner_lease(0x40000000, self.path): pass

    def test_force_exit_leaves_marker_and_blocks_next_process(self):
        child = subprocess.run([sys.executable, '-c',
            'from planner_accel_lease import acquire_planner_lease; import os,sys; '
            'lease=acquire_planner_lease(0x40000000,sys.argv[1]); '
            'lease.mark_inflight(7,13); os._exit(23)', self.path],
            cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(child.returncode, 23)
        marker = Path(self.path) / 'ip-40000000.inflight.json'
        self.assertEqual(json.loads(marker.read_text())['generation'], 13)
        with self.assertRaisesRegex(RuntimeError, 'stale in-flight marker'):
            acquire_planner_lease(0x40000000, self.path)


class TransportLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = self.directory.name

    def backend(self, timeout=.01, lease=None):
        allocator = FakeAllocator(); mmio = FakeMMIO(allocator)
        backend = PynqPlannerAccel(mmio=mmio, registers=REGS, allocator=allocator,
            timeout_s=timeout, lease_directory=self.path, lease=lease)
        def drain():
            mmio.stuck = False
            transport = backend.transport
            if transport.inflight: transport.release_after_idle()
            transport.close()
            if transport._guardian: transport._guardian.join(2)
        self.addCleanup(drain)
        return allocator, mmio, backend

    def test_two_pynq_instances_cannot_share_physical_ip_or_borrowed_lease(self):
        with acquire_planner_lease(0x40000000, self.path) as lease:
            allocator, mmio, backend = self.backend(lease=lease)
            other_allocator = FakeAllocator()
            with self.assertRaises((OSError, RuntimeError)):
                PynqPlannerAccel(mmio=FakeMMIO(other_allocator), registers=REGS,
                    allocator=other_allocator, lease_directory=self.path)
            with self.assertRaisesRegex(RuntimeError, 'live transport'):
                PynqPlannerAccel(mmio=FakeMMIO(other_allocator), registers=REGS,
                    allocator=other_allocator, lease=lease)
            self.assertFalse(other_allocator.buffers)
            backend.transport.close()
            # Closing a borrower must not release the loader's platform lease.
            lease.assert_owned()

    def test_wrong_physical_base_rejected_before_allocation(self):
        with acquire_planner_lease(0x40010000, self.path) as lease:
            allocator = FakeAllocator()
            with self.assertRaisesRegex(ValueError, 'another physical IP'):
                PynqPlannerAccel(mmio=FakeMMIO(allocator), registers=REGS, allocator=allocator, lease=lease)
            self.assertFalse(allocator.buffers)

    def test_overlapping_physical_buffers_rejected_and_released_before_start(self):
        class Overlapping(FakeAllocator):
            def __call__(self,shape,dtype):
                buffer=super().__call__(shape,dtype)
                buffer.device_address=self.base
                return buffer
        allocator=Overlapping();mmio=FakeMMIO(allocator)
        with self.assertRaisesRegex(ValueError,'must not overlap'):
            PynqPlannerAccel(mmio=mmio,registers=REGS,allocator=allocator,lease_directory=self.path)
        self.assertEqual(mmio.starts,0)
        self.assertEqual(len(allocator.buffers),5)
        self.assertTrue(all(buffer.freed for buffer in allocator.buffers.values()))
        with acquire_planner_lease(0x40000000,self.path):pass

    def test_inherited_pid_cannot_execute_close_or_drain(self):
        allocator, mmio, backend = self.backend()
        _, _, _, ctx, inputs = sample_inputs()
        before = list(allocator.events)
        with patch('planner_accel_backend.os.getpid', return_value=os.getpid()+1):
            for action in (backend.transport.close, backend.transport.release_after_idle,
                lambda: backend.transport.execute(ctx,contract.IK_CHAIN,inputs,7,13)):
                with self.assertRaisesRegex(RuntimeError, 'inherited'): action()
        self.assertEqual(allocator.events, before)
        self.assertFalse(any(buffer.freed for buffer in allocator.buffers.values()))

    def test_launch_marker_exists_before_doorbell_and_is_removed_after_idle(self):
        allocator, mmio, backend = self.backend()
        transport = backend.transport; original = mmio.write
        def checked_write(offset, value):
            if offset == 0:
                self.assertTrue(transport.lease.marker.exists())
                self.assertIs(_INFLIGHT[id(transport)], transport)
                self.assertFalse(transport._guardian.daemon)
            return original(offset, value)
        mmio.write = checked_write
        _, _, _, ctx, inputs = sample_inputs()
        transport.execute(ctx,contract.IK_CHAIN,inputs,7,13)
        self.assertFalse(transport.lease.marker.exists())
        self.assertNotIn(id(transport), _INFLIGHT)
        self.assertGreater(transport.write_s, 0)
        self.assertGreater(transport.wait_s, 0)
        self.assertGreater(transport.read_s, 0)

    def test_backend_metrics_include_transport_phases_even_on_timeout(self):
        allocator,mmio,backend=self.backend(timeout=.001)
        _,_,_,ctx,inputs=sample_inputs()
        backend._execute(ctx,contract.IK_CHAIN,inputs,None)
        first=backend.metrics()
        self.assertTrue(first['ddr_phase_timing_available'])
        self.assertEqual(first['transport'],'m_axi_DDR')
        for field in ('write_s','wait_s','read_s'):
            self.assertEqual(first[field],getattr(backend.transport,field))
            self.assertGreater(first[field],0)
        mmio.stuck=True
        with self.assertRaises(FloatingPointError):backend._execute(ctx,contract.IK_CHAIN,inputs,None)
        second=backend.metrics()
        self.assertGreater(second['wait_s'],first['wait_s'])
        self.assertGreater(second['total_s'],first['total_s'])
        self.assertTrue(second['faulted'])

    def test_fsync_failure_before_launch_fails_closed_without_doorbell(self):
        allocator, mmio, backend = self.backend()
        transport = backend.transport
        _, _, _, ctx, inputs = sample_inputs()
        with patch('planner_accel_lease._sync_directory', side_effect=OSError('test fsync failure')):
            with self.assertRaises(OSError): transport.execute(ctx,contract.IK_CHAIN,inputs,7,13)
        self.assertEqual(mmio.starts,0)
        self.assertTrue(transport.lease.marker.exists())
        self.assertTrue(transport.lease.pending)
        # The test explicitly proves idle before cleanup; no marker is removed
        # automatically after failure just because the launch count is zero.
        transport.release_after_idle()

    def test_keyboard_interrupt_after_launch_cancels_and_retains_until_idle(self):
        allocator, mmio, backend = self.backend(timeout=.001)
        transport = backend.transport; mmio.stuck = True
        _, _, _, ctx, inputs = sample_inputs()
        def cancelled(): raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            transport.execute(ctx,contract.IK_CHAIN,inputs,7,13,cancelled)
        self.assertTrue(transport.inflight)
        self.assertEqual(int(transport.buffers['cancel_words'][0]), (7 << 32) | 13)
        self.assertTrue(transport.lease.marker.exists())
        self.assertFalse(any(buffer.freed for buffer in allocator.buffers.values()))

    def test_gc_of_last_client_keeps_ddr_and_lease_until_guardian_observes_idle(self):
        # No cleanup closure may retain the transport in this test.
        allocator = FakeAllocator(); mmio = FakeMMIO(allocator); mmio.stuck = True
        backend = PynqPlannerAccel(mmio=mmio, registers=REGS, allocator=allocator,
            timeout_s=.001, lease_directory=self.path)
        reference = weakref.ref(backend.transport); identity = id(backend.transport)
        _, _, _, ctx, inputs = sample_inputs()
        try:
            with self.assertRaises(FloatingPointError):
                backend.transport.execute(ctx,contract.IK_CHAIN,inputs,7,13)
            guardian=backend.transport._guardian
            del backend; gc.collect()
            self.assertIsNotNone(reference())
            with _INFLIGHT_LOCK: self.assertIn(identity, _INFLIGHT)
            self.assertFalse(any(buffer.freed for buffer in allocator.buffers.values()))
            with self.assertRaises((OSError,RuntimeError)):
                acquire_planner_lease(0x40000000,self.path)
        finally:
            mmio.stuck = False
            wait_for(lambda: identity not in _INFLIGHT)
            wait_for(lambda: all(buffer.freed for buffer in allocator.buffers.values()))
            # freebuffer occurs inside close(), before the guardian drops its
            # bound-method reference. Wait for the actual thread exit first.
            guardian.join(5)
            self.assertFalse(guardian.is_alive())
        gc.collect(); self.assertIsNone(reference())
        with acquire_planner_lease(0x40000000,self.path): pass

    def test_normal_subprocess_exit_waits_for_idle_before_buffer_release(self):
        script = r'''
import gc,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_planner_accel_backend import FakeAllocator,FakeMMIO,REGS,sample_inputs
from planner_accel_backend import PynqPlannerAccel
import planner_accel_contract as contract
directory=Path(sys.argv[1]); allocator=FakeAllocator(); mmio=FakeMMIO(allocator)
original=mmio.read
def read(offset):
    mmio.stuck=not (directory/'release').exists()
    return original(offset)
mmio.read=read
backend=PynqPlannerAccel(mmio=mmio,registers=REGS,allocator=allocator,
    timeout_s=.001,lease_directory=directory)
_,_,_,ctx,inputs=sample_inputs()
try:backend.transport.execute(ctx,contract.IK_CHAIN,inputs,7,13)
except FloatingPointError:pass
del backend;gc.collect()
(directory/'main_finished').write_text('yes')
'''
        child = subprocess.Popen([sys.executable,'-X','utf8','-c',script,self.path],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            wait_for(lambda: (Path(self.path)/'main_finished').exists() or child.poll() is not None)
            self.assertIsNone(child.poll(), 'normal exit freed ownership before idle')
            self.assertTrue((Path(self.path)/'ip-40000000.inflight.json').exists())
            with self.assertRaises((OSError,RuntimeError)):
                acquire_planner_lease(0x40000000,self.path)
            (Path(self.path)/'release').write_text('observed by fake MMIO')
            out,err=child.communicate(timeout=10)
            self.assertEqual(child.returncode,0,out+err)
            self.assertFalse((Path(self.path)/'ip-40000000.inflight.json').exists())
            with acquire_planner_lease(0x40000000,self.path): pass
        finally:
            if child.poll() is None:
                child.kill();child.communicate(timeout=5)

    def test_forced_transport_exit_leaves_fail_closed_marker(self):
        script=r'''
import os,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_planner_accel_backend import FakeAllocator,FakeMMIO,REGS,sample_inputs
from planner_accel_backend import PynqPlannerAccel
import planner_accel_contract as contract
allocator=FakeAllocator();mmio=FakeMMIO(allocator);mmio.stuck=True
backend=PynqPlannerAccel(mmio=mmio,registers=REGS,allocator=allocator,
    timeout_s=.001,lease_directory=sys.argv[1])
_,_,_,ctx,inputs=sample_inputs()
try:backend.transport.execute(ctx,contract.IK_CHAIN,inputs,7,13)
except FloatingPointError:pass
assert backend.transport.inflight and mmio.starts==1
assert not any(buffer.freed for buffer in allocator.buffers.values())
os._exit(24)
'''
        child=subprocess.run([sys.executable,'-X','utf8','-c',script,self.path],
            cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(child.returncode,24,child.stdout+child.stderr)
        with self.assertRaisesRegex(RuntimeError,'stale in-flight marker'):
            acquire_planner_lease(0x40000000,self.path)


if __name__ == '__main__': unittest.main()
