# Crypto Data Pipeline

Shared market-data foundation. Both the TSMOM project and the multi-sleeve
portfolio project read from this. Build it once, use it everywhere.

**Start here: `SETUP.md`**

## What it collects

| Dataset | Source | Cadence | History |
|---|---|---|---|
| `spot_klines`  | Binance Vision (bulk) | 1h | 2017+ |
| `perp_klines`  | Binance Vision (bulk) | 1h | 2019-09+ |
| `funding`      | Binance REST          | 8h | 2019-09+ |
| `metrics` (OI) | Binance Vision (bulk) | 5m | ~30d only |

## Commands

```bash
python -m cdp.ingest --backfill   # once
python -m cdp.ingest              # daily (cron does this)
python -m cdp.quality             # ALWAYS run before a backtest
python -m cdp.ingest --summary    # what do I have?
```

## Design rules

1. **Data never enters git.** Code is disposable; data is precious.
2. **Idempotent ingest.** Re-running is always safe.
3. **Fail loud.** A crash beats silent corruption. The timestamp sanity gate
   exists because a wrong-unit epoch will otherwise poison a whole backtest.
4. **`store.read()` is the only public interface.** Strategy code never touches
   raw files.
