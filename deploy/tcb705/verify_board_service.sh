set -eu
systemctl is-active tcb705-ui so101-workbench so101-platform so101-md0700r so101-gt911 so101-bluetooth
systemctl is-enabled tcb705-ui so101-md0700r so101-gt911
systemctl show tcb705-ui so101-md0700r so101-gt911 -p Id -p MainPID -p NRestarts -p ExecMainStatus
python3 - <<'PY'
import json,urllib.request,pathlib,time
base='http://127.0.0.1:8095'
def get(path):
    with urllib.request.urlopen(base+path,timeout=10) as r:return json.load(r)
s=get('/api/tcb/status');c=get('/api/tcb/config')
assert s['robot_type']=='TCB705' and not s['simulation'] and s['allow_real']
assert c['armvision']['a_mm']==[-509.605,-67.854]
assert c['armvision']['pose_uvw_deg']==[180,0,0]
assert c['planning']['lift_m']==.008 and c['planning']['final_lift_m']==.06
print(json.dumps({'robot_type':s['robot_type'],'ik_backend':s['ik_backend'],'simulation':s['simulation'],'physical_ready':s['readiness']['physical_ready'],'armvision':c['armvision']},ensure_ascii=False))
with urllib.request.urlopen(base+'/debug',timeout=10) as r:
    html=r.read().decode();assert '读取A点坐标' in html and '获取落笔点' in html
print('CALIBRATION_PAGE_OK')
for i in range(70):
    p=pathlib.Path('/run/so101-lcd/status.json')
    if p.exists():
        state=json.loads(p.read_text());assert state['hardware_frames_verified']
        print('LCD_STATUS',json.dumps(state));break
    if i==69:raise RuntimeError('LCD frame status not ready')
    time.sleep(1)
PY
printf 'GUI_PROCESS\n'
ps -eo pid,args | grep -E 'tcb705.*run_tcb705|tcb705.*app.py|tcb705.*user_gui_kiosk|tcb705.*md0700r_display' | grep -v grep
printf 'RECENT_LOGS\n'
journalctl -u tcb705-ui -u so101-md0700r -u so101-gt911 --since '2026-10-17 03:09:00 UTC' -n 20 --no-pager
printf 'NETWORK\n'
ip -brief -4 address
printf 'SOURCE_AND_BINARIES\n'
file /home/xilinx/ZYNQArm/build/tcb705/libtcb_core.so /home/xilinx/ZYNQArm/build/tcb705/tcb_runner /home/xilinx/ZYNQArm/build/tcb705/tcb_sdk_probe
