#!/usr/bin/env bash
# Board-local installer entry point. For PC upload use deploy_z20.ps1.
set -euo pipefail
exec bash "$(dirname "$0")/install_z20.sh" "$@"
