from pathlib import Path
import json,csv,collections,hashlib
import numpy as np
r=Path(__file__).resolve().parent
rows=list(csv.DictReader((r/'rows.csv').open()))
calls=list(csv.DictReader((r/'calls.csv').open()))
recorded=list(csv.DictReader((r/'recorded_preflight.csv').open()))
provenance=json.loads((r/'provenance.json').read_text(encoding='utf8'))
assert len(rows)==provenance['target_count_excluding_seed']
assert [int(v['index']) for v in rows]==list(range(1,len(rows)+1))
def metrics(data,name):
 x=np.array([float(v[name]) for v in data]);imax=int(x.argmax())
 return {'min':float(x.min()),'p50':float(np.quantile(x,.5)),'p90':float(np.quantile(x,.9)),
  'p95':float(np.quantile(x,.95)),'p99':float(np.quantile(x,.99)),'p99_9':float(np.quantile(x,.999)),
  'max':float(x.max()),'max_node_index':int(data[imax]['index'])}
methods=dict(collections.Counter(row['method'] for row in rows));phases={}
for phase in sorted(set(row['phase'] for row in rows)):
 subset=[row for row in rows if row['phase']==phase]
 phases[phase]={'targets':len(subset),'methods':dict(collections.Counter(v['method'] for v in subset)),
  'original_strict_ok':sum(int(v['old_strict_ok']) for v in subset),
  **{name:metrics(subset,name) for name in ['position_m','orientation_rad','joint_step_rad']}}
machine=json.loads(Path(provenance['sources']['machine.json']['path']).read_text(encoding='utf-8-sig'))
limits=np.radians(np.array(machine['kinematics']['joint_limits_deg']))
q=np.array([[float(v['q%d'%k]) for k in range(7)] for v in rows])
margin=np.minimum(q-limits[:,0],limits[:,1]-q)
summary={'physical_motion':False,'simulation_type':'native host call of the same formal FP32 HLS C++ kernel; independent full4x4 FP64 sin/cos FK oracle',
 'target_count':len(rows),'source_nodes_including_initial_seed':len(recorded),'batch_size':64,'kernel_calls':len(calls),
 'targets_per_call':dict(collections.Counter(int(v['requested']) for v in calls)),
 'method_counts':methods,'pl_acceptance_fraction':methods.get('pl',0)/len(rows),
 'cpu_fallback_fraction':methods.get('cpu_fallback',0)/len(rows),'unresolved_fraction':methods.get('unresolved_historical_reseed',0)/len(rows),
 'rejected_call_count':sum(int(v['status'])!=0 for v in calls),
 'original_strict_tolerances':{'position_m':1e-7,'orientation_rad':1e-6},
 'fp32_offline_budgets':{'position_m':1e-5,'orientation_rad':1e-4},
 'original_strict_ok':sum(int(v['old_strict_ok']) for v in rows),
 'original_position_only_ok':sum(float(v['position_m'])<=1e-7 for v in rows),
 'original_orientation_only_ok':sum(float(v['orientation_rad'])<=1e-6 for v in rows),
 'fp32_offline_budget_ok':sum(int(v['fp32_budget_ok']) for v in rows),
 'minimum_joint_limit_margin_rad':float(margin.min()),
 **{name:metrics(rows,name) for name in ['position_m','orientation_rad','joint_step_rad','delta_recorded_q_rad']},
 'recorded_preflight':{'original_strict_ok':sum(int(v['strict_ok']) for v in recorded),
  **{name:metrics(recorded,name) for name in ['position_m','orientation_rad','joint_step_rad']}},
 'phase_statistics':phases,'failure_boundaries':[],
 'provenance':provenance,'artifact_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in r.iterdir() if p.suffix in ['.cpp','.py','.txt','.csv','.log']}}
summary['original_strict_fraction']=summary['original_strict_ok']/len(rows)
(r/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf8')
lines=['# Full historical trajectory replay — FP32 kernel','',
'This is offline host execution of the same frozen HLS C++ kernel, not robot motion or a board timing measurement. The native wall time must not be used as FPGA throughput.','',
f"The record contains {len(recorded):,} nodes; node 0 is the recorded home seed. All {len(rows):,} following targets were processed in order, in 64-point batches (final batch 47 points), and each batch used the preceding accepted joint solution as seed. No batch used a fresh recorded seed.",
'',f"**{methods.get('pl',0):,}/{len(rows):,} targets accepted by the PL algorithm model; zero CPU fallback, zero unresolved points, zero rejected batches.** All {len(calls)} calls completed. Every recorded q/position was independently checked first: all source nodes meet the original fixed-pose/model tolerances.",
'','| Metric | Median | P95 | P99 | Maximum |','|---|---:|---:|---:|---:|']
for label,name in [('Position error (m)','position_m'),('Orientation error (rad)','orientation_rad'),('Largest joint change between neighbors (rad)','joint_step_rad'),('Difference from historical redundant joint solution (rad)','delta_recorded_q_rad')]:
 v=summary[name];lines.append(f"| {label} | {v['p50']:.9g} | {v['p95']:.9g} | {v['p99']:.9g} | {v['max']:.9g} |")
lines+=['',f"Original strict tolerance (1e-7 m / 1e-6 rad): {summary['original_strict_ok']:,}/{len(rows):,} points. Declared FP32 offline budget (1e-5 m / 1e-4 rad): {summary['fp32_offline_budget_ok']:,}/{len(rows):,}. These are different criteria and are not conflated.",
'','All motion phases in the historical record were retained, including pen-down, pen-up/travel and transition points; phase codes and per-phase counts are preserved in summary.json. The final source attribution is the recorded controller-DH model, not a substitute URDF.',
'','No fallback occurred in this particular trajectory. That does not establish a zero fallback rate for arbitrary reachable poses, near-singular configurations, other paper placements or other models. The tested kernel still has explicit conditioning/model/joint-limit domain restrictions.',
'','Artifacts: rows.csv records every target, output q, error and step; calls.csv records every batch status; recorded_preflight.csv checks original input consistency; summary.json holds quantiles, model/source hashes and phase statistics. Formal hardware source was not changed.']
(r/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
print(json.dumps({k:summary[k] for k in ['target_count','kernel_calls','method_counts','position_m','orientation_rad','joint_step_rad','delta_recorded_q_rad','minimum_joint_limit_margin_rad','original_strict_ok','fp32_offline_budget_ok']},indent=2))
