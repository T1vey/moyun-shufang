#!/bin/sh
set -eu
systemctl is-active tcb705-ui so101-md0700r so101-gt911
journalctl -b -u tcb705-ui --no-pager | grep -E 'LINEART_ATTACH_PREPARE|ImportError|Traceback' | tail -n 12
