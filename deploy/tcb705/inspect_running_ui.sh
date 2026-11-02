set -eu
journalctl -u tcb705-ui --since '2026-10-17 03:09:00 UTC' -n 160 --no-pager
printf '\nDISPLAY_LOG\n'
tail -n 60 /run/so101-lcd/gui.log
printf '\nDISPLAY_STATE\n'
ls -l /run/so101-lcd/gui-screen.png /run/so101-lcd/status.json
cat /run/so101-lcd/status.json
printf '\nSERVICE_STATE\n'
systemctl show tcb705-ui so101-md0700r so101-gt911 -p Id -p ActiveState -p SubState -p NRestarts -p ExecMainStatus
