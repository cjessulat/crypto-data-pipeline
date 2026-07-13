#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# VPS provisioning. Run ONCE on a fresh Ubuntu droplet, as root.
#
#   bash scripts/setup_vps.sh
#
# Creates:
#   /opt/marketdata/        <- the data store (survives code changes)
#   /opt/cdp/               <- this repo
#   /opt/cdp/.venv/         <- python environment
# ---------------------------------------------------------------------------
set -euo pipefail

echo "==> system packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git tmux htop unzip

echo "==> directories"
mkdir -p /opt/marketdata/{raw,parquet,logs,state}
mkdir -p /opt/cdp

echo "==> python venv"
cd /opt/cdp
python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet pandas pyarrow requests

echo "==> environment"
grep -q CDP_DATA_ROOT /etc/environment 2>/dev/null || \
  echo 'CDP_DATA_ROOT=/opt/marketdata' >> /etc/environment

cat <<'EOF'

---------------------------------------------------------------
VPS ready.

  data  -> /opt/marketdata
  code  -> /opt/cdp

Next:
  cd /opt/cdp
  git clone <YOUR_REPO_URL> .
  export CDP_DATA_ROOT=/opt/marketdata
  ./.venv/bin/python -m cdp.ingest --backfill
---------------------------------------------------------------
EOF
