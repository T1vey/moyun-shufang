set -eu
printf 'USB_CURRENT\n'
lsusb
lsusb -t
printf 'USB_KERNEL\n'
dmesg | grep -Ei 'usb|8723|8821|bluetooth|firmware|wlan' | tail -45
printf 'WIRELESS_DRIVERS\n'
lsmod | grep -Ei 'bluetooth|btusb|btrtl|rtl|8723|8821' || true
printf 'TOUCH_DISPLAY_CURRENT\n'
cat /run/so101-lcd/status.json || true
journalctl -b -u so101-gt911 -n 8 --no-pager
printf 'USB_HOST_SETUP\n'
systemctl cat so101-usb-host
printf 'CLOCK\n'
date -Is
printf 'VENV\n'
/home/xilinx/so101_releases/release_planner_20261011_a8f65f66/so101_planner_runtime/.venv/bin/python -c 'import numpy,PIL,serial;print(numpy.__version__,PIL.__version__,serial.__version__)'
