set -eu
printf 'BOARD\n'
date -Is
uname -a
id
printf 'PYTHON\n'
/usr/local/share/pynq-venv/bin/python -c 'import sys; print(sys.version)' 2>/dev/null || true
python3 - <<'PY'
import importlib
for name in ('numpy','PIL','cv2','scipy','skimage','serial','pynq','PyQt5.QtWebEngineWidgets'):
    try:
        m=importlib.import_module(name);print(name,'OK',getattr(m,'__version__',''))
    except Exception as e: print(name,type(e).__name__,str(e))
PY
printf 'SERVICES\n'
systemctl show so101-workbench so101-md0700r so101-gt911 so101-platform -p Id -p ActiveState -p SubState -p NRestarts -p MainPID -p ExecStart -p EnvironmentFiles
printf 'DISPLAY_LOG\n'
journalctl -b -u so101-md0700r -n 15 --no-pager
printf 'BOARD_FILES\n'
cat /usr/local/bin/so101-md0700r-start /usr/local/bin/so101-gt911-start
printf 'NETWORK\n'
ip -4 route
nmcli -t -f NAME,TYPE,AUTOCONNECT connection show || true
printf 'HEALTH\n'
python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:8765/api/status',timeout=5) as r:d=json.load(r)
print(json.dumps({k:v for k,v in d.items() if k in ('version','pl','platform','ik_backend','robot_type','allow_real','motion_supported')},ensure_ascii=False))
PY
