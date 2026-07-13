"""
Central configuration. Everything that might change lives here.

DATA_ROOT is the single source of truth for where data lives.
Override with the CDP_DATA_ROOT environment variable so the same code
runs on Windows (desktop) and Linux (VPS) without edits.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# On VPS   -> /opt/marketdata
# On Windows -> C:\marketdata
_default_root = "/opt/marketdata" if os.name != "nt" else r"C:\marketdata"
DATA_ROOT = Path(os.environ.get("CDP_DATA_ROOT", _default_root))

RAW_DIR = DATA_ROOT / "raw"        # downloaded zips (can be deleted after parse)
PARQUET_DIR = DATA_ROOT / "parquet"  # the actual dataset you query
LOG_DIR = DATA_ROOT / "logs"
STATE_DIR = DATA_ROOT / "state"    # download manifests / checkpoints

BINANCE_VISION = "https://data.binance.vision"

# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------
# Start deliberately small. Expanding the universe is a one-line change;
# un-expanding it after you've overfit to 200 assets is not.
#
# SURVIVORSHIP WARNING: this is a hand-picked list of things that exist TODAY.
# Backtests on it are biased. See docs before drawing conclusions.
CORE_UNIVERSE = [
    # 26 crypto perps, 3+ years of history.
    #
    # EXCLUDES Binance's tokenized-equity perps (NVDA, MSTR, QQQ, INTC...).
    # Their funding is driven by equity borrow demand, NOT crypto leverage
    # demand -- a different mechanism. Including them would pollute the
    # cross-section with instruments that do not share the effect we harvest.
    #
    # SURVIVORSHIP BIAS -- MEASURED, NOT HYPOTHETICAL:
    # MATIC, FTM, EOS and MKR were all major perps, now DELISTED. That is ~9%
    # of a hand-picked list, and there are surely more we never thought to
    # name. Every result from this universe is an OPTIMISTIC UPPER BOUND: the
    # strategy gets credit for dodging disasters it never actually faced.
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT",
    "DOTUSDT", "UNIUSDT", "ATOMUSDT", "ETCUSDT", "XLMUSDT",
    "BCHUSDT", "FILUSDT", "NEARUSDT", "AAVEUSDT", "TRXUSDT",
    "ICPUSDT", "ALGOUSDT", "VETUSDT", "THETAUSDT", "SNXUSDT",
    "CRVUSDT",
]

# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------
# market: "spot" | "futures/um"
# kind:   binance-vision data_type
DATASETS = {
    "spot_klines": {
        "market": "spot",
        "kind": "klines",
        "interval": "1h",
        "monthly": True,
    },
    "perp_klines": {
        "market": "futures/um",
        "kind": "klines",
        "interval": "1h",
        "monthly": True,
    },
    # Funding rate is embedded in premiumIndexKlines? No -- it is its own
    # fundingRate dataset on futures. Handled separately (see funding.py).
    "premium_index": {
        "market": "futures/um",
        "kind": "premiumIndexKlines",
        "interval": "1h",
        "monthly": True,
    },
    # metrics = open interest + long/short ratios. DAILY ONLY on Binance Vision.
    "metrics": {
        "market": "futures/um",
        "kind": "metrics",
        "interval": None,
        "monthly": False,
    },
}

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]

METRICS_COLS = [
    "create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
    "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
    "count_long_short_ratio", "sum_taker_long_short_vol_ratio",
]


def ensure_dirs() -> None:
    for d in (RAW_DIR, PARQUET_DIR, LOG_DIR, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)
