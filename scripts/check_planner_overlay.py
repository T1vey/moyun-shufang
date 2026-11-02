"""Validate the attached planner PL on the board; never opens servo devices."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from ik_target_contract import STATUSES
from planner_accel_backend import PynqPlannerAccel
from scripts.generate_target_vectors import cases


def run_gate(core):
    statuses = {}
    count = 0
    maximum = 0.0
    for model, position, axis, seed, config, mode, want, golden in cases():
        result = core.solve_target(model, position, axis, seed, config, mode=mode)
        expected = STATUSES.get(want)
        if (want < 0 and result.status == 'OK') or (want >= 0 and result.status != expected):
            raise AssertionError('case %d: %s expected %s' % (count, result.status, expected))
        if core.faulted:
            raise AssertionError('Planner faulted at case ' + str(count))
        if result.status == 'OK':
            np.testing.assert_allclose(result.q_solution, golden, atol=.003, rtol=0)
            maximum = max(maximum, result.position_error_m)
        statuses[result.status] = statuses.get(result.status, 0) + 1
        count += 1
    # A complete 64-target dependency chain must actually cross DDR in a batch.
    from planning import nominal, load
    model, _, q0 = nominal()
    config = load('contract.json')
    config['max_iterations'] = 40
    targets = []
    for i in range(64):
        q = np.clip(np.asarray(q0) + .012*np.sin(.05*(i+1))*np.array([1.,-.3,.4,-.2,.1]),
                    model.limits[:,0]+.01, model.limits[:,1]-.01)
        pose = model.pose(q)
        targets.append(dict(position=pose[:3,3], axis=pose[:3,:3]@model.tool_axis))
    core.begin_plan(64*40)
    # Ensure the first row requires a real solve, not the PS zero-iteration cache.
    seed = np.clip(np.asarray(q0)+.015, model.limits[:,0], model.limits[:,1])
    before = core.transport.starts
    core.prepare_targets(targets, 0, 64*40)
    for target in targets:
        result = core.solve_target(model, target['position'], target['axis'], seed, config)
        if result.status != 'OK' or core.faulted:
            raise AssertionError('Batch chain failed: '+result.status)
        seed = np.asarray(result.q_solution)
        maximum = max(maximum, result.position_error_m)
    starts = core.transport.starts-before
    if starts != 1:
        raise AssertionError('Expected one 64-target hardware batch, got '+str(starts))
    from scripts.load_platform import planner_fk_self_test
    qs = np.repeat(np.asarray(q0)[None,:], 1024, axis=0)
    qs[:,0] += np.linspace(-.02,.02,1024)
    planner_fk_self_test(core, model, qs, config)
    return dict(status='PASS', cases=count, statuses=statuses, batch_targets=64,
                batch_kernel_starts=starts, fk_shadow_rows=1024,
                max_position_error_m=maximum, metrics=core.metrics())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--overlay', type=Path, required=True)
    p.add_argument('--platform-manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    core = PynqPlannerAccel(a.overlay, load_policy='attach', platform_manifest=a.platform_manifest)
    try:
        report = run_gate(core)
        report.update(scope='BOARD_PLANNER_PS_PL_NO_MOTOR_IO',
            hashes={suffix:hashlib.sha256(a.overlay.with_suffix(suffix).read_bytes()).hexdigest()
                    for suffix in ('.bit','.hwh','.registers.json')})
    finally:
        core.transport.close()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print('PLANNER_OVERLAY_PASS', report['cases'], 'IK64', 'FK1024')


if __name__ == '__main__':
    main()
