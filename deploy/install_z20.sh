#!/usr/bin/env bash
# Install a reviewed release. No serial IO; target gate loads PL only.
set -euo pipefail
cd "$(dirname "$0")/.."
root_dir="$(pwd -P)"
offline=0
profile=ps
allow_motion=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --offline) offline=1; shift ;;
    --profile) profile="${2:?Expected ps or target}"; shift 2 ;;
    --allow-motion) allow_motion=1; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done
[[ "$profile" == ps || "$profile" == target ]] || { echo 'Profile must be ps or target'; exit 1; }
[[ "$(id -u)" -ne 0 ]] || { echo 'Run as the board login user, not sudo bash'; exit 1; }
board_python="${SO101_PYTHON:-/usr/local/share/pynq-venv/bin/python3}"
[[ -x "$board_python" ]] || board_python=python3
"$board_python" -c 'import sys; assert sys.version_info >= (3,8)'
if [[ "$offline" == 0 ]]; then
  sudo apt-get update
  sudo apt-get install -y python3-venv python3-pip python3-numpy python3-scipy python3-pil python3-opencv python3-skimage python3-serial python3-pyparsing
fi
[[ -x .venv/bin/python ]] || "$board_python" -m venv --system-site-packages .venv
# A venv created from the manufacturer's PYNQ venv inherits system packages,
# but not its parent's site-packages. Reference that runtime without replacing
# the board's installed packages or the release's pinned pure-Python wheels.
.venv/bin/python - "$("$board_python" -c 'import json,site,sys; print(json.dumps(dict(nested=sys.prefix != sys.base_prefix,prefix=sys.prefix,paths=site.getsitepackages())))')" <<'PY'
import json, site, sys
from pathlib import Path
source = json.loads(sys.argv[1])
prefix = Path(source['prefix']).resolve()
paths = []
if source['nested']:
    for name in source['paths']:
        path = Path(name).resolve()
        if path.is_dir() and prefix in path.parents and str(path) not in paths:
            paths.append(str(path))
destination = Path(site.getsitepackages()[0]) / 'so101-pynq-runtime.pth'
destination.write_text(''.join(path + '\n' for path in paths), encoding='utf-8')
print('PYNQ_RUNTIME_PATHS', paths)
PY
if [[ -f PACKAGE_MANIFEST.json ]]; then .venv/bin/python -B scripts/verify_package.py; fi
# Universal wheels are bundled; never resolve/upgrade the board's binary numerics.
.venv/bin/python -m pip --disable-pip-version-check install --no-index --no-deps \
  --find-links dependencies/pynq_wheels -r requirements-pynq.txt
doctor_args=()
if [[ "$profile" == target ]]; then doctor_args+=(--require-pynq); fi
.venv/bin/python -B scripts/doctor.py "${doctor_args[@]}"
.venv/bin/python -B scripts/run_board.py --profile "config/runtime.$profile.json" --check
# systemd does not source the board's login profile. Preserve only the PYNQ
# runtime variables, never the user's cloud credentials or full environment.
if [[ "$profile" == target ]]; then
  .venv/bin/python - "$root_dir/.pynq-service.env" <<'PY'
import json, os, sys
from pathlib import Path
if not os.environ.get('XILINX_XRT'):
    raise SystemExit('Source the PYNQ/XRT login environment before target installation')
lines = []
for key in ('XILINX_XRT', 'PYTHONPATH', 'LD_LIBRARY_PATH'):
    value = os.environ.get(key)
    if value:
        if any(c in value for c in '\n\r\0'):
            raise SystemExit('Invalid PYNQ environment variable: ' + key)
        lines.append(key + '=' + json.dumps(value))
Path(sys.argv[1]).write_text('\n'.join(lines) + '\n', encoding='utf-8')
PY
fi
data_dir="${SO101_DATA_DIR:-$HOME/so101_data}"
mkdir -p "$data_dir"
service_user="$(id -un)"
if [[ "$profile" == target ]]; then service_user=root; fi
motion_arg=''
if [[ "$allow_motion" == 1 ]]; then motion_arg=--allow-motion; fi
unit_temp="$(mktemp)"
trap 'rm -f -- "$unit_temp"' EXIT
cat > "$unit_temp" <<EOF
[Unit]
Description=SO101 target drawing workbench
After=network.target
Conflicts=so101-upstream.service
[Service]
Type=simple
User=$service_user
SupplementaryGroups=dialout
WorkingDirectory=$root_dir
Environment=OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
EnvironmentFile=-$root_dir/.pynq-service.env
ExecStart="$root_dir/.venv/bin/python" -B "$root_dir/scripts/run_board.py" --profile "config/runtime.$profile.json" --data-dir "$data_dir" $motion_arg
Restart=on-failure
RestartSec=3
TimeoutStopSec=8
[Install]
WantedBy=multi-user.target
EOF
previous_units=()
# A runtime update must not interrupt a current drawing/servo job.
if systemctl is-active --quiet so101-workbench.service; then
  .venv/bin/python - <<'PY'
import http.client, json
c = http.client.HTTPConnection('127.0.0.1', 8765, timeout=5)
try:
    c.request('GET', '/api/jobs')
    r = c.getresponse()
    if r.status != 200:
        raise SystemExit('Cannot check current job; runtime was not stopped')
    data = json.loads(r.read())
    if data.get('active') is not None:
        raise SystemExit('Current board job is active; finish it before installing')
finally:
    c.close()
PY
fi
for unit in so101-workbench.service so101-upstream.service; do
  if systemctl is-active --quiet "$unit"; then
    previous_units+=("$unit")
    sudo systemctl stop "$unit"
  fi
done
# Do not load another overlay while the existing workbench owns PL.
if [[ "$profile" == target ]]; then
  gate_environment=("XILINX_XRT=$XILINX_XRT")
  for runtime_key in PYTHONPATH LD_LIBRARY_PATH; do
    if [[ -n "${!runtime_key:-}" ]]; then
      gate_environment+=("$runtime_key=${!runtime_key}")
    fi
  done
  if ! sudo env "${gate_environment[@]}" "$root_dir/.venv/bin/python" -B scripts/check_target_overlay.py --overlay overlay/drawing_target.bit --output "$data_dir/target_board_gate.json"; then
    echo 'Target numerical gate failed; candidate service has not been installed.'
    for unit in "${previous_units[@]}"; do sudo systemctl start "$unit" || true; done
    exit 1
  fi
fi
sudo usermod -aG dialout "$(id -un)"
sudo install -m 644 "$unit_temp" /etc/systemd/system/so101-workbench.service
# Remove old PL command-line overrides only for this managed service.
if [[ -f /etc/systemd/system/so101-workbench.service.d/pl.conf ]]; then
  sudo mv /etc/systemd/system/so101-workbench.service.d/pl.conf /etc/systemd/system/so101-workbench.service.d/pl.conf.disabled
fi
if [[ -f /etc/systemd/system/so101-upstream.service ]]; then
  sudo systemctl disable --now so101-upstream.service
fi
sudo systemctl daemon-reload
sudo systemctl enable so101-workbench.service
sudo systemctl restart so101-workbench.service
.venv/bin/python - "$profile" <<'PY'
import http.client, json, sys, time
deadline = time.monotonic() + 60
last = 'Not started'
while time.monotonic() < deadline:
    connection = http.client.HTTPConnection('127.0.0.1', 8765, timeout=2)
    try:
        connection.request('GET', '/api/status')
        response = connection.getresponse()
        status = json.loads(response.read())
        if response.status != 200:
            raise RuntimeError('HTTP ' + str(response.status))
        if sys.argv[1] == 'target' and status.get('ik_backend') != 'PL_z20_ik_target':
            raise RuntimeError('Wrong target backend')
        if status.get('ik_metrics', {}).get('faulted'):
            raise RuntimeError('Target session faulted')
        print('SERVICE_HTTP_READY', status.get('version'), status.get('ik_backend'))
        break
    except (OSError, ValueError, RuntimeError) as exc:
        last = str(exc)
        time.sleep(.5)
    finally:
        connection.close()
else:
    raise SystemExit('Service HTTP readiness failed: ' + last)
PY
sudo systemctl --no-pager status so101-workbench.service
echo "Installed profile=$profile; calibration/data=$data_dir; board port=8765"
echo 'PC: deploy/tunnel.ps1, then launch_pc.ps1. No servo command has been sent by installation.'
