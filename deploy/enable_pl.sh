#!/usr/bin/env bash
# Select the delivered complete-target hardware after user compilation.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "${1:-target}" == target ]] || { echo 'This delivery uses target. For PS use install_z20.sh --profile ps.'; exit 1; }
shift "$(( $# > 0 ? 1 : 0 ))"
exec bash deploy/install_z20.sh --offline --profile target "$@"
