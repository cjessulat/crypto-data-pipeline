#!/usr/bin/env bash
set -euo pipefail
export CDP_DATA_ROOT=/opt/marketdata
export PYTHONPATH=/opt/cdp/src
cd /opt/cdp
echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) daily update ====="
./.venv/bin/python -m cdp.ingest
./.venv/bin/python -m cdp.quality
echo "===== done ====="
