#!/bin/sh
# Restore only files and the eth1 address changed by activate_joint_release.sh.
set -eu
BK=${1:?usage: rollback_joint_release.sh backup_directory}
case "$BK" in /home/xilinx/tcb705_deploy_backups/joint_activate_*) ;; *) exit 2 ;; esac
if [ "$(id -u)" != 0 ]; then exec sudo sh "$0" "$BK"; fi
test "$(cat "$BK/COMPLETE")" = joint-release-backup-v1
for path in /etc/systemd/system/tcb705-ui.service.d/zzzzzzzzz-tcb705-joint.conf /home/xilinx/tcb705_data/tcb705.machine.json /etc/network/interfaces.d/eth1; do
    if [ -f "$BK/files$path.absent" ]; then
        rm -f -- "$path"
    else
        test -e "$BK/files$path" || test -L "$BK/files$path"
        cp -a --remove-destination "$BK/files$path" "$path"
    fi
done
if ! grep -q 'inet 192.168.4.23/24 ' "$BK/eth1.addr.before"; then
    if ip -4 -o addr show dev eth1 | grep -q 'inet 192.168.4.23/24 '; then
        ip address del 192.168.4.23/24 dev eth1
    fi
fi
flags=$(cat "$BK/eth1.flags.before")
if [ $((flags & 1)) = 0 ]; then ip link set eth1 down; fi
systemctl daemon-reload
if grep -qx active "$BK/ui.state.before"; then
    systemctl restart tcb705-ui
    systemctl is-active --quiet tcb705-ui
else
    systemctl stop tcb705-ui
fi
echo JOINT_ROLLBACK_OK
