# User-selected topology: PC -> GE_PL; controller -> GE_PS. Run over Wi-Fi.
set -eu
test "$(id -u)" = 0
backup=/home/xilinx/tcb705_deploy_backups/port_roles_20261017
mkdir -p "$backup"
test -e "$backup/eth0.interfaces" || cp -a /etc/network/interfaces.d/eth0 "$backup/eth0.interfaces"
python3 - <<'PY'
import json,subprocess,shutil
from pathlib import Path
assert Path('/sys/class/net/eth0/address').read_text().strip()=='00:0a:35:00:22:01'
assert Path('/sys/class/net/eth1/address').read_text().strip()=='02:0a:35:00:22:02'
backup=Path('/home/xilinx/tcb705_deploy_backups/port_roles_20261017')
for iface,obsolete in (('eth0','192.168.2.99/24'),('eth1','192.168.4.23/24')):
 rows=json.loads(subprocess.check_output(['ip','-j','-4','addr','show','dev',iface]))
 if any(x['local']+'/'+str(x['prefixlen'])==obsolete for r in rows for x in r['addr_info']):
  subprocess.run(['ip','address','del',obsolete,'dev',iface],check=True)
subprocess.run(['ip','address','replace','192.168.4.23/24','dev','eth0'],check=True)
subprocess.run(['ip','address','replace','192.168.2.99/24','dev','eth1'],check=True)
Path('/etc/network/interfaces.d/eth0').write_text('''# TCB705 dedicated controller port; no default route.
auto eth0
iface eth0 inet static
    address 192.168.4.23
    netmask 255.255.255.0
''')
net=Path('/home/xilinx/tcb705_data/ge_pl_network.json')
if net.exists() and not (backup/net.name).exists():shutil.copy2(net,backup/net.name)
net.write_text(json.dumps(dict(address='192.168.2.99/24',peer_ip='192.168.2.1',role='pc_debug'),indent=2)+'\n')
cfg=Path('/home/xilinx/tcb705_data/tcb705.machine.json')
if cfg.exists():
 if not (backup/cfg.name).exists():shutil.copy2(cfg,backup/cfg.name)
 data=json.loads(cfg.read_text());data['controller']['local_ip']='192.168.4.23';data['controller']['remote_ip']='192.168.4.4'
 cfg.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
 print('CONTROLLER_ENDPOINT_UPDATED',str(cfg),flush=True)
else:print('CONTROLLER_PROFILE_NOT_FOUND',str(cfg),flush=True)
PY
ip -br address
ip route
