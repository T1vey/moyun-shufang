#!/bin/sh
set -eu
python3 - <<'PY'
import pathlib,subprocess
for unit in ('so101-platform','tcb705-ui'):
 text=subprocess.check_output(['systemctl','cat',unit],text=True)
 print('UNIT_ENV',unit)
 for line in text.splitlines():
  if line.startswith(('Environment=','EnvironmentFile=')) and any(k in line for k in ('XILINX','LD_LIBRARY_PATH','PYNQ','PATH=')):print(line)
pid=subprocess.check_output(['systemctl','show','tcb705-ui','--property=MainPID','--value'],text=True).strip()
data=pathlib.Path('/proc/'+pid+'/environ').read_bytes().split(b'\0')
for entry in data:
 if entry.split(b'=',1)[0] in (b'XILINX_XRT',b'LD_LIBRARY_PATH',b'PATH',b'XILINX_VITIS',b'PYNQ_JUPYTER_NOTEBOOKS'):print(entry.decode())
for d in ('/etc/profile.d','/opt/xilinx/xrt'):
 p=pathlib.Path(d)
 print(d,[x.name for x in p.iterdir()] if p.exists() else 'missing')
PY
