from pathlib import Path
import json,hashlib,math,collections
r=Path(__file__).resolve().parent
project=Path(r'D:/zhiliao/TCB705_ZYNQ-10-15/ZYNQArm')
source=project/'build/tcb705/startup_speed_20261020'
paths={n:source/n for n in ['nodes.json','machine.json','board_benchmark.json']}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
n=json.loads(paths['nodes.json'].read_text(encoding='utf-8-sig'))
m=json.loads(paths['machine.json'].read_text(encoding='utf-8-sig'))
assert sha(paths['machine.json'])=='0c0cc14003fa59f9f80ddff060b1902387d5b1e470a463ae8cd0f5874545605e'
assert sha(paths['nodes.json'])=='b6b9cd1df4b3ee3a49aabc5ce3084cc8ead785b62a34419f2e7be0f87da2674d'
assert m['kinematics']['source']=='controller_dh'
assert len(n['positions_m'])==len(n['sdk_degrees'])==21680
seed_difference_deg=max(abs(a-b) for a,b in zip(n['sdk_degrees'][0],m['execution']['web_program']['home']['joint_degrees']))
assert seed_difference_deg<1e-12
with (r/'nodes.txt').open('w') as out:
 out.write(str(len(n['positions_m']))+'\n')
 for i,(p,q) in enumerate(zip(n['positions_m'],n['sdk_degrees'])):
  phase=-1 if i==0 else n['interval_phase'][i-1]
  stroke=-1 if i==0 else n['interval_stroke'][i-1]
  out.write(' '.join([str(i),str(phase),str(stroke)]+[format(float(x),'.17g') for x in p]+[format(math.radians(x),'.17g') for x in q])+'\n')
meta={'sources':{name:{'path':str(path),'sha256':sha(path)} for name,path in paths.items()},
 'physical_motion':False,'source_model':m['kinematics'],'fixed_target_rotation':m['tool_rotation'],
 'source_node_count':len(n['positions_m']),'target_count_excluding_seed':len(n['positions_m'])-1,
 'target_phase_counts':dict(collections.Counter(n['interval_phase'])),
 'recorded_seed_sdk_degrees':n['sdk_degrees'][0],'home_seed_max_difference_deg':seed_difference_deg,
 'batch_size':64,'formal_source_sha256':{p.name:sha(p) for p in (r.parent/'src').iterdir() if p.suffix in ['.h','.hpp','.cpp']},
 'input_text_sha256':sha(r/'nodes.txt')}
(r/'provenance.json').write_text(json.dumps(meta,indent=2,ensure_ascii=False),encoding='utf8')
print(json.dumps({k:meta[k] for k in ['source_node_count','target_count_excluding_seed','target_phase_counts','physical_motion']},indent=2))
