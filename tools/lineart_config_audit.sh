#!/bin/sh
set -eu
python3 - <<'PY'
import hashlib,pathlib,json
expected='41df136cdd85507a4c28071b36f400a73850eefc4ed248c73b8e58d33bd0ae57'
for directory in ('/home/xilinx/tcb705_data','/home/xilinx/tcb705_deploy_backups'):
 base=pathlib.Path(directory)
 for p in base.rglob('*'):
  if p.is_file() and any(x in p.name.lower() for x in ('machine','profile','config')) and p.stat().st_size<200000:
   h=hashlib.sha256(p.read_bytes()).hexdigest()
   print('CONFIG_FILE',p,h,'MATCH' if h==expected else '')
for p in pathlib.Path('/home/xilinx/tcb705_data').rglob('events.jsonl'):
 for raw in p.read_text(errors='replace').splitlines()[-40:]:
  if any(event in raw for event in ('TCB_CONFIG','TCB_SPEED')):
   print('CONFIG_EVENT',p,raw[:1500])
PY
