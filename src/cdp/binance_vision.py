"""
Binance Vision bulk downloader.

Design notes (read these, they explain the non-obvious bits):

1. CHECKSUMS. Every zip has a .CHECKSUM sibling. We verify. Binance has
   silently re-uploaded corrected files in the past; if you don't verify you
   will not notice.

2. THE MICROSECOND TRAP. Binance switched SPOT timestamps to microseconds from
   2025-01-01. Futures stayed in milliseconds. If you blindly do
   pd.to_datetime(unit="ms") you get dates in the year 57000 and your backtest
   silently drops them. We sniff the magnitude and normalise. This is the single
   most likely thing to silently corrupt your data.

3. 404s ARE NORMAL. A symbol didn't exist in 2019, or the current month isn't
   published yet. We treat 404 as "skip", not "fail".

4. IDEMPOTENT. Re-running never re-downloads what's already on disk. You can
   cron this daily and it just tops up.
"""
from __future__ import annotations

import hashlib
import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from pandas.errors import OutOfBoundsDatetime

from . import config as cfg

log = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "cdp/1.0"})


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Target:
    market: str          # "spot" | "futures/um"
    kind: str            # "klines" | "metrics" | ...
    symbol: str
    interval: str | None
    period: str          # "2024-03"  (monthly) or "2024-03-15" (daily)
    monthly: bool

    @property
    def filename(self) -> str:
        if self.interval:
            return f"{self.symbol}-{self.interval}-{self.period}.zip"
        return f"{self.symbol}-{self.kind}-{self.period}.zip"

    @property
    def url(self) -> str:
        freq = "monthly" if self.monthly else "daily"
        parts = [cfg.BINANCE_VISION, "data", self.market, freq, self.kind, self.symbol]
        if self.interval:
            parts.append(self.interval)
        parts.append(self.filename)
        return "/".join(parts)

    @property
    def local_path(self) -> Path:
        return (
            cfg.RAW_DIR / self.market / self.kind / self.symbol / self.filename
        )


# ---------------------------------------------------------------------------
# Download + verify
# ---------------------------------------------------------------------------
def _verify(content: bytes, checksum_text: str) -> bool:
    expected = checksum_text.split()[0].strip()
    actual = hashlib.sha256(content).hexdigest()
    return expected == actual


def download(target: Target, force: bool = False) -> Path | None:
    """Download one archive. Returns local path, or None if unavailable."""
    if target.local_path.exists() and not force:
        return target.local_path

    r = SESSION.get(target.url, timeout=60)
    if r.status_code == 404:
        log.debug("not published: %s", target.filename)
        return None
    r.raise_for_status()
    content = r.content

    # Verify against published checksum
    rc = SESSION.get(target.url + ".CHECKSUM", timeout=30)
    if rc.status_code == 200:
        if not _verify(content, rc.text):
            raise RuntimeError(f"CHECKSUM MISMATCH: {target.url}")
    else:
        log.warning("no checksum published for %s", target.filename)

    target.local_path.parent.mkdir(parents=True, exist_ok=True)
    target.local_path.write_bytes(content)
    log.info("downloaded %s (%.1f KB)", target.filename, len(content) / 1024)
    return target.local_path


# ---------------------------------------------------------------------------
# Timestamp normalisation  -- THE IMPORTANT BIT
# ---------------------------------------------------------------------------
def _to_utc(series: pd.Series) -> pd.Series:
    """
    Convert a Binance epoch column to tz-aware UTC, handling the ms/us split.

    Binance spot moved to MICROSECONDS on 2025-01-01. Futures did not.
    Rather than branch on market+date (fragile), we sniff the magnitude:
      ms  epoch for 2020-2030 is ~1.5e12 - 1.9e12  (13 digits)
      us  epoch for 2020-2030 is ~1.5e15 - 1.9e15  (16 digits)
    """
    s = pd.to_numeric(series, errors="coerce")
    med = s.dropna().median()

    if pd.isna(med):
        # Not epoch integers. Binance's `metrics` files use human-readable
        # datetime strings ("2024-03-01 00:00:00", UTC).
        out = pd.to_datetime(series, utc=True, errors="coerce")
        unit = "datetime-string"
        if out.isna().all():
            raise ValueError("no parseable timestamps")
    else:
        if med > 1e14:
            unit = "us"
        elif med > 1e11:
            unit = "ms"
        else:
            unit = "s"
        try:
            out = pd.to_datetime(s, unit=unit, utc=True)
        except (OverflowError, OutOfBoundsDatetime) as e:
            raise ValueError(
                f"timestamps unrepresentable as unit={unit} (median={med:.3g}): {e}"
            ) from e

    # Sanity gate -- applies to BOTH paths. Anything outside this window means
    # we guessed the format wrong, and it is better to crash loudly than to
    # silently write garbage timestamps into the parquet store.
    lo = pd.Timestamp("2015-01-01", tz="UTC")
    hi = pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=2)
    if out.min() < lo or out.max() > hi:
        raise ValueError(
            f"timestamp out of range after unit={unit}: "
            f"{out.min()} .. {out.max()}"
        )
    return out


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------
def _read_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            raw = f.read()

    # Binance sometimes includes a header row, sometimes not. Sniff it.
    first = raw.split(b"\n", 1)[0].decode("utf-8", "ignore")
    has_header = any(c.isalpha() for c in first.split(",")[0])

    return pd.read_csv(
        io.BytesIO(raw),
        header=0 if has_header else None,
        low_memory=False,
    )


def parse_klines(path: Path, symbol: str) -> pd.DataFrame:
    df = _read_zip(path)
    df = df.iloc[:, : len(cfg.KLINE_COLS)]
    df.columns = cfg.KLINE_COLS

    df["ts"] = _to_utc(df["open_time"])
    for c in ("open", "high", "low", "close", "volume",
              "quote_volume", "taker_buy_base", "taker_buy_quote"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["trades"] = pd.to_numeric(df["trades"], errors="coerce").astype("Int64")
    df["symbol"] = symbol

    keep = ["ts", "symbol", "open", "high", "low", "close", "volume",
            "quote_volume", "trades", "taker_buy_base", "taker_buy_quote"]
    return df[keep].sort_values("ts").reset_index(drop=True)


def parse_metrics(path: Path, symbol: str) -> pd.DataFrame:
    """Open interest + long/short ratios. 5-minute cadence, daily files."""
    df = _read_zip(path)
    df = df.iloc[:, : len(cfg.METRICS_COLS)]
    df.columns = cfg.METRICS_COLS

    df["ts"] = _to_utc(df["create_time"])
    for c in cfg.METRICS_COLS[2:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["symbol"] = symbol

    keep = ["ts", "symbol"] + cfg.METRICS_COLS[2:]
    return df[keep].sort_values("ts").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Period enumeration
# ---------------------------------------------------------------------------
def months_between(start: str, end: str) -> list[str]:
    s = datetime.strptime(start, "%Y-%m")
    e = datetime.strptime(end, "%Y-%m")
    out = []
    while s <= e:
        out.append(s.strftime("%Y-%m"))
        s = (s.replace(day=1) + timedelta(days=32)).replace(day=1)
    return out


def days_between(start: date, end: date) -> list[str]:
    out, d = [], start
    while d <= end:
        out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out
