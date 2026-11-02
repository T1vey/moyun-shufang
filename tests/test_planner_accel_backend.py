"""Offline DDR ordering, fault ownership, and native old/new planner parity."""
import copy
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from planning import nominal, load
from ik_target_backend import NativeIKTarget
import planner_accel_contract as contract
from planner_accel_backend import NativePlannerAccel, NativePlannerTransport, PynqPlannerAccel, DDRTransport

DLL = os.environ.get('SO101_PLANNER_DLL')
REGS = {'abi': contract.ABI, 'top': contract.TOP}
cursor = 0x10
for name, count in contract.FIELDS.items():
    REGS[name] = cursor
    cursor += 4 * count + 4


class FakeBuffer(np.ndarray):
    def __new__(cls, allocator, shape, dtype, address):
        obj = np.zeros(shape, dtype=dtype).view(cls)
        obj.allocator = allocator
        obj.device_address = address
        obj.device_copy = np.zeros(shape, dtype=dtype)
        obj.freed = False
        return obj

    def flush(self):
        self.allocator.events.append(('flush', self.device_address))
        self.device_copy[:] = self

    def invalidate(self):
        self.allocator.events.append(('invalidate', self.device_address))
        self[:] = self.device_copy

    def freebuffer(self):
        self.allocator.events.append(('free', self.device_address))
        self.freed = True


class FakeAllocator:
    def __init__(self, base=0x10000000):
        self.base = base
        self.buffers = {}
        self.events = []

    def __call__(self, shape, dtype):
        address = self.base + len(self.buffers) * 0x20000
        buffer = FakeBuffer(self, shape, dtype, address)
        self.buffers[address] = buffer
        return buffer


class FakeMMIO:
    """Noncoherent DDR: only flush/invalidate transfer data across the boundary."""
    def __init__(self, allocator, native=None):
        self.base_addr = 0x40000000
        self.allocator = allocator
        self.native = native
        self.regs = {}
        self.running = False
        self.idle = True
        self.starts = 0
        self.polls = 0
        self.finish_after = 2
        self.stuck = False
        self.corrupt = None

    def write(self, offset, value):
        self.allocator.events.append(('write', offset, value))
        self.regs[offset] = value
        if offset == 0:
            self.starts += 1; self.running = True; self.idle = False; self.polls = 0

    def read(self, offset):
        self.allocator.events.append(('read', offset))
        if offset:
            return self.regs.get(offset, 0)
        if self.running:
            self.polls += 1
            if self.stuck or self.polls < self.finish_after:
                return 0
            self.complete()
            self.running = False; self.idle = True
            return 6
        return 4 if self.idle else 0

    def complete(self):
        arrays = [self.allocator.buffers[self.regs[REGS[name]]].device_copy for name in contract.POINTERS]
        integers = [self.regs[REGS[name]] for name in ('mode', 'count', 'output_capacity', 'job_id', 'generation')]
        if self.native:
            self.native.fn(*[value.ctypes.data_as(self.native.ptr) for value in arrays], *integers)
        else:
            ctx = arrays[0].view(contract.CONTEXT)
            inp = arrays[1].view(contract.IK_INPUT)
            out = arrays[2].view(contract.IK_OUTPUT)
            head = arrays[3].view(contract.HEADER)
            mode, count, capacity, job, generation = integers
            for key, value in dict(abi=contract.MAGIC, status=0, job_id=job, generation=generation,
                                   context_id=int(ctx['context_id'][0]), mode=mode, requested=count,
                                   done_count=count, first_error=0xffffffff,
                                   total_iterations=0, total_evaluations=count).items():
                head[key][0] = value
            out['q'][:count] = ctx['seed'][0]
            out['id'][:count] = inp['id'][:count]
            out['generation'][:count] = generation
            out['context_id'][:count] = ctx['context_id'][0]
            out['evaluations'][:count] = 1
        if self.corrupt:
            self.corrupt(arrays[3].view(contract.HEADER), arrays[2].view(contract.IK_OUTPUT))


def sample_inputs():
    model, _, seed = nominal()
    cfg = load('contract.json')
    ctx, _ = contract.context(model, seed, cfg)
    inputs = np.zeros(1, dtype=contract.IK_INPUT)
    pose = model.pose(seed)
    inputs['position'][0] = pose[:3, 3]
    inputs['axis'][0] = pose[:3, :3] @ model.tool_axis
    inputs['id'][0] = 91
    return model, seed, cfg, ctx, inputs


class TransportTests(unittest.TestCase):
    def setup_transport(self, timeout=.02):
        allocator = FakeAllocator(); mmio = FakeMMIO(allocator)
        transport = DDRTransport(mmio, REGS, allocator, timeout_s=timeout)
        def drain():
            mmio.stuck=False
            if transport.inflight:transport.release_after_idle()
            transport.close()
            if transport._guardian is not None:transport._guardian.join(2)
        self.addCleanup(drain)
        return allocator, mmio, transport

    def test_flush_precedes_doorbell_and_invalidate_follows_done(self):
        allocator, mmio, transport = self.setup_transport()
        _, _, _, ctx, inputs = sample_inputs()
        header, rows = transport.execute(ctx, contract.IK_CHAIN, inputs, 7, 13)
        self.assertEqual(header['done_count'], 1); self.assertEqual(rows['id'].tolist(), [91])
        events = allocator.events
        doorbell = events.index(('write', 0, 1))
        for name in contract.POINTERS:
            address = transport.buffers[name].device_address
            self.assertLess(events.index(('flush', address)), doorbell)
            self.assertEqual(mmio.regs[REGS[name]], address)
            self.assertEqual(mmio.regs[REGS[name] + 4], 0)
        last_read = max(i for i, event in enumerate(events) if event == ('read', 0))
        self.assertGreater(events.index(('invalidate', transport.buffers['output_words'].device_address)), last_read)
        self.assertGreater(events.index(('invalidate', transport.buffers['result_words'].device_address)), last_read)
        self.assertFalse(transport.inflight)
        transport.close(); self.assertTrue(all(b.freed for b in allocator.buffers.values()))

    def test_not_idle_rejects_before_touching_or_flushing_ddr(self):
        allocator, mmio, transport = self.setup_transport()
        _, _, _, ctx, inputs = sample_inputs()
        for buffer in allocator.buffers.values():
            buffer.fill(0xabcdef)
        mmio.idle = False
        with self.assertRaises((FloatingPointError, RuntimeError)):
            transport.execute(ctx, contract.IK_CHAIN, inputs, 7, 13)
        self.assertTrue(transport.faulted)
        self.assertEqual(mmio.starts, 0)
        self.assertFalse(any(event[0] == 'flush' for event in allocator.events))
        self.assertTrue(all(np.all(b == 0xabcdef) for b in allocator.buffers.values()))

    def test_timeout_retains_buffers_and_prohibits_reuse_or_close(self):
        allocator, mmio, transport = self.setup_transport(timeout=.001)
        _, _, _, ctx, inputs = sample_inputs(); mmio.stuck = True
        with self.assertRaisesRegex(FloatingPointError, 'timeout'):
            transport.execute(ctx, contract.IK_CHAIN, inputs, 7, 13)
        self.assertTrue(transport.faulted); self.assertTrue(transport.inflight)
        with self.assertRaises(RuntimeError): transport.close()
        with self.assertRaises(FloatingPointError):
            transport.execute(ctx, contract.IK_CHAIN, inputs, 7, 14)
        self.assertEqual(mmio.starts, 1)
        self.assertFalse(any(b.freed for b in allocator.buffers.values()))
        self.assertEqual(int(transport.buffers['cancel_words'][0]), (7 << 32) | 13)

    def test_maintenance_releases_only_after_observed_idle_and_never_reenables(self):
        allocator, mmio, transport = self.setup_transport(timeout=.001)
        _, _, _, ctx, inputs = sample_inputs(); mmio.stuck = True
        with self.assertRaises(FloatingPointError):
            transport.execute(ctx, contract.IK_CHAIN, inputs, 7, 13)
        with self.assertRaises(RuntimeError): transport.release_after_idle()
        self.assertFalse(any(b.freed for b in allocator.buffers.values()))
        mmio.stuck = False  # Subsequent ap_done also reports ap_idle.
        transport.release_after_idle()
        self.assertTrue(all(b.freed for b in allocator.buffers.values()))
        self.assertTrue(transport.faulted); self.assertFalse(transport.inflight)
        with self.assertRaises(FloatingPointError):
            transport.execute(ctx, contract.IK_CHAIN, inputs, 7, 14)
        self.assertEqual(mmio.starts, 1)

    def test_close_serializes_with_prelaunch_buffer_preparation(self):
        allocator,mmio,transport=self.setup_transport()
        _,_,_,ctx,inputs=sample_inputs()
        entered=threading.Event();proceed=threading.Event();closing=threading.Event();closed=threading.Event()
        errors=[]; original=FakeBuffer.flush
        first=transport.buffers['config_words']
        def flush(buffer):
            if buffer is first:
                entered.set()
                if not proceed.wait(2):raise RuntimeError('test gate timed out')
            return original(buffer)
        def execute():
            try:transport.execute(ctx,contract.IK_CHAIN,inputs,7,13)
            except Exception as exc:errors.append(exc)
        def close():
            closing.set()
            try:transport.close()
            except Exception as exc:errors.append(exc)
            finally:closed.set()
        with patch.object(FakeBuffer,'flush',flush):
            worker=threading.Thread(target=execute);worker.start()
            self.assertTrue(entered.wait(1))
            closer=threading.Thread(target=close);closer.start();self.assertTrue(closing.wait(1))
            try:
                self.assertFalse(closed.wait(.03),'close freed buffers while execute was preparing them')
                self.assertFalse(any(b.freed for b in allocator.buffers.values()))
            finally:
                proceed.set();worker.join(2);closer.join(2)
        self.assertFalse(worker.is_alive());self.assertFalse(closer.is_alive())
        self.assertEqual(errors,[]);self.assertTrue(closed.is_set())
        self.assertTrue(all(b.freed for b in allocator.buffers.values()))

    def test_wrong_completion_or_row_identity_faults_without_second_start(self):
        for field in ('abi', 'job_id', 'generation', 'context_id', 'mode', 'requested'):
            with self.subTest(header=field):
                allocator, mmio, transport = self.setup_transport()
                _, _, _, ctx, inputs = sample_inputs()
                mmio.corrupt = lambda h, rows, field=field: h[field].__setitem__(0, int(h[field][0]) + 1)
                with self.assertRaises(FloatingPointError):
                    transport.execute(ctx, contract.IK_CHAIN, inputs, 7, 13)
                self.assertTrue(transport.faulted); self.assertFalse(transport.inflight)
                with self.assertRaises(FloatingPointError):
                    transport.execute(ctx, contract.IK_CHAIN, inputs, 7, 14)
                self.assertEqual(mmio.starts, 1)
        for field in ('id', 'generation', 'context_id', 'flags'):
            with self.subTest(row=field):
                _, mmio, transport = self.setup_transport()
                _, _, _, ctx, inputs = sample_inputs()
                mmio.corrupt = lambda h, rows, field=field: rows[field].__setitem__(0, int(rows[field][0]) + 1)
                with self.assertRaises(FloatingPointError):
                    transport.execute(ctx, contract.IK_CHAIN, inputs, 7, 13)

    def test_budget_completion_cannot_claim_a_full_or_failed_prefix(self):
        _, _, _, ctx, inputs = sample_inputs()
        for mutation in ('full_count', 'wrong_index', 'failed_row'):
            _, mmio, transport = self.setup_transport()
            expanded = np.repeat(inputs, 2)
            def corrupt(h, rows):
                h['status'][0] = 7
                h['done_count'][0] = 2 if mutation == 'full_count' else 1
                h['first_error'][0] = 0 if mutation == 'wrong_index' else h['done_count'][0]
                h['total_evaluations'][0] = h['done_count'][0]
                if mutation == 'failed_row': rows['status'][0] = 3
            mmio.corrupt = corrupt
            with self.subTest(mutation=mutation), self.assertRaises(FloatingPointError):
                transport.execute(ctx, contract.IK_CHAIN, expanded, 7, 13)

    def test_wrong_register_identity_alignment_and_address_width_are_refused(self):
        for bad in (dict(REGS, abi='legacy'), dict(REGS, top='z20_ik_target'),
                    dict(REGS, input_words=REGS['config_words'])):
            with self.assertRaises(ValueError): DDRTransport(FakeMMIO(FakeAllocator()), bad, FakeAllocator())
        for base in (0x10000001, 2**32 - 64):
            allocator = FakeAllocator(base)
            with self.assertRaises(ValueError): DDRTransport(FakeMMIO(allocator), REGS, allocator)
            self.assertTrue(all(b.freed for b in allocator.buffers.values()))


@unittest.skipUnless(DLL, 'set SO101_PLANNER_DLL for native C++ differential checks')
class NativeDifferentialTests(unittest.TestCase):
    def setUp(self):
        self.model, _, self.seed = nominal()
        self.cfg = load('contract.json')

    def assert_result_equal(self, old, new):
        self.assertEqual(new.status, old.status)
        self.assertEqual(new.iterations, old.iterations)
        for field in ('q_solution', 'q_last'):
            if getattr(old, field) is None:
                self.assertIsNone(getattr(new, field))
            else:
                np.testing.assert_allclose(getattr(new, field), getattr(old, field), rtol=0, atol=2e-7)

    def targets(self, count=130):
        targets = []
        for i in range(count):
            q = np.asarray(self.seed).copy(); q[1] += (i + 1) * .0015
            pose = self.model.pose(q)
            targets.append(dict(position=pose[:3, 3].tolist(), axis=(pose[:3, :3] @ self.model.tool_axis).tolist(),
                                phase='DRAW', stroke=i))
        return targets

    def test_reachable_failure_and_weighted_modes_match_old_kernel(self):
        from scripts.generate_target_vectors import cases
        for index, (model, position, axis, seed, cfg, mode, _, _) in enumerate(cases()):
            with self.subTest(vector=index):
                old = NativeIKTarget(DLL).solve_target(model, position, axis, seed, cfg, mode=mode)
                new = NativePlannerAccel(DLL).solve_target(model, position, axis, seed, cfg, mode=mode)
                self.assert_result_equal(old, new)

    def test_calibrated_links_or_axes_rejected_but_runtime_pen_and_limits_accepted(self):
        from r1a.model import Model
        for change in ('offsets_m','axes'):
            cfg=copy.deepcopy(load('nominal_so101.json'))
            if change=='offsets_m':cfg[change][0][0]+=.001
            else:cfg[change][0]=[float(np.sin(.001)),0.,float(np.cos(.001))]
            model=Model(cfg);backend=NativePlannerAccel(DLL)
            pose=model.pose(self.seed)
            self.assertFalse(backend.validate_model(model))
            result=backend.solve_target(model,pose[:3,3],pose[:3,:3]@model.tool_axis,self.seed,self.cfg)
            self.assertEqual(result.status,'INVALID_INPUT');self.assertEqual(backend.transport.starts,0)
            with self.assertRaisesRegex(ValueError,'model mismatch'):
                backend.fk_rows(model,[self.seed],self.cfg)
            self.assertEqual(backend.transport.starts,0)
        model=copy.deepcopy(self.model)
        model.tool+=np.array([.003,-.002,.004])
        model.tool_axis=np.array([.1,.2,.9]);model.tool_axis/=np.linalg.norm(model.tool_axis)
        model.limits[:,0]+=.001;model.limits[:,1]-=.001
        backend=NativePlannerAccel(DLL);pose=model.pose(self.seed)
        self.assertTrue(backend.validate_model(model))
        old=NativeIKTarget(DLL).solve_target(model,pose[:3,3],pose[:3,:3]@model.tool_axis,self.seed,self.cfg)
        new=backend.solve_target(model,pose[:3,3],pose[:3,:3]@model.tool_axis,self.seed,self.cfg)
        self.assertEqual(new.status,'OK');self.assert_result_equal(old,new)

    def test_130_point_prefix_crosses_64_boundary_with_exact_authority_seeds(self):
        targets = self.targets(); old = NativeIKTarget(DLL); new = NativePlannerAccel(DLL)
        new.begin_plan(120000)
        old_seed = list(self.seed); new_seed = list(self.seed)
        for index, target in enumerate(targets):
            if new.needs_target_batch():
                new.prepare_targets(targets[index:index + 64], index, 120000)
            a = old.solve_target(self.model, target['position'], target['axis'], old_seed, self.cfg)
            b = new.solve_target(self.model, target['position'], target['axis'], new_seed, self.cfg)
            self.assertEqual(a.status, 'OK'); self.assert_result_equal(a, b)
            old_seed = a.q_solution; new_seed = b.q_solution
        self.assertGreaterEqual(new.batch_calls, 3)
        self.assertLess(new.batch_calls, len(targets) // 4)
        self.assertEqual(new.prepare_calls,new.batch_calls)
        self.assertEqual(new.prepare_calls,3)

    def test_changed_authority_seed_discards_tail_and_uses_single_target_fallback(self):
        targets=self.targets(8);backend=NativePlannerAccel(DLL);backend.begin_plan(120000)
        backend.prepare_targets(targets,0,120000)
        first=backend.solve_target(self.model,targets[0]['position'],targets[0]['axis'],self.seed,self.cfg)
        self.assertEqual(first.status,'OK');self.assertFalse(backend.needs_target_batch())
        # A rejected transition/recovery can supply an authority seed different
        # from the speculative chain. Do not prepare or consume its stale tail.
        changed=np.array(first.q_solution);changed[1]+=.02
        target=targets[1]
        old=NativeIKTarget(DLL).solve_target(self.model,target['position'],target['axis'],changed,self.cfg)
        actual=backend.solve_target(self.model,target['position'],target['axis'],changed,self.cfg)
        self.assert_result_equal(old,actual)
        self.assertEqual(backend.batch_calls,2);self.assertEqual(backend.prepare_calls,1)
        self.assertEqual(backend._prefetched,[]);self.assertTrue(backend.needs_target_batch())
        backend.prepare_targets(targets[2:],2,120000)
        target=targets[2]
        old=NativeIKTarget(DLL).solve_target(self.model,target['position'],target['axis'],actual.q_solution,self.cfg)
        actual=backend.solve_target(self.model,target['position'],target['axis'],actual.q_solution,self.cfg)
        self.assert_result_equal(old,actual)

    def test_retry_weight_change_discards_tail_without_new_preparation(self):
        targets=self.targets(8);backend=NativePlannerAccel(DLL);backend.begin_plan(120000)
        backend.prepare_targets(targets,0,120000)
        first=backend.solve_target(self.model,targets[0]['position'],targets[0]['axis'],self.seed,self.cfg)
        self.assertFalse(backend.needs_target_batch())
        changed=dict(self.cfg,weights=[1,1,1,.01,.01,.01]);target=targets[1]
        old=NativeIKTarget(DLL).solve_target(self.model,target['position'],target['axis'],first.q_solution,changed)
        actual=backend.solve_target(self.model,target['position'],target['axis'],first.q_solution,changed)
        self.assert_result_equal(old,actual)
        self.assertEqual(backend._prefetched,[]);self.assertTrue(backend.needs_target_batch())
        self.assertEqual(backend.prepare_calls,1);self.assertEqual(backend.batch_calls,2)

    def test_cache_hit_and_changed_config_discard_speculative_tail(self):
        targets = self.targets(8); new = NativePlannerAccel(DLL); new.begin_plan(120000)
        new.prepare_targets(targets, 0, 120000)
        first = targets[0]
        result = new.solve_target(self.model, first['position'], first['axis'], self.seed, self.cfg)
        self.assertEqual(result.status, 'OK'); self.assertGreater(len(new._prefetched), 0)
        calls = new.batch_calls
        cached = new.solve_target(self.model, first['position'], first['axis'], result.q_solution, self.cfg)
        self.assertEqual(cached.iterations, 0); self.assertEqual(new.batch_calls, calls)
        self.assertEqual(new._prefetched, [])
        changed = dict(self.cfg, weights=[1, 1, 1, .01, .01, .01])
        target = targets[1]
        new.prepare_targets(targets[1:], 1, 120000)
        expected = NativeIKTarget(DLL).solve_target(self.model, target['position'], target['axis'], result.q_solution, changed)
        actual = new.solve_target(self.model, target['position'], target['axis'], result.q_solution, changed)
        self.assert_result_equal(expected, actual)

    def test_speculative_work_budget_is_bounded_and_exhaustion_does_not_relaunch(self):
        targets = self.targets(); backend = NativePlannerAccel(DLL); backend.begin_plan(1)
        seed = self.seed
        for index, target in enumerate(targets):
            backend.prepare_targets(targets[index:index + 64], index, 120000)
            result = backend.solve_target(self.model, target['position'], target['axis'], seed, self.cfg)
            self.assertLessEqual(backend._work_used, 2)
            if result.status != 'OK': break
            seed = result.q_solution
        self.assertEqual(result.status, 'NUMERIC'); self.assertTrue(backend.faulted)
        self.assertIn('work budget', backend.last_error)
        starts = backend.transport.starts
        self.assertEqual(backend.solve_target(self.model, target['position'], target['axis'], seed, self.cfg).status, 'NUMERIC')
        self.assertEqual(backend.transport.starts, starts)

    def test_identical_zero_iteration_prefetch_preserves_tail_on_ps_cache_hit(self):
        ordinary=self.targets(2)
        targets=[copy.deepcopy(ordinary[0]) for _ in range(3)]+[ordinary[1]]
        backend=NativePlannerAccel(DLL);backend.begin_plan(120000)
        backend.prepare_targets(targets,0,120000)
        first=backend.solve_target(self.model,targets[0]['position'],targets[0]['axis'],self.seed,self.cfg)
        self.assertEqual(first.status,'OK');self.assertEqual(len(backend._prefetched),3)
        starts=backend.transport.starts
        for remaining in (2,1):
            result=backend.solve_target(self.model,targets[0]['position'],targets[0]['axis'],first.q_solution,self.cfg)
            self.assertEqual(result.iterations,0);self.assertEqual(result.q_solution,first.q_solution)
            self.assertEqual(len(backend._prefetched),remaining)
            self.assertEqual(backend.transport.starts,starts)
        expected=NativeIKTarget(DLL).solve_target(self.model,ordinary[1]['position'],ordinary[1]['axis'],first.q_solution,self.cfg)
        actual=backend.solve_target(self.model,ordinary[1]['position'],ordinary[1]['axis'],first.q_solution,self.cfg)
        self.assert_result_equal(expected,actual);self.assertEqual(backend.transport.starts,starts)

    def test_cache_hit_clears_tail_if_pl_row_iterates_or_changes_authority_seed(self):
        target=self.targets(1)[0]
        for mutation in ('iterations','q'):
            backend=NativePlannerAccel(DLL);backend.begin_plan(120000)
            backend.prepare_targets([copy.deepcopy(target) for _ in range(3)],0,120000)
            first=backend.solve_target(self.model,target['position'],target['axis'],self.seed,self.cfg)
            row=backend._prefetched[0][3]
            if mutation=='iterations':row['iterations']=1
            else:row['q'][0]+=np.float32(.00001)
            result=backend.solve_target(self.model,target['position'],target['axis'],first.q_solution,self.cfg)
            self.assertEqual(result.iterations,0);self.assertEqual(result.q_solution,first.q_solution)
            self.assertEqual(backend._prefetched,[])

    def test_cancel_is_flushed_and_kernel_drained_before_aborting(self):
        allocator = FakeAllocator(); native = NativePlannerTransport(DLL); mmio = FakeMMIO(allocator, native)
        mmio.finish_after = 3
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        backend = PynqPlannerAccel(mmio=mmio, registers=REGS, allocator=allocator,lease_directory=directory.name)
        self.addCleanup(backend.transport.close)
        target = self.targets(1)[0]
        result = backend.solve_target(self.model, target['position'], target['axis'], self.seed, self.cfg,
                                      cancel=lambda: mmio.starts > 0)
        self.assertEqual(result.status, 'ABORT')
        self.assertFalse(backend.transport.inflight); self.assertFalse(backend.faulted)
        cancel_address = backend.transport.buffers['cancel_words'].device_address
        self.assertEqual(sum(e == ('flush', cancel_address) for e in allocator.events), 2)
        self.assertEqual(mmio.starts, 1)
        backend.transport.close(); self.assertTrue(all(b.freed for b in allocator.buffers.values()))

    def test_fk_shadow_returns_ps_fp64_and_handles_1024_boundary(self):
        backend = NativePlannerAccel(DLL)
        rng = np.random.default_rng(1017)
        qs = np.asarray(self.seed) + rng.uniform(-.08, .08, (1027, 5))
        reference = self.model.pose_many(qs)
        tips, axes = backend.fk_rows(self.model, qs, self.cfg)
        np.testing.assert_array_equal(tips, reference[:, :3, 3])
        np.testing.assert_array_equal(axes, reference[:, :3, :3] @ self.model.tool_axis)
        self.assertEqual(backend.fk_rows_checked, 1027); self.assertEqual(backend.batch_calls, 2)
        self.assertLess(backend.fk_max_position_difference, 1e-6)

    def test_frozen_planner_path_recovery_after_64_boundary_matches_new_hook(self):
        frozen = ROOT / 'reports/planner_accel_implementation_20261011/baseline/planner_source/r1b/planner.py'
        if not frozen.is_file(): self.skipTest('frozen pre-change planner not bundled')
        name = 'r1b._frozen_accel_gate'
        module_spec = importlib.util.spec_from_file_location(name, frozen)
        old_planner = importlib.util.module_from_spec(module_spec)
        sys.modules[name] = old_planner; module_spec.loader.exec_module(old_planner)
        from r1b import planner as current
        cfg = load('trajectory.json'); cfg.update(max_total_ik_iterations=120000, max_targets=10000)
        targets = self.targets()
        outputs = []
        for module, backend in ((old_planner, NativeIKTarget(DLL)), (current, NativePlannerAccel(DLL))):
            original = module.motion_segment; recovery = [False]
            def check(*args, **kwargs):
                target = args[4]
                if target['stroke'] == 65 and not recovery[0]:
                    recovery[0] = True
                    raise ValueError('PATH_DISCONTINUITY')
                return original(*args, **kwargs)
            with patch.object(module, 'motion_segment', side_effect=check):
                result = module.plan(self.model, None, self.seed, self.cfg, cfg,
                                     backend=backend, targets_override=copy.deepcopy(targets))
            self.assertTrue(recovery[0]); outputs.append(result)
            if isinstance(backend,NativePlannerAccel):
                self.assertLess(backend.prepare_calls,10,'planner copied the 64-row prefix at every target')
        old, new = outputs
        self.assertEqual(old.status, 'OK'); self.assertEqual(new.status, old.status)
        self.assertEqual(new.metrics['recovery_calls'], old.metrics['recovery_calls'])
        self.assertEqual(new.metrics['ik_iterations'], old.metrics['ik_iterations'])
        self.assertEqual(len(new.commands), len(old.commands))
        for a, b in zip(old.commands, new.commands):
            for key in ('phase', 'stroke', 'pen_down', 'physical_authorized'):
                self.assertEqual(b[key], a[key])
            np.testing.assert_allclose(b['q_rad'], a['q_rad'], rtol=0, atol=2e-7)
            self.assertAlmostEqual(b['t_s'], a['t_s'], delta=1e-6)


if __name__ == '__main__':
    unittest.main()
