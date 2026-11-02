# Restore the previous display application; preserve the deployed code and data.
set -eu
drop=/etc/systemd/system/so101-md0700r.service.d/zzzz-tcb705.conf
test -f "$drop"
backup=/home/xilinx/tcb705_deploy_backups/20261017_armvision
test -d "$backup"
systemctl stop so101-gt911.service
systemctl stop so101-md0700r.service
mv "$drop" "$backup/disabled-tcb705-display.conf"
systemctl daemon-reload
systemctl disable --now tcb705-ui.service
systemctl start so101-md0700r.service
systemctl start so101-gt911.service
printf 'PREVIOUS_DISPLAY_RESTORED\n'
