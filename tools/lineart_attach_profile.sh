#!/bin/sh
set -eu
cd /home/xilinx/tcb705_releases/20261020_lineart_r1/ZYNQArm
export XILINX_XRT=/usr TCB705_PL_MANIFEST="$PWD/overlay/tcb705/platform.json"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
.venv/bin/python - <<'PY'
import json,time
import lineart_contract as c
from tcb705.accel_runtime import attached_identity,platform_manifest,ensure_event_loop,ps_ddr_allocator,verify_planner_clock
from planner_accel_lease import acquire_planner_lease
ensure_event_loop()
for i in range(2):
 row={'pass':i};t=time.perf_counter()
 cfg,*_=attached_identity();row['identity']=time.perf_counter()-t;t=time.perf_counter()
 manifest=platform_manifest();bit=manifest.parent/cfg['bitfile']
 entry,registers=c.validate_manifest_section(cfg,manifest.parent,bit)
 row['contract']=time.perf_counter()-t;t=time.perf_counter()
 lease=acquire_planner_lease(entry['base'])
 try:
  from pynq import Overlay
  verify_planner_clock(cfg['accelerator_clock_hz'])
  row['import_clock_lease']=time.perf_counter()-t;t=time.perf_counter()
  overlay=Overlay(str(bit),download=False)
  row['overlay']=time.perf_counter()-t;t=time.perf_counter()
  allocate=ps_ddr_allocator(overlay)
  row['allocator']=time.perf_counter()-t
 finally:lease.close()
 print(json.dumps(row),flush=True)
PY
