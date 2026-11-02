set -eu
python3 - <<'PY'
import json,urllib.request
for port in (8785,8095,8765):
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/status'%port,timeout=3) as r:doc=json.load(r)
        keys=('version','robot_type','status','busy','running','active_job','current_job','job','ik_backend','ik_metrics')
        print('STATUS',port,json.dumps({k:doc[k] for k in keys if k in doc},ensure_ascii=False))
        print('STATUS_KEYS',port,sorted(doc))
    except Exception as exc:print('STATUS_ERROR',port,str(exc))
PY
readlink -f /home/xilinx/ZYNQArm
systemctl is-active so101-platform so101-workbench tcb705-ui so101-md0700r so101-gt911
cat /run/so101-lcd/status.json
cat /run/so101-lcd/touch.json
find /run/lock -maxdepth 2 -name '*planner*' -printf '%p\n'
cat /home/xilinx/so101_releases/release_planner_20261011_a8f65f66/so101_planner_runtime/.pynq-service.env
df -h /home/xilinx
free -m
