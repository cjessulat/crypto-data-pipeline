"""Multi-venue funding: Bybit, OKX, Hyperliquid. All public, no auth."""
from __future__ import annotations
import time
import pandas as pd
import requests

S = requests.Session()
S.headers.update({"User-Agent": "cdp/1.0"})

# SETTLEMENT INTERVALS DIFFER. Binance/Bybit/OKX = 8h. HYPERLIQUID = 1h.
# Comparing raw funding rates across venues is MEANINGLESS. Annualise first.
PERIODS = {"binance": 3*365, "bybit": 3*365, "okx": 3*365,
           "hyperliquid": 24*365}


def bybit(symbol, start="2021-01-01"):
    """
    Bybit returns NEWEST-FIRST. Page BACKWARDS: walk endTime down toward
    `start`. The original forward-walking version jumped straight to the
    present and returned only the last 200 settlements.
    """
    url = "https://api.bybit.com/v5/market/funding/history"
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp()*1000)
    end_ms = int(pd.Timestamp.now(tz="UTC").timestamp()*1000)
    rows = []
    for _ in range(400):
        r = S.get(url, params={"category": "linear", "symbol": symbol,
                               "startTime": start_ms, "endTime": end_ms,
                               "limit": 200}, timeout=30)
        if r.status_code != 200:
            break
        lst = r.json().get("result", {}).get("list", [])
        if not lst:
            break
        rows.extend(lst)
        oldest = min(int(x["fundingRateTimestamp"]) for x in lst)
        if oldest <= start_ms or len(lst) < 200:
            break
        end_ms = oldest - 1          # step the window BACK
        time.sleep(0.15)
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    return pd.DataFrame({
        "ts": pd.to_datetime(d["fundingRateTimestamp"].astype("int64"),
                             unit="ms", utc=True),
        "symbol": symbol, "venue": "bybit",
        "funding_rate": pd.to_numeric(d["fundingRate"], errors="coerce"),
    }).drop_duplicates(subset=["ts"]).sort_values("ts")


def okx(symbol, start="2021-01-01"):
    """
    OKX pages BACKWARDS. `after` = return records OLDER than this fundingTime.
    Requires BOTH before/after omitted on the first call, then `after` set to
    the oldest ts seen. The earlier version broke early on short pages.
    """
    inst = symbol.replace("USDT", "-USDT-SWAP")
    url = "https://www.okx.com/api/v5/public/funding-rate-history"
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp()*1000)
    rows, after, prev = [], None, None

    for _ in range(500):
        p_ = {"instId": inst, "limit": "100"}
        if after:
            p_["after"] = after
        r = S.get(url, params=p_, timeout=30)
        if r.status_code != 200:
            break
        data = r.json().get("data", [])
        if not data:
            break
        rows.extend(data)
        oldest = min(int(x["fundingTime"]) for x in data)
        if oldest <= start_ms:
            break
        if prev is not None and oldest >= prev:   # no backward progress
            break
        prev = oldest
        after = str(oldest)
        time.sleep(0.12)

    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    out = pd.DataFrame({
        "ts": pd.to_datetime(d["fundingTime"].astype("int64"), unit="ms", utc=True),
        "symbol": symbol, "venue": "okx",
        "funding_rate": pd.to_numeric(d["fundingRate"], errors="coerce"),
    })
    return out[out.ts >= pd.Timestamp(start, tz="UTC")] \
        .drop_duplicates(subset=["ts"]).sort_values("ts")


def hyperliquid(symbol, start="2023-01-01"):
    """
    HL uses BARE coin names ('BTC'), settles HOURLY, caps 500 rows/call.

    FIXED. The first version broke on `len(data) < 500`, treating any short
    page as end-of-history. HL returns short pages MID-HISTORY, so symbols
    silently truncated at 500/1000/1500 rows -- or returned nothing at all,
    which I then misread as "not listed on HL". HL actually lists 232 coins,
    including 24 of our 26.

    Correct rule: only stop when the API returns NOTHING, or when timestamps
    stop advancing.
    """
    coin = symbol.replace("USDT", "")
    url = "https://api.hyperliquid.xyz/info"
    cur = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    rows = []

    for _ in range(2000):          # hourly x 3.5y ~= 30k rows / 500 = 60 pages
        try:
            r = S.post(url, json={"type": "fundingHistory", "coin": coin,
                                  "startTime": cur, "endTime": end_ms},
                       timeout=30)
        except Exception:
            time.sleep(1.0)
            continue
        if r.status_code != 200:
            time.sleep(0.5)
            continue

        data = r.json()
        if not isinstance(data, list) or not data:
            break                  # ONLY a genuinely empty reply ends it

        rows.extend(data)
        newest = max(int(x["time"]) for x in data)
        if newest + 1 <= cur:      # no forward progress -> done
            break
        cur = newest + 1
        if cur >= end_ms:
            break
        time.sleep(0.08)

    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    return pd.DataFrame({
        "ts": pd.to_datetime(d["time"].astype("int64"), unit="ms", utc=True),
        "symbol": symbol, "venue": "hyperliquid",
        "funding_rate": pd.to_numeric(d["fundingRate"], errors="coerce"),
    }).drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)


FETCH = {"bybit": bybit, "okx": okx, "hyperliquid": hyperliquid}


def annualise(df):
    d = df.copy()
    d["funding_ann"] = d["funding_rate"] * d["venue"].map(PERIODS)
    return d


def hl_candles(symbol, start="2023-01-01", interval="1h"):
    """
    Hyperliquid OHLCV via /info candleSnapshot.

    THE QUIRK: when the requested range exceeds the 5000-candle cap, HL IGNORES
    startTime and simply returns the most recent 5000 bars. Forward pagination
    therefore never advances -- every call hands back the same recent window.

    So we page BACKWARDS: walk endTime down from now in 5000-bar chunks until
    we reach `start`.
    """
    coin = symbol.replace("USDT", "")
    url = "https://api.hyperliquid.xyz/info"
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    step = 4900 * 3600 * 1000        # 4900 hours, just under the cap
    rows = []

    for _ in range(60):
        lo = max(start_ms, end_ms - step)
        try:
            r = S.post(url, json={
                "type": "candleSnapshot",
                "req": {"coin": coin, "interval": interval,
                        "startTime": lo, "endTime": end_ms},
            }, timeout=40)
        except Exception:
            time.sleep(1.0)
            continue
        if r.status_code != 200:
            time.sleep(0.5)
            continue

        data = r.json()
        if not isinstance(data, list) or not data:
            break

        rows.extend(data)
        oldest = min(int(x["t"]) for x in data)
        if oldest <= start_ms:
            break
        nxt = oldest - 1
        if nxt >= end_ms:            # no backward progress
            break
        end_ms = nxt
        time.sleep(0.08)

    if not rows:
        return pd.DataFrame()

    d = pd.DataFrame(rows)
    out = pd.DataFrame({
        "ts": pd.to_datetime(d["t"].astype("int64"), unit="ms", utc=True),
        "symbol": symbol,
        "open": pd.to_numeric(d["o"], errors="coerce"),
        "high": pd.to_numeric(d["h"], errors="coerce"),
        "low": pd.to_numeric(d["l"], errors="coerce"),
        "close": pd.to_numeric(d["c"], errors="coerce"),
        "volume": pd.to_numeric(d["v"], errors="coerce"),
        "trades": pd.to_numeric(d["n"], errors="coerce").astype("Int64"),
    })
    out["quote_volume"] = out["volume"] * out["close"]
    out["taker_buy_base"] = float("nan")
    out["taker_buy_quote"] = float("nan")
    return (out[out.ts >= pd.Timestamp(start, tz="UTC")]
            .drop_duplicates(subset=["ts"]).sort_values("ts")
            .reset_index(drop=True))
