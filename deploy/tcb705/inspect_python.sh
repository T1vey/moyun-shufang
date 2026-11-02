set -eu
old=/home/xilinx/so101_releases/release_planner_20261011_a8f65f66/so101_planner_runtime
cat "$old/.venv/pyvenv.cfg"
"$old/.venv/bin/python" - <<'PY'
import sys,numpy,serial,site,pathlib
print('BASE',sys.base_prefix)
print('PATH',sys.path)
print('NUMPY',numpy.__file__)
print('SERIAL',serial.__file__)
for p in pathlib.Path(sys.prefix).rglob('*.pth'):
    print('PTH',str(p),p.read_text())
PY
ip -brief -4 address
ip -4 route
nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device
systemctl is-active so101-bluetooth
