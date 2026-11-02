set -eu
nmcli -t -f SSID,SIGNAL,SECURITY device wifi list ifname wlan0 | grep '^ESP8200:' || true
nmcli --wait 20 connection up so101-ESP8200 || true
ip -brief -4 address
ip -4 route
systemctl is-active so101-bluetooth
