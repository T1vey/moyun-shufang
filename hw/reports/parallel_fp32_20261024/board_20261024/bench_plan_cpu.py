"""Board-side offline CPU planning of the portrait with the live machine config (no PL, no I/O)."""
import json, os, sys, time
release = sys.argv[1]
os.environ['TCB705_PL_MANIFEST'] = release + '/not_loaded.json'      # force the native CPU batches
sys.path.insert(0, release)
os.chdir(release)
import copy
from tcb705.config import load as load_config
from tcb705.model import Model
from tcb705.planning_session import PlanningSession
cfg = load_config('/home/xilinx/tcb705_data/tcb705.machine.json')
q0 = Model(cfg).from_sdk(cfg['execution']['web_program']['home']['joint_degrees']).tolist()
paths = json.load(open('/home/xilinx/fp32_check/motion_portrait.paths.json', encoding='utf-8'))
session = PlanningSession()
out = []
for i in range(int(sys.argv[2])):
    t = time.perf_counter()
    result = session.plan_cpu(copy.deepcopy(paths), copy.deepcopy(cfg), q0, lambda: False, None)
    wall = time.perf_counter() - t
    mt = result['metrics']
    keys = ('nodes', 'frames', 'planning_s', 'ik_cpu_batch_s', 'ik_pl_batch_s', 'ik_cpu_batches', 'pl_batch_starts',
            'geometry_fk_batches', 'geometry_probe_samples', 'ik_backend', 'duration_s')
    out.append(dict(run=i, wall_s=round(wall, 3), **{k: mt.get(k) for k in keys}))
    print(json.dumps(out[-1], ensure_ascii=False), flush=True)
json.dump(out, open(sys.argv[3], 'w'), indent=1)
