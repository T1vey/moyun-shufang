"""Find the pen contact height with one sloped line ("ramp"): the flange Z falls linearly
from --z-high to --z-low over --length mm along +X; where the ink starts gives the contact
height: z = z_high - (z_high - z_low) * (mark_start_mm / length).
One program run; both mode switches happen high above the paper (start pose, final lift).

  python scripts/tcb705_contact_ramp.py --dry-run
  python scripts/tcb705_contact_ramp.py --execute          # moves the arm, touches the paper
"""
import argparse, json, sys, time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from tcb705.config import load  # noqa: E402
from tcb705.web_control import Controller, dist3, settle_pose  # noqa: E402
from tcb705.web_executor import uvw_deg  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true'); ap.add_argument('--execute', action='store_true')
    ap.add_argument('--profile', type=Path, default=ROOT / 'robots/tcb705/profile.armvision_joint.json')
    ap.add_argument('--x0', type=float, default=-440.0); ap.add_argument('--y', type=float, default=-45.0)
    ap.add_argument('--length', type=float, default=40.0)
    ap.add_argument('--z-high', type=float, default=223.3); ap.add_argument('--z-low', type=float, default=218.3)
    ap.add_argument('--speed', type=float, default=3); ap.add_argument('--air-speed', type=float, default=5)
    a = ap.parse_args()
    if a.dry_run == a.execute: ap.error('choose --dry-run or --execute')
    if not 216.0 <= a.z_low < a.z_high <= 240.0: ap.error('z range must be within 216..240 and z_low < z_high')
    if a.length <= 0 or a.length > 60: ap.error('length 0..60 mm')
    cfg = load(a.profile); ctrl = Controller(cfg['controller'], cfg['robot_id']); ctrl.login()
    uvw = [round(v, 4) for v in uvw_deg(np.asarray(cfg['tool_rotation'], dtype=float))]
    av = cfg['armvision']; (xa, ya), (xb, yb) = av['a_mm'], av['b_mm']
    x1 = a.x0 + a.length
    for x in (a.x0, x1):
        if not (min(xa, xb) <= x <= max(xa, xb) and min(ya, yb) <= a.y <= max(ya, yb)):
            raise SystemExit('ramp leaves the ArmVision paper range')
    st = ctrl.state(); al = ctrl.active_alarms(); p0 = ctrl.pose()
    up = a.z_high + 8.0
    pts = [[a.x0, a.y, max(up, p0[2])], [a.x0, a.y, a.z_high], [x1, a.y, a.z_low], [x1, a.y, a.z_low + 8.0], [x1, a.y, max(up, p0[2])]]
    speeds = [a.air_speed, a.speed, a.speed, a.speed, a.air_speed]
    print('STATE', json.dumps(st)); print('ALARMS', json.dumps(al, ensure_ascii=False)); print('POSE', json.dumps([round(v, 3) for v in p0]))
    print('UVW', uvw, 'slope %.3f mm per mm' % ((a.z_high - a.z_low) / a.length))
    for i, (p, sp) in enumerate(zip(pts, speeds), 1):
        print('PATH %d %s speed %s%%' % (i, json.dumps([round(v, 3) for v in p]), sp))
    print('READ-OUT: contact z = %.2f - %.4f * (mm from ramp start where the ink begins)' % (a.z_high, (a.z_high - a.z_low) / a.length))
    if a.dry_run: return 0
    if al or st['_phc_alarm_'] not in ('0', '') or st['g_state_'] != '1': raise SystemExit('alarm/estop; not moving')
    if p0[2] < up: raise SystemExit('start pose must be above %.1f' % up)
    blocks = [{'fc': 'hmcLine', 'pluginName': 'HC Motion Adapter', 'enabled': True, 'options': {'customName': ''},
               'code': {'robot': cfg['robot_id'], 'speed': sp, 'delay': 0, 'smooth': 0, 'relative': 0, 'mask': 63, 'more': [],
                        'endp': [round(v, 3) for v in p] + uvw}} for p, sp in zip(pts, speeds)]
    content = {'name': 'ZYNQ_ContactRamp', 'showname': 'ZYNQ_ContactRamp', 'type': 0, 'variables': [],
               'programs': [{'name': '主程序', 'tpid': 0, 'condition': 'd(_phc_ctrlkey) == 100 && d(_phc_key) == 100', 'recycle': False,
                             'type': 0, 'logic': 0, 'codeBlock': blocks + [{'fc': 'end', 'pluginName': '', 'enabled': True}]}]}
    xs = [p[0] for p in pts] + [p0[0]]; ys = [p[1] for p in pts] + [p0[1]]
    box = (min(xs) - 2, max(xs) + 2, min(ys) - 2, max(ys) + 2, a.z_low - 0.5, max(p0[2], pts[0][2]) + 2)
    moved = False; rc = 0
    try:
        ctrl.power('auto'); time.sleep(1.5)
        if ctrl.state()['g_servo_statero_'] not in ('1', 'true', 'True'): raise RuntimeError('servo not on')
        s1 = settle_pose(ctrl); print('POWER_ON_SHIFT %.3f mm' % dist3(s1, p0))
        if dist3(s1, p0) > 10: raise RuntimeError('power-on shift too large')
        ctrl.load_program('ZYNQ_ContactRamp', content); ctrl.run_key(False); time.sleep(0.2); ctrl.run_key(True); moved = True
        t0 = time.monotonic(); last = t0; prev = s1; stable = 0; lowest = 1e9
        while True:
            time.sleep(0.1); p = ctrl.pose(); now = time.monotonic(); lowest = min(lowest, p[2])
            if not (box[0] <= p[0] <= box[1] and box[2] <= p[1] <= box[3] and box[4] <= p[2] <= box[5]):
                raise RuntimeError('pose outside box %s' % [round(v, 2) for v in p[:3]])
            if dist3(p, prev) > 0.02: last = now
            prev = p
            stable = stable + 1 if dist3(p, pts[-1]) < 0.1 else 0
            if stable >= 5: break
            if now - last > 10 or now - t0 > 240: raise RuntimeError('no progress / timeout')
        print('DONE lowest flange z %.3f, final %s' % (lowest, json.dumps([round(v, 3) for v in ctrl.pose()])))
    except Exception as e:  # noqa: BLE001
        print('ERROR', e); rc = 2
        if moved: print('STOP', ctrl.stop())
    finally:
        print('RESTORE', ctrl.restore())
    return rc


if __name__ == '__main__':
    sys.exit(main())
