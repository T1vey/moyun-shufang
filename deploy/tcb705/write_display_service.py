"""Replace dependency-bearing unit: systemd drop-ins cannot clear dependencies."""
import os
from pathlib import Path

if os.geteuid()!=0:raise PermissionError('root required')
root=Path(__file__).resolve().parents[2]
python=root/'.venv/bin/python';manifest=root/'overlay/tcb705/platform.json'
unit=f'''[Unit]
Description=TCB705 userspace MD0700R display
Requires=tcb705-ui.service so101-platform.service
BindsTo=tcb705-ui.service so101-platform.service
After=tcb705-ui.service so101-platform.service
PartOf=tcb705-ui.service so101-platform.service
Wants=so101-gt911.service

[Service]
Type=simple
WorkingDirectory={root}
Environment=XILINX_XRT=/usr
ExecStart={python} -B {root}/deploy/pynq-md0700r/md0700r_display.py --runtime {root} --platform-manifest {manifest} --gui-user xilinx --data-dir /home/xilinx/tcb705_data --port 8785 --user-ui-port 8095
Restart=on-failure
RestartSec=3
TimeoutStopSec=infinity

[Install]
WantedBy=multi-user.target
'''
Path('/etc/systemd/system/so101-md0700r.service').write_text(unit)
