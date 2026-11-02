"""Make the pen vertical (UVW = tool_rotation of the profile) at the current X/Y, optionally
lifted, with one controller hmcLine (controller IK). Needed before joint-mode drawing:
the ZYNQ plan must start from real joints with the planned pen orientation.

  python scripts/tcb705_pen_vertical.py --dry-run [--lift 10]
  python scripts/tcb705_pen_vertical.py --execute [--lift 10]     # moves the arm
"""
import argparse, json, math, sys, time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from tcb705.config import load  # noqa: E402
from tcb705.web_control import Controller, dist3, settle_pose  # noqa: E402
from tcb705.web_executor import uvw_deg, require_mode_switch_clearance, restore_safe  # noqa: E402
from tcb705.model import rpy_matrix, pose_error  # noqa: E402

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--dry-run', action='store_true'); ap.add_argument('--execute', action='store_true')
    ap.add_argument('--profile', type=Path, default=ROOT / 'robots/tcb705/profile.armvision_joint.json')
    ap.add_argument('--lift', type=float, default=0.0); ap.add_argument('--speed', type=float, default=5); ap.add_argument('--min-z', type=float, default=240.0)
    a = ap.parse_args()
    if a.dry_run == a.execute: ap.error('choose --dry-run or --execute')
    cfg = load(a.profile); ctrl = Controller(cfg['controller'], cfg['robot_id']); ctrl.login()
    st = ctrl.state(); al = ctrl.active_alarms(); p0 = settle_pose(ctrl)
    uvw = [round(v, 4) for v in uvw_deg(np.asarray(cfg['tool_rotation'], dtype=float))]
    tilt = math.degrees(pose_error(np.eye(4) if False else np.block([[rpy_matrix(np.radians(p0[3:])), np.zeros((3, 1))], [np.zeros((1, 3)), np.ones((1, 1))]]),
                                    np.block([[np.asarray(cfg['tool_rotation'], dtype=float), np.zeros((3, 1))], [np.zeros((1, 3)), np.ones((1, 1))]]))[1])
    target = [round(p0[0], 3), round(p0[1], 3), round(p0[2] + a.lift, 3)] + uvw
    print('STATE', json.dumps(st)); print('ALARMS', json.dumps(al, ensure_ascii=False))
    print('POSE', json.dumps([round(v, 3) for v in p0])); print('PEN TILT FROM TARGET %.3f deg' % tilt); print('TARGET', json.dumps(target))
    require_mode_switch_clearance(cfg, p0)
    require_mode_switch_clearance(cfg, target)
    if target[2] < a.min_z: raise SystemExit('target Z below %.1f' % a.min_z)
    if a.dry_run: return 0
    if al or st['_phc_alarm_'] not in ('0', '') or st['g_state_'] != '1': raise SystemExit('alarm/estop; not moving')
    blk = {'fc': 'hmcLine', 'pluginName': 'HC Motion Adapter', 'enabled': True, 'options': {'customName': ''},
           'code': {'robot': cfg['robot_id'], 'speed': a.speed, 'delay': 0, 'smooth': 0, 'relative': 0, 'mask': 63, 'more': [], 'endp': target}}
    content = {'name': 'ZYNQ_PenVertical', 'showname': 'ZYNQ_PenVertical', 'type': 0, 'variables': [],
               'programs': [{'name': '主程序', 'tpid': 0, 'condition': 'd(_phc_ctrlkey) == 100 && d(_phc_key) == 100', 'recycle': False,
                             'type': 0, 'logic': 0, 'codeBlock': [blk, {'fc': 'end', 'pluginName': '', 'enabled': True}]}]}
    moved = False; rc = 0
    try:
        ctrl.power('auto'); time.sleep(1.5)
        if ctrl.state()['g_servo_statero_'] not in ('1', 'true', 'True'): raise RuntimeError('servo not on')
        s1 = settle_pose(ctrl); print('POWER_ON_SHIFT %.3f mm' % dist3(s1, p0))
        if dist3(s1, p0) > 10: raise RuntimeError('power-on shift too large')
        target[:3] = [round(s1[0], 3), round(s1[1], 3), round(s1[2] + a.lift, 3)]
        require_mode_switch_clearance(cfg, target)
        ctrl.load_program('ZYNQ_PenVertical', content); ctrl.run_key(False); time.sleep(0.2); ctrl.run_key(True); moved = True
        t0 = time.monotonic(); last = t0; prev = s1; stable = 0
        while True:
            time.sleep(0.1); p = ctrl.pose(); now = time.monotonic()
            if p[2] < a.min_z or dist3(p, s1) > a.lift + 5: raise RuntimeError('pose out of bounds %s' % p[:3])
            if dist3(p, prev) > 0.02: last = now
            prev = p
            done = dist3(p, target) < 0.1 and max(abs(((p[3 + i] - target[3 + i]) + 180) % 360 - 180) for i in range(3)) < 0.05
            stable = stable + 1 if done else 0
            if stable >= 5: break
            if now - last > 10 or now - t0 > 60: raise RuntimeError('no progress / timeout')
        print('DONE', json.dumps([round(v, 3) for v in ctrl.pose()]), 'JOINTS', json.dumps([round(v, 3) for v in ctrl.joints(7)]))
    except Exception as e:  # noqa: BLE001
        print('ERROR', e); rc = 2
        if moved: print('STOP', ctrl.stop())
    finally:
        ref, steps = restore_safe(ctrl, cfg)
        print('RESTORE', steps)
        if ref is None:
            print('RESTORE_DEFERRED: stopped; no mode switch at low/unknown height')
            rc = 2
    return rc

if __name__ == '__main__':
    sys.exit(main())
