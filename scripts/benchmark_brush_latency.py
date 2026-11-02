"""CPU-only brush planning benchmark. No SDK, PL access or robot motion."""
import argparse
import cProfile
import json
import platform
import pstats
import sys
import time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calligraphy.presets import task
from tcb705.artifact import nodes_of
from tcb705.config import load
from tcb705.model import Model
from tcb705.planning_session import PlanningSession
from tcb705.web_executor import prepare_joint


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', required=True)
    ap.add_argument('--module', default='heng')
    ap.add_argument('--size', type=float, default=40)
    ap.add_argument('--repeat', type=int, default=3)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--profile', action='store_true')
    ap.add_argument('--hover', action='store_true', help='Offline scenario: start 20 mm before the stroke at hover height')
    ap.add_argument('--short', action='store_true', help='Non-executable SDK joint-geometry prototype')
    args = ap.parse_args()
    config = load(args.config)
    model = Model(config)
    q0 = model.from_sdk(config['execution']['web_program']['home']['joint_degrees'])
    paths = task(args.module, args.size, config)
    if args.hover:
        # A hypothetical session state, never a command to the real arm. Only
        # the in-memory final lift changes; no calibration/settings are saved.
        config['planning']['final_lift_m'] = config['planning']['lift_m']
        if 'armvision' in config:
            config['armvision']['final_lift_mm'] = config['armvision']['lift_mm']
        paths = task(args.module, args.size, config)
        px, py = paths['paths'][0][0]
        px -= 20.
        py = paths['height_mm']-py
        goal = np.eye(4); goal[:3, :3] = config['tool_rotation']
        paper = config['paper']
        goal[:3, 3] = (np.asarray(paper['origin_m']) +
                      .001*(px*np.asarray(paper['x_axis'])+py*np.asarray(paper['y_axis'])))
        goal[2, 3] += config['planning']['lift_m']
        solved = model.solve(goal, q0, q0)
        if not solved['ok']:
            raise ValueError('offline hover seed IK failed')
        q0 = solved['q']
    records = []
    profiler = cProfile.Profile()
    session = PlanningSession()
    for i in range(args.repeat):
        if args.profile and i == args.repeat-1:
            profiler.enable()
        start = time.perf_counter()
        if args.short:
            from tcb705.short_stroke import compile_single
            plan = compile_single(paths, config, q0)
            end = time.perf_counter()
            nodes = plan['nodes'];m = plan['metrics']
            planned = start+m['geometry_s'];extracted = planned
            blocks=m['blocks'];error=(m['near_error_mm'],m['air_error_mm'])
        else:
            plan = session.plan_cpu(paths, config, q0)
            planned = time.perf_counter()
            nodes = nodes_of(plan)
            extracted = time.perf_counter()
            prepared = prepare_joint(config, nodes)
            end = time.perf_counter()
            blocks=len(prepared.keep)-1;error=prepared.error_mm
        if args.profile:
            profiler.disable()
        row = dict(run=i, plan_s=planned-start, nodes_s=extracted-planned,
                   prepare_s=end-extracted, total_s=end-start,
                   nodes=len(nodes['positions_m']), frames=plan['metrics']['frames'],
                   blocks=blocks, error_mm=error,
                   ik_cpu_batch_s=plan['metrics'].get('ik_cpu_batch_s'),
                   metrics=plan['metrics'])
        records.append(row)
        print(json.dumps({k:v for k,v in row.items() if k != 'metrics'}), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(host=platform.machine(), python=sys.version,
        cpu_only=True, no_motion=True, hover=args.hover, short_research=args.short,
        module=args.module, size_mm=args.size,
        profiled_last=args.profile, records=records), indent=2), encoding='utf-8')
    if args.profile:
        with args.output.with_suffix('.profile.txt').open('w', encoding='utf-8') as out:
            pstats.Stats(profiler, stream=out).sort_stats('cumtime').print_stats(65)


if __name__ == '__main__':
    main()
