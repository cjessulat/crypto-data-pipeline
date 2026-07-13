"""
The ingest runner. This is the one command you actually type.

    python -m cdp.ingest --backfill          # first run: pull all history
    python -m cdp.ingest                     # daily: top up recent data
    python -m cdp.ingest --summary           # what do I have?

Idempotent. Safe to re-run. Safe to cron.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

import pandas as pd

from . import binance_vision as bv
from . import config as cfg
from . import funding
from . import store

log = logging.getLogger("cdp")


def _setup_logging() -> None:
    cfg.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(cfg.LOG_DIR / "ingest.log"),
        ],
    )


# ---------------------------------------------------------------------------
def ingest_monthly(dataset: str, symbols: list[str],
                   start: str, end: str) -> None:
    spec = cfg.DATASETS[dataset]
    for sym in symbols:
        got = 0
        for period in bv.months_between(start, end):
            out_dir = cfg.PARQUET_DIR / dataset / f"symbol={sym}"
            if (out_dir / f"{sym}-{period}.parquet").exists():
                continue

            tgt = bv.Target(spec["market"], spec["kind"], sym,
                            spec["interval"], period, monthly=True)
            try:
                path = bv.download(tgt)
                if path is None:
                    continue          # not published (pre-listing / current month)
                df = bv.parse_klines(path, sym)
                store.write(df, dataset, sym, period)
                got += 1
            except Exception as e:  # noqa: BLE001
                log.error("%s %s %s: %s", dataset, sym, period, e)
        if got:
            log.info("%-14s %-10s +%d months", dataset, sym, got)


def ingest_metrics(symbols: list[str], days_back: int) -> None:
    """Open interest + long/short ratios. Daily files only."""
    spec = cfg.DATASETS["metrics"]
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days_back)

    for sym in symbols:
        got = 0
        for period in bv.days_between(start, end):
            out_dir = cfg.PARQUET_DIR / "metrics" / f"symbol={sym}"
            if (out_dir / f"{sym}-{period}.parquet").exists():
                continue

            tgt = bv.Target(spec["market"], spec["kind"], sym,
                            None, period, monthly=False)
            try:
                path = bv.download(tgt)
                if path is None:
                    continue
                df = bv.parse_metrics(path, sym)
                store.write(df, "metrics", sym, period)
                got += 1
            except Exception as e:  # noqa: BLE001
                log.error("metrics %s %s: %s", sym, period, e)
        if got:
            log.info("%-14s %-10s +%d days", "metrics", sym, got)


def ingest_funding(symbols: list[str], start: str) -> None:
    """
    Funding comes from the REST API, not the bulk archive.
    We rewrite the whole per-symbol file each time -- funding history is small
    (a few thousand rows), so this is cheap and avoids append-boundary bugs.
    """
    for sym in symbols:
        try:
            df = funding.fetch_funding(sym, start=start)
            if df.empty:
                continue
            store.write(df, "funding", sym, "all")
            log.info("%-14s %-10s %d rows  %s -> %s", "funding", sym, len(df),
                     df.ts.min().date(), df.ts.max().date())
        except Exception as e:  # noqa: BLE001
            log.error("funding %s: %s", sym, e)


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Crypto market data ingest")
    ap.add_argument("--backfill", action="store_true",
                    help="pull full history (slow, run once)")
    ap.add_argument("--summary", action="store_true",
                    help="print what's in the store and exit")
    ap.add_argument("--start", default="2019-09",
                    help="backfill start month, YYYY-MM")
    ap.add_argument("--symbols", nargs="*", default=None,
                    help="override the universe")
    args = ap.parse_args()

    _setup_logging()
    symbols = args.symbols or cfg.CORE_UNIVERSE

    if args.summary:
        s = store.summary()
        print(s.to_string(index=False) if not s.empty else "store is empty")
        return

    end = pd.Timestamp.now(tz="UTC").strftime("%Y-%m")
    start = args.start if args.backfill else (
        pd.Timestamp.now(tz="UTC") - pd.DateOffset(months=2)
    ).strftime("%Y-%m")

    log.info("=" * 62)
    log.info("ingest | %d symbols | %s -> %s | root=%s",
             len(symbols), start, end, cfg.DATA_ROOT)
    log.info("=" * 62)

    ingest_monthly("spot_klines", symbols, start, end)
    ingest_monthly("perp_klines", symbols, start, end)
    # Funding rewrites the whole per-symbol file, so it must ALWAYS pull
    # full history -- never the incremental window, or we destroy the past.
    ingest_funding(symbols, start="2019-09-01")
    # Binance only retains ~1 month of metrics/OI files. Nothing we can do.
    ingest_metrics(symbols, days_back=30)

    log.info("-" * 62)
    s = store.summary()
    if not s.empty:
        print(s.to_string(index=False))
        print(f"\ntotal: {s['rows'].sum():,} rows | {s['mb'].sum():.1f} MB")


if __name__ == "__main__":
    main()
