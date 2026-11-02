#!/bin/sh
set -eu
# The UI restart propagates through PartOf to these display/input services.
# Restarting them attaches to the loaded platform; it never downloads FPGA.
systemctl start so101-md0700r so101-gt911
systemctl show tcb705-ui so101-md0700r so101-gt911 -p Id -p ActiveState -p SubState -p Result
journalctl -b -u tcb705-ui -n 55 --no-pager
