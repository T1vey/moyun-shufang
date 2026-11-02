"""Install a validated board platform and local GUI; preserve all machine data.

Run on the board only after kernel/display/WiFi packages are ready. Does not
reboot, download a bitstream, restart the running backend, or execute motion.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import pwd
import grp
import importlib.util
import shlex
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from platform_runtime import validate_manifest, display_backend, accelerator_identity, PLANNER_ABI


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--platform-manifest',type=Path,required=True)
    p.add_argument('--data-dir',type=Path,default=Path('/home/xilinx/so101_data_work107'))
    p.add_argument('--user',default='xilinx')
    a=p.parse_args()
    if os.geteuid()!=0:raise PermissionError('Run installer as root')
    cfg,bit,*_=validate_manifest(a.platform_manifest,platform.release())
    if display_backend(cfg)!='kernel-drm':
        raise ValueError('Use scripts/install_planner_runtime.py for the PYNQ userspace display; this installer configures Linux DRM/LightDM')
    account=pwd.getpwnam(a.user)
    if not (a.data_dir/'machine.json').is_file():
        raise ValueError('Existing machine.json is required; never install a factory calibration')
    for tool in ('Xorg','lightdm','openbox','xset'):
        if not shutil.which(tool):raise ValueError('Missing GUI dependency: '+tool)
    import tkinter
    from PIL import ImageTk
    import cv2, numpy
    for module in ('pynq','serial','scipy','skimage','ezdxf','svgpathtools'):
        if importlib.util.find_spec(module) is None:
            raise ValueError('Missing board Python dependency: '+module)
    timestamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup=a.data_dir/'deployment_backups'/timestamp
    backup.mkdir(parents=True,exist_ok=False)
    shutil.copy2(a.data_dir/'machine.json',backup/'machine.json')
    def install(destination,content,mode=0o644):
        dest=Path(destination)
        if dest.exists():
            previous=backup/str(dest).lstrip('/');previous.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(dest,previous)
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(content,encoding='utf-8');dest.chmod(mode)
    values={'SO101_APP':str(ROOT),'SO101_DATA':str(a.data_dir.resolve()),'SO101_ALLOW_MOTION':'1',
            'SO101_PLATFORM':str(a.platform_manifest.resolve())}
    install('/etc/so101/desktop.env',''.join(k+'='+shlex.quote(v)+'\n' for k,v in values.items()))
    runtime=dict(schema='so101-runtime-v1',ik_engine='wls',pl_mode='planner' if accelerator_identity(cfg)[0]==PLANNER_ABI else 'target',port=8765,
                 overlay=str(bit),ip_name=cfg.get('ip_name','z20_ik_target_0'),
                 pl_load_policy='attach',platform_manifest=str(a.platform_manifest.resolve()))
    install('/etc/so101/runtime.desktop.json',json.dumps(runtime,indent=2)+'\n')
    source=ROOT/'deploy/standalone'
    for name in ('so101-platform-start','so101-workbench-start','so101-desktop'):
        install('/usr/local/bin/'+name,(source/name).read_text(),0o755)
    install('/etc/systemd/system/so101-platform.service',(source/'so101-platform.service').read_text())
    install('/usr/share/xsessions/so101-desktop.desktop',(source/'so101-desktop.desktop').read_text())
    install('/etc/systemd/system/so101-workbench.service.d/desktop.conf',
            '[Unit]\nRequires=so101-platform.service\nAfter=so101-platform.service\n'
            '[Service]\nExecStart=\nExecStart=/usr/local/bin/so101-workbench-start\n'
            'Environment=OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1\n')
    install('/etc/systemd/system/lightdm.service.d/so101.conf',
            '[Unit]\nRequires=so101-platform.service\nAfter=so101-platform.service so101-workbench.service\n')
    install('/etc/lightdm/lightdm.conf.d/80-so101.conf',
            '[Seat:*]\nxserver-command=X -config /run/so101-platform/xorg.conf\nautologin-user='+a.user+'\nautologin-session=so101-desktop\nuser-session=so101-desktop\n')
    # PYNQ 2.7/Ubuntu 20.04 uses polkit local-authority. Allow only the active
    # console user to create private Wi-Fi profiles without a password agent.
    install('/etc/polkit-1/localauthority/50-local.d/60-so101-network.pkla',
            '[SO101 active console WiFi]\nIdentity=unix-user:'+a.user+'\n'
            'Action=org.freedesktop.NetworkManager.network-control;org.freedesktop.NetworkManager.wifi.scan;org.freedesktop.NetworkManager.settings.modify.own\n'
            'ResultAny=no\nResultInactive=no\nResultActive=yes\n')
    groups=[]
    for name in ('video','input'):
        try: grp.getgrnam(name);groups.append(name)
        except KeyError: pass
    if groups:subprocess.run(['usermod','-a','-G',','.join(groups),a.user],check=True)
    for name in ('cloud_images','gui_calibration','inbox'):
        folder=a.data_dir/name;folder.mkdir(exist_ok=True)
        os.chown(folder,account.pw_uid,account.pw_gid)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','so101-platform.service','so101-workbench.service','lightdm.service'],check=True)
    print('INSTALLED_FOR_NEXT_BOOT',backup)
    print('Current services and motors were not restarted. Reboot only after display/kernel acceptance.')

if __name__=='__main__':main()
