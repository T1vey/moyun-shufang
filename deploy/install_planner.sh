#!/usr/bin/env bash
# Planner-v2 installation has a separate, transactional entry point.
# Run with sudo after extracting into a NEW permanent release directory.
set -euo pipefail
root_dir="$(cd "$(dirname "$0")/.." && pwd -P)"
exec "${SO101_INSTALL_PYTHON:-/usr/bin/python3}" -B "$root_dir/scripts/install_planner_runtime.py" "$@"
