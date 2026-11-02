#!/bin/sh
# Run on the board; the user enters sudo's password in the interactive terminal.
# No controller commands or FPGA/GE_PL service changes are made here.
set -eu
NEW=/home/xilinx/tcb705_releases/20261018_joint_r1/ZYNQArm
DROP=/etc/systemd/system/tcb705-ui.service.d/zzzzzzzzz-tcb705-joint.conf
MACHINE=/home/xilinx/tcb705_data/tcb705.machine.json
NET=/etc/network/interfaces.d/eth1
test -f "$NEW/scripts/run_tcb705.py"
test -f "$NEW/deploy/tcb705/rollback_joint_release.sh"
if [ "$(id -u)" != 0 ]; then exec sudo sh "$0"; fi
umask 077
BK=$(mktemp -d /home/xilinx/tcb705_deploy_backups/joint_activate_$(date +%Y%m%d_%H%M%S)_XXXXXX)
for path in "$DROP" "$MACHINE" "$NET"; do
    mkdir -p "$BK/files$(dirname "$path")"
    if [ -e "$path" ] || [ -L "$path" ]; then
        cp -a "$path" "$BK/files$path"
    else
        touch "$BK/files$path.absent"
    fi
done
cp -a /etc/systemd/system/tcb705-ui.service "$BK/"
if [ -d /etc/systemd/system/tcb705-ui.service.d ]; then
    cp -a /etc/systemd/system/tcb705-ui.service.d "$BK/"
fi
ip -4 -o addr show dev eth1 > "$BK/eth1.addr.before"
cat /sys/class/net/eth1/flags > "$BK/eth1.flags.before"
systemctl is-active tcb705-ui > "$BK/ui.state.before" || true
systemctl show tcb705-ui -p ExecStart -p DropInPaths > "$BK/ui.before"
cp "$NEW/deploy/tcb705/rollback_joint_release.sh" "$BK/rollback.sh"
printf 'joint-release-backup-v1\n' > "$BK/COMPLETE"
echo "BACKUP=$BK"
echo "ROLLBACK: sudo sh $BK/rollback.sh $BK"
trap 'echo "Activation stopped. Backup and rollback: sudo sh $BK/rollback.sh $BK" >&2' 1 2 15
if grep -q 'inet 192.168.4.23/' "$BK/eth1.addr.before" && ! grep -q 'inet 192.168.4.23/24 ' "$BK/eth1.addr.before"; then
    echo 'Existing eth1 address has a different prefix; no configuration changed.' >&2
    exit 1
fi
install -m 0644 -o xilinx -g xilinx "$NEW/robots/tcb705/profile.armvision_joint.json" "$MACHINE"
mkdir -p "$(dirname "$DROP")"
cat > "$DROP" <<EOF
[Service]
WorkingDirectory=$NEW
ExecStart=
ExecStart=$NEW/.venv/bin/python -B $NEW/scripts/run_tcb705.py --allow-real --no-browser --data-dir /home/xilinx/tcb705_data --secrets-file /home/xilinx/.config/so101/secrets.local.json
EOF
chmod 0644 "$DROP"
cat > "$NET" <<EOF
auto eth1
iface eth1 inet static
address 192.168.4.23
netmask 255.255.255.0
EOF
chmod 0644 "$NET"
if ! grep -q 'inet 192.168.4.23/24 ' "$BK/eth1.addr.before"; then
    ip address add 192.168.4.23/24 dev eth1
fi
ip link set eth1 up
systemctl daemon-reload
systemctl show tcb705-ui -p ExecStart > "$BK/ui.after"
grep -F "$NEW/scripts/run_tcb705.py --allow-real" "$BK/ui.after" >/dev/null
systemctl restart tcb705-ui
sleep 8
systemctl is-active --quiet tcb705-ui
systemctl show tcb705-ui -p ExecStart -p DropInPaths
ip -4 -o addr show eth1
carrier=$(cat /sys/class/net/eth1/carrier)
echo "PL_CARRIER=$carrier"
if [ "$carrier" = 1 ]; then
    ping -I eth1 -c 2 -W 1 192.168.4.4 >/dev/null 2>&1 && echo CONTROLLER_REACHABLE || echo CONTROLLER_NOT_REACHABLE
else
    echo 'CONTROLLER_LINK_DOWN: controller verification and motion must wait.'
fi
echo JOINT_ACTIVATION_OK
echo "ROLLBACK: sudo sh $BK/rollback.sh $BK"
