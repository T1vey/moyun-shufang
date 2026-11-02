"""Read-only: fetch the controller's own kinematics (r_dh_1_, r_classic_1_, tool/user frame)
and verify it against the live joint/pose feedback. Optionally refresh a profile.

  python scripts/tcb705_read_controller_model.py                       # read + verify
  python scripts/tcb705_read_controller_model.py --update robots/tcb705/profile.armvision_joint.json
Never writes to the controller and never moves the arm.
"""
import argparse, json, math, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from tcb705.config import load, validate  # noqa: E402
from tcb705.model import Model, rpy_matrix, pose_error  # noqa: E402
from tcb705.web_control import Controller, settle_pose  # noqa: E402

LIMITS = [[-178.9, 178.9], [-134.9, 134.9], [-178.9, 178.9], [-143.0, 143.0], [-178.9, 178.9], [-133.0, 133.0], [-178.9, 178.9]]

def parse_dh(value):
    rows = []
    for part in str(value).split('|0')[1:]:
        if '{' in part:
            d = json.loads(part[part.index('{'):])
            rows.append([float(d.get('a', 0)), float(d.get('d', 0)), float(d.get('alpha', 0)), float(d.get('theta', 0))])
    return rows

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--profile', type=Path, default=ROOT / 'robots/tcb705/profile.armvision_joint.json')
    ap.add_argument('--update', type=Path, help='write the read kinematics into this profile if verification passes')
    a = ap.parse_args()
    cfg = load(a.profile); ctrl = Controller(cfg['controller'], cfg['robot_id']); ctrl.login()
    robots = ctrl.request('/api/robots', check=False).get('data')
    dh = parse_dh(ctrl.var('r_dh_%d_' % cfg['robot_id'])['value'])
    classic = ctrl.var('r_classic_%d_' % cfg['robot_id'])['value']
    tool = ctrl.value('r_tool_%d_' % cfg['robot_id']); user = ctrl.value('r_user_%d_' % cfg['robot_id'])
    print('ROBOTS', json.dumps(robots, ensure_ascii=False)); print('DH', json.dumps(dh)); print('CLASSIC', classic)
    print('TOOL', tool, 'USER', user)
    if len(dh) != 7: raise SystemExit('expected 7 DH rows')
    if tool != '0' or user != '0': raise SystemExit('controller tool/user frame is not 0: the profile assumes tool 0 / base frame')
    kin = dict(source='controller_dh', read_from='r_dh_%d_' % cfg['robot_id'], dh=dh, joint_limits_deg=LIMITS)
    test = json.loads(json.dumps(cfg)); test['kinematics'] = kin
    test['sdk_mapping'] = dict(sdk_to_model_index=list(range(7)), sign=[1] * 7, offset_rad=[0] * 7)
    m = Model(test)
    settle_pose(ctrl); q = ctrl.joints(7); p = ctrl.pose()
    T = m.fk(m.from_sdk(q)); R = np.eye(4); R[:3, :3] = rpy_matrix(np.radians(p[3:])); R[:3, 3] = np.asarray(p[:3]) / 1000
    pe, ae = pose_error(T, R)
    print('VERIFY live pose: %.4f mm, %.4f deg' % (pe * 1000, math.degrees(ae)))
    ok = pe * 1000 <= 0.05 and math.degrees(ae) <= 0.01
    print('RESULT', 'PASS' if ok else 'FAIL')
    if a.update:
        if not ok: raise SystemExit('verification failed; profile not changed')
        c = load(a.update); c['kinematics'] = kin; c['sdk_mapping'] = test['sdk_mapping']; validate(c)
        a.update.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding='utf-8'); print('UPDATED', a.update)
    return 0 if ok else 2

if __name__ == '__main__':
    sys.exit(main())
