#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
IVF_DATA_DIR=${1:-/var/dataset}
if [ "$#" -gt 0 ]; then shift; fi
exec python3 scripts/run_experiments.py \
  --data-dir "$IVF_DATA_DIR" \
  --out "results/server_full_$(date +%Y%m%d_%H%M%S)" \
  "$@"
