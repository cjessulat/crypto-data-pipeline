#!/usr/bin/env bash
# Nightly incremental top-up. Wire into cron:
#
#   crontab -e
#   15 1 * * * /opt/cdp/scripts/daily_update.sh >> /opt/marketdata/logs/cron.log 2>&1
#
# 01:15 UTC: Binance publishes the previous day's files shortly after 00:00 UTC,
# so this gives them an hour of slack.
set -euo pipefail

export CDP_DATA_ROOT=/opt/marketdata
cd /opt/cdp

echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) daily update ====="
./.venv/bin/python -m cdp.ingest
./.venv/bin/python -m cdp.quality
echo "===== done ====="
