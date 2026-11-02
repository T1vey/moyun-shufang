set -eu
systemctl cat so101-platform so101-workbench tcb705-ui so101-md0700r so101-gt911
cat /etc/so101/desktop.env
sudo -n cat /run/so101-platform/ready.json
