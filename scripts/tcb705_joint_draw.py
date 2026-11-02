"""Joint-mode drawing without the GUI: local 7-axis plan (PL batches on the board, CPU on a PC)
from the arm's real joints -> frozen plan -> hmcRobotFree programs (tcb705/web_executor.py).

  python scripts/tcb705_joint_draw.py --circle 30 --air 15 --dry-run      # plan + checks, no motion
  python scripts/tcb705_joint_draw.py --circle 30 --air 15 --execute      # moves the arm
--air raises the paper height for this run only (pen stays above the paper).
"""
import argparse, copy, json, math, sys, time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from tcb705.config import load, validate  # noqa: E402
from tcb705.calibration import apply_armvision  # noqa: E402
from tcb705.bridge import web_start  # noqa: E402
from tcb705.planner import plan  # noqa: E402
from tcb705 import artifact, web_executor as W  # noqa: E402


def path_error_text(value):
    """Unknown residuals are not a measured zero, including FP32 sentinels."""
    return '未评估' if value is None or not math.isfinite(float(value)) else '%.4f mm'%(float(value)*1000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--profile', type=Path, default=ROOT / 'robots/tcb705/profile.armvision_joint.json')
    ap.add_argument('--circle', type=float, help='diameter mm, centred on the paper')
    ap.add_argument('--square-circle', type=float, help='square side = circle diameter (mm), side by side')
    ap.add_argument('--square', type=float, help='square side (mm), centred on the paper')
    ap.add_argument('--offline-start', help='dry-run only: 7 joint degrees (comma separated) instead of reading the controller')
    ap.add_argument('--show-ik', action='store_true', help='print the IK joint solution at every corner / key node')
    ap.add_argument('--smooth', type=int, help='hmcRobotFree/hmcLine smooth level at gentle vertices')
    ap.add_argument('--speed', type=float, help='program speed %% (draw and air)')
    ap.add_argument('--merge-tol', type=float, help='joint merge tolerance near paper (mm)')
    ap.add_argument('--air', type=float, default=15.0, help='mm added to the paper height (0 = on paper)')
    ap.add_argument('--dry-run', action='store_true'); ap.add_argument('--execute', action='store_true')
    ap.add_argument('--out', type=Path, default=ROOT / 'build/tcb705/joint_draw')
    a = ap.parse_args()
    if a.dry_run == a.execute:
        ap.error('choose --dry-run or --execute')
    if a.air < 0:
        ap.error('--air must be >= 0')
    if sum(bool(v) for v in (a.circle, a.square_circle, a.square)) != 1:
        ap.error('give one of --circle, --square, --square-circle')
    if a.offline_start and a.execute:
        ap.error('--offline-start is for --dry-run only')
    cfg = load(a.profile)
    wp = cfg['execution']['web_program']
    if a.smooth is not None: wp['smooth'] = a.smooth
    if a.speed is not None: wp['draw_speed_pct'] = wp['air_speed_pct'] = a.speed
    if a.merge_tol is not None: wp['joint_merge_tolerance_mm'] = a.merge_tol
    print('SETTINGS smooth %s speed %s%% merge_tol %s mm' % (wp.get('smooth', 0), wp.get('draw_speed_pct'), wp.get('joint_merge_tolerance_mm', 0.02)))
    if a.air:
        av = copy.deepcopy(cfg['armvision']); av['z_table_mm'] = round(av['z_table_mm'] + a.air, 3)
        cfg = apply_armvision(cfg, av, reset_verified=False); validate(cfg)
    if a.offline_start:
        from tcb705.model import Model
        qd = [float(v) for v in a.offline_start.split(',')]; m0 = Model(cfg); q0 = m0.from_sdk(qd)
        T0 = m0.fk(q0); start = dict(joint_degrees=qd, world_mm_deg=(T0[:3, 3] * 1000).tolist() + [0, 0, 0], q_rad=q0.tolist(), model_error_mm=0.0)
        print('OFFLINE START (no controller read)')
    else:
        start = web_start(cfg)
    print('START joints', json.dumps([round(v, 3) for v in start['joint_degrees']]), 'pose', json.dumps([round(v, 3) for v in start['world_mm_deg']]),
          'model err %.4f mm' % start.get('model_error_mm', 0))
    W.require_mode_switch_clearance(cfg, start['world_mm_deg'])
    w, h = cfg['paper']['width_mm'], cfg['paper']['height_mm']
    def circle(cx, cy, d):
        r = d / 2; n = max(24, int(math.ceil(math.pi * d)))
        return [[cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)] for k in range(n + 1)]
    if a.circle:
        strokes = [circle(w / 2, h / 2, a.circle)]
    elif a.square:
        e = a.square / 2; cx, cy = w / 2, h / 2
        strokes = [[[cx - e, cy - e], [cx + e, cy - e], [cx + e, cy + e], [cx - e, cy + e], [cx - e, cy - e]]]
    else:
        d = a.square_circle; gap = 8.0; cx1, cx2 = w / 2 - (d + gap) / 2, w / 2 + (d + gap) / 2; cy = h / 2; e = d / 2
        strokes = [[[cx1 - e, cy - e], [cx1 + e, cy - e], [cx1 + e, cy + e], [cx1 - e, cy + e], [cx1 - e, cy - e]], circle(cx2, cy, d)]
    paths = dict(units='mm', width_mm=w, height_mm=h, coordinate_system='full_canvas_xy_up', paths=strokes)
    t0 = time.perf_counter(); res = plan(paths, cfg, start['q_rad']); t_plan = time.perf_counter() - t0
    mt = res['metrics']
    folder = a.out / time.strftime('%Y%m%d_%H%M%S'); doc = artifact.save(res, folder, 'real'); nodes = artifact.load_nodes(folder, doc)
    mm = np.asarray(nodes['positions_m']) * 1000
    W.require_mode_switch_clearance(cfg, mm[-1])
    print('PLAN %.2f s  nodes %d  ik_iterations %d (%.2f/node)  backend %s  path_err %s' % (
        t_plan, mt['nodes'], mt['ik_iterations'], mt['ik_iterations'] / mt['nodes'], mt.get('ik_backend'), path_error_text(mt.get('max_path_error_m'))))
    print('PL_VERIFICATION', json.dumps({k: mt.get(k) for k in (
        'pl_rows_cpu_verified', 'pl_rows_cpu_rejected', 'ik_accel_errors', 'ik_accel_unavailable_reason')}))
    print('GEOMETRY z_min %.2f  x %.1f..%.1f  y %.1f..%.1f  (paper z %.2f + air %.1f)' % (
        mm[:, 2].min(), mm[:, 0].min(), mm[:, 0].max(), mm[:, 1].min(), mm[:, 1].max(), cfg['paper']['origin_m'][2] * 1000 - a.air, a.air))
    s = W.settings(cfg); _, chunks = W.build(cfg, nodes, s)
    blk = [b for c in chunks for b in c['content']['programs'][0]['codeBlock'] if b['fc'] != 'end']
    print('SMOOTHED blocks %d of %d (corners / pen up-down / ends stay exact), corner stops %d' % (
        sum(1 for b in blk if b['code']['smooth']), len(blk), mt.get('corner_stops', 0)))
    keep = [0] + [i for c in chunks for i in c['node_index']]
    lens = np.linalg.norm(np.diff(mm[keep], axis=0), axis=1)
    print('PROGRAM mode %s  nodes %d -> blocks %d  chunks %d  block length mm mean %.2f max %.2f' % (
        s['mode'], len(mm), sum(c['blocks'] for c in chunks), len(chunks), lens.mean(), lens.max()))
    if s['mode'] == 'joint':
        print('JOINT-LERP deviation of executed blocks: near paper %.4f mm, air %.4f mm (limits %.2f / %.2f)' % (
            *W.joint_block_error(cfg, nodes, keep), s['joint_draw_tolerance_mm'], s['joint_air_tolerance_mm']))
    if a.show_ik:
        qn = np.asarray(nodes['sdk_degrees']); ph = nodes['interval_phase']; stops = set(nodes.get('stops', []))
        names = {0: 'APPROACH', 1: 'DRAW', 2: 'LIFT', 3: 'TRAVEL', 4: 'LOWER', 5: 'FINISH'}
        key = [0] + [i for i in range(1, len(qn) - 1) if i in stops or ph[i] != ph[i - 1]] + [len(qn) - 1]
        print('IK at key nodes (target pen-tip XYZ mm -> 7 joint angles deg):')
        for i in key:
            label = names.get(ph[i - 1] if i else ph[0], '?') + ('/corner' if i in stops and i else '')
            print('  node %4d %-14s xyz %s -> q %s' % (i, label, np.round(mm[i], 2).tolist(), np.round(qn[i], 3).tolist()))
    print('FOLDER', folder)
    if a.dry_run:
        return 0
    result = W.execute(folder, cfg, progress=lambda e: print('EXEC', json.dumps({k: v for k, v in e.items() if k not in ('stop', 'steps')}, ensure_ascii=False)) if e['event'] != 'PROGRESS' or int(e['t']) % 2 == 0 else None)
    print('RESULT', json.dumps({k: v for k, v in result.items() if k != 'log'}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
