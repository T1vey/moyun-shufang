#!/bin/sh
# Install the receiver service only. Kernel/module/firmware setup is separate.
set -eu
if [ "$(id -u)" != 0 ]; then
    echo "Run this installer using sudo." >&2
    exit 1
fi
runtime=${1:?Usage: install.sh ABSOLUTE_RUNTIME [ABSOLUTE_DATA_DIR]}
data_dir=${2:-/home/xilinx/so101_data_work107}
case "$runtime:$data_dir" in *'"'*|*'\'*|*'
'*) echo "Paths must not contain quotes, backslashes or newlines." >&2; exit 1;; esac
case "$runtime" in /*) ;; *) echo "Runtime path must be absolute." >&2; exit 1;; esac
case "$data_dir" in /*) ;; *) echo "Data path must be absolute." >&2; exit 1;; esac
test -f "$runtime/scripts/bluetooth_receiver.py"
test -f "$runtime/bluetooth_inbox.py"
test -x /usr/lib/bluetooth/obexd
test -x /usr/bin/dbus-run-session
/usr/bin/python3 -c 'import dbus, gi; from PIL import Image'
install -d -m 0700 -o xilinx -g xilinx "$data_dir/.bluetooth_staging"
install -d -m 0750 -o xilinx -g xilinx "$data_dir/bluetooth_images"
printf 'SO101_RUNTIME="%s"\nSO101_DATA_DIR="%s"\n' "$runtime" "$data_dir" > /etc/so101-bluetooth.env
chmod 0644 /etc/so101-bluetooth.env
install -m 0644 "$runtime/deploy/bluetooth/so101-bluetooth.service" /etc/systemd/system/so101-bluetooth.service
systemctl daemon-reload
systemctl enable so101-bluetooth.service
systemctl restart so101-bluetooth.service
