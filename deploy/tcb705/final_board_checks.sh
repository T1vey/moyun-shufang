set -eu
python3 - <<'PY'
import json, pathlib, urllib.request, urllib.parse
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(url):
    with opener.open(url,timeout=15) as r:return json.load(r)
status=get('http://127.0.0.1:8785/api/status')
root=pathlib.Path('/home/xilinx/ZYNQArm')
cfg=json.loads((root/'config/cloud.seedream.example.json').read_text())
credentials=json.loads(pathlib.Path('/home/xilinx/.config/so101/secrets.local.json').read_text())
gui_key_present=bool(credentials.get(cfg['api_key_env'], '').strip())
assert gui_key_present, 'GUI cloud profile credential missing'
assert status['robot_type']=='TCB705' and not status['simulation']
network=get('http://127.0.0.1:8095/api/network')
state=get('http://127.0.0.1:8095/api/state')
base='http://10.217.38.90:8095'
assert get(base+'/api/ping')['ok']
url=base+'/upload?'+urllib.parse.urlencode({'t':network['token']})
with opener.open(url,timeout=15) as r:assert r.status==200 and b'<html' in r.read().lower()
print(json.dumps({'robot_type':status['robot_type'],'ik_backend':status['ik_backend'],
 'simulation':status['simulation'],'physical_ready':status['readiness']['physical_ready'],
 'backend_default_cloud_profile':status['cloud_configured'],
 'gui_cloud_profile':'seedream','gui_cloud_credential_present':gui_key_present,'wifi_upload_page_ok':True,
 'wifi_url':base,'screen_view':state['view']},ensure_ascii=False))
PY
systemctl is-active tcb705-ui so101-platform so101-workbench so101-md0700r so101-gt911 so101-bluetooth
systemctl is-enabled tcb705-ui so101-md0700r so101-gt911
systemctl show tcb705-ui so101-md0700r so101-gt911 -p Id -p NRestarts -p ActiveEnterTimestamp
ip -brief -4 address
ip route
nmcli -g GENERAL.STATE,GENERAL.CONNECTION device show wlan0
nmcli -g connection.autoconnect connection show so101-ESP8200
