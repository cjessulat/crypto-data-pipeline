"""
Funding rate history.

Funding is NOT in the Binance Vision bulk archive -- it only comes from the
REST endpoint /fapi/v1/fundingRate, which is capped at 1000 rows per call.
Funding is 8-hourly, so 1000 rows ~= 333 days. We paginate forward.

This is slow the first time (a few minutes for 10 symbols x several years)
and near-instant on subsequent incremental runs.
"""
from __future__ import annotations

import logging
import time

import pandas as pd
import requests

log = logging.getLogger(__name__)

FAPI = "https://fapi.binance.com/fapi/v1/fundingRate"
LIMIT = 1000

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "cdp/1.0"})


def fetch_funding(symbol: str, start: str = "2019-09-01",
                  end: str | None = None, pause: float = 0.25) -> pd.DataFrame:
    """
    Pull complete funding history for one symbol.

    Returns columns: ts, symbol, funding_rate, mark_price
    """
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(
        (pd.Timestamp(end, tz="UTC") if end else pd.Timestamp.now(tz="UTC"))
        .timestamp() * 1000
    )

    rows: list[dict] = []
    cursor = start_ms

    while cursor < end_ms:
        r = SESSION.get(
            FAPI,
            params={"symbol": symbol, "startTime": cursor,
                    "endTime": end_ms, "limit": LIMIT},
            timeout=30,
        )
        if r.status_code == 429:
            log.warning("rate limited; backing off 60s")
            time.sleep(60)
            continue
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break

        rows.extend(batch)
        last = int(batch[-1]["fundingTime"])
        if last <= cursor:      # no forward progress -> done
            break
        cursor = last + 1

        if len(batch) < LIMIT:  # partial page -> caught up
            break
        time.sleep(pause)

    if not rows:
        return pd.DataFrame(
            columns=["ts", "symbol", "funding_rate", "mark_price"]
        )

    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["symbol"] = symbol
    df["funding_rate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
    df["mark_price"] = pd.to_numeric(
        df.get("markPrice", pd.NA), errors="coerce"
    )

    df = (df[["ts", "symbol", "funding_rate", "mark_price"]]
          .drop_duplicates(subset=["ts", "symbol"])
          .sort_values("ts")
          .reset_index(drop=True))

    # Funding is a PERIOD rate (per 8h), not annualised. Do the conversion at
    # analysis time, not here -- storing derived columns invites inconsistency.
    return df
