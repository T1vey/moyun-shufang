"""Capture static joint/pose samples for tcb705/kinematic_fit.py (moves the arm).

1. hmcLine straight up to --lift-z (same X/Y/UVW).
2. N hmcRobotFree poses: current joints + bounded per-joint offsets (seeded).
3. At each pose: wait still, read 7 joints + XYZUVW twice (must agree), append JSONL.
4. hmcRobotFree back to the lifted start joints; restore mold + manual.
Watchdog during every move: Z >= --min-z, TCP within --max-disp mm of the lifted
start, no progress 10 s -> stop. Same auto-mode program path as the drawing executor.

  python scripts/tcb705_calibrate_capture.py --dry-run
  python scripts/tcb705_calibrate_capture.py --execute     # person at E-stop
"""
import argparse
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tcb705.config import load  # noqa: E402
from tcb705.web_control import Controller, ControllerError, dist3, settle_pose  # noqa: E402

# max |offset| per joint (deg) and allowed sign: J2/J4 + lowers the TCP on this arm
SPAN = [8, 8, 8, 8, 8, 8, 8]
LOWERING_LIMIT = {1: 2.0, 3: 2.0}
MOLD = 'ZYNQ_Calib'


def program(blocks):
    return {'name': MOLD, 'showname': MOLD, 'type': 0, 'variables': [],
            'programs': [{'name': '主程序', 'tpid': 0, 'condition': 'd(_phc_ctrlkey) == 100 && d(_phc_key) == 100',
                          'recycle': False, 'type': 0, 'logic': 0,
                          'codeBlock': blocks + [{'fc': 'end', 'pluginName': '', 'enabled': True}]}]}


def block(fc, endp, speed, robot):
    return {'fc': fc, 'pluginName': 'HC Motion Adapter', 'enabled': True, 'options': {'customName': ''},
            'code': {'robot': robot, 'speed': speed, 'delay': 0, 'smooth': 0, 'relative': 0,
                     'mask': 63 if fc == 'hmcLine' else 127, 'more': [], 'endp': endp}}


def targets(q0, n, seed):
    import random
    rnd = random.Random(seed); out = []
    for k in range(n):
        d = [rnd.uniform(-s, s) for s in SPAN]
        for j, lim in LOWERING_LIMIT.items():
            d[j] = min(d[j], lim)
        if k < 7:  # guarantee every joint gets a full-span sample early
            d = [0.0] * 7; d[k] = SPAN[k] if k not in LOWERING_LIMIT else -SPAN[k]
        out.append([round(q0[j] + d[j], 3) for j in range(7)])
    return out


def move(ctrl, blk, args, home, log, joint_target=None):
    ctrl.load_program(MOLD, program([blk])); ctrl.run_key(False); time.sleep(0.2); ctrl.run_key(True)
    t0 = time.monotonic(); last = t0; prev = ctrl.pose(); stable = 0
    while True:
        time.sleep(0.1)
        p = ctrl.pose(); now = time.monotonic()
        if p[2] < args.min_z:
            raise ControllerError('Z %.2f < %.1f' % (p[2], args.min_z))
        if home is not None and dist3(p, home) > args.max_disp:
            raise ControllerError('TCP %.1f mm from start > %.1f' % (dist3(p, home), args.max_disp))
        if dist3(p, prev) > 0.02:
            last = now; stable = 0
        else:
            stable += 1
        prev = p
        if joint_target is not None:
            q = ctrl.joints(7)
            reached = max(abs(a - b) for a, b in zip(q, joint_target)) < 0.02
        else:
            reached = dist3(p, blk['code']['endp']) < 0.1
        if reached and stable >= 5:
            break
        if now - last > 10:
            raise ControllerError('no progress 10 s')
        if now - t0 > 90:
            raise ControllerError('move timeout')
    ctrl.run_key(False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true'); ap.add_argument('--execute', action='store_true')
    ap.add_argument('--profile', type=Path, default=ROOT / 'robots/tcb705/profile.armvision.json')
    ap.add_argument('--ip', default='192.168.4.4'); ap.add_argument('--samples', type=int, default=20)
    ap.add_argument('--lift-z', type=float, default=320.0); ap.add_argument('--min-z', type=float, default=260.0)
    ap.add_argument('--max-disp', type=float, default=150.0); ap.add_argument('--speed', type=float, default=5)
    ap.add_argument('--seed', type=int, default=705)
    ap.add_argument('--out', type=Path, default=ROOT / 'build/tcb705/calibration/samples.jsonl')
    args = ap.parse_args()
    if args.dry_run == args.execute:
        ap.error('choose --dry-run or --execute')
    cfg = load(args.profile); controller = dict(cfg['controller'], remote_ip=args.ip)
    ctrl = Controller(controller, cfg['robot_id']); ctrl.login()
    log = lambda *a: print('CALIB', *a, flush=True)  # noqa: E731
    st = ctrl.state(); alarms = ctrl.active_alarms(); p0 = ctrl.pose(); q0 = ctrl.joints(7)
    log('STATE', json.dumps(st)); log('ALARMS', json.dumps(alarms, ensure_ascii=False))
    log('POSE', json.dumps(p0)); log('JOINTS', json.dumps(q0))
    if ctrl.axis_count() != 7:
        raise SystemExit('controller axis count is not 7')
    if args.lift_z < p0[2]:
        raise SystemExit('lift Z below current Z')
    lift = [round(v, 3) for v in p0[:2]] + [args.lift_z] + [round(v, 3) for v in p0[3:]]
    log('LIFT_TO', json.dumps(lift))
    log('NOTE joint targets are offsets from the joints at the lifted pose (read after the lift)')
    for i, t in enumerate(targets(q0, args.samples, args.seed)):
        log('TARGET_OFFSETS_FROM_CURRENT %02d' % i, json.dumps([round(a - b, 2) for a, b in zip(t, q0)]))
    if args.dry_run:
        return 0
    if alarms or st['_phc_alarm_'] not in ('0', '') or st['g_state_'] != '1':
        raise SystemExit('alarm/estop state; not moving')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    moved = False; rc = 0
    try:
        ctrl.power('auto'); time.sleep(1.5)
        if ctrl.state()['g_servo_statero_'] not in ('1', 'true', 'True'):
            raise ControllerError('servo not on after auto')
        settled = settle_pose(ctrl); log('POWER_ON_SHIFT_MM %.3f' % dist3(settled, p0))
        if dist3(settled, p0) > 10:
            raise ControllerError('power-on shift too large')
        lift[:2] = [round(v, 3) for v in settled[:2]]
        moved = True; move(ctrl, block('hmcLine', lift, args.speed, cfg['robot_id']), args, None, log)
        home = ctrl.pose(); qh = ctrl.joints(7); log('LIFTED', json.dumps(home), json.dumps(qh))
        with args.out.open('a', encoding='utf-8') as f:
            for i, t in enumerate(targets(qh, args.samples, args.seed)):
                move(ctrl, block('hmcRobotFree', t, args.speed, cfg['robot_id']), args, home, log, joint_target=t)
                time.sleep(0.5)
                a = (ctrl.joints(7), ctrl.pose()); time.sleep(0.3); b = (ctrl.joints(7), ctrl.pose())
                if max(abs(x - y) for x, y in zip(a[0], b[0])) > 0.005 or dist3(a[1], b[1]) > 0.02:
                    raise ControllerError('sample %d not static' % i)
                rec = dict(schema='tcb705-web-static-sample-v1', index=i, joint_degrees=b[0], world_mm_deg=b[1],
                           unix_s=time.time(), source='controller_web', robot_id=cfg['robot_id'])
                f.write(json.dumps(rec) + '\n'); f.flush()
                log('SAMPLE %02d' % i, json.dumps([round(v, 3) for v in b[0]]), json.dumps([round(v, 3) for v in b[1]]))
        move(ctrl, block('hmcRobotFree', [round(v, 3) for v in qh], args.speed, cfg['robot_id']), args, home, log, joint_target=qh)
        log('RETURNED', json.dumps(ctrl.pose()))
    except Exception as exc:  # noqa: BLE001
        log('ERROR', exc); rc = 2
        if moved:
            log('STOP', ctrl.stop())
    finally:
        log('RESTORE', ctrl.restore())
    return rc


if __name__ == '__main__':
    sys.exit(main())
