# Setup Runbook

Every command below is tagged with **where it runs**. Never run a `[VPS]`
command on Windows or vice versa.

---

## The mental model (read this first)

There are **two machines** and they have **different jobs**:

| | Windows desktop | DigitalOcean VPS |
|---|---|---|
| **Job** | Edit code. Read results. | Run code. Store data. |
| **Code lives at** | `C:\dev\crypto-data-pipeline` | `/opt/cdp` |
| **Data lives at** | *(nothing — or a small test copy)* | `/opt/marketdata` |
| **Runs 24/7?** | No | Yes |

**The link between them is git. Not copy-paste. Not FTP.**

```
  Windows  --git push-->  GitHub  --git pull-->  VPS
  (edit)                                         (run)
```

Why this matters: if you edit files in both places, you *will* eventually run a
stale version and not know it. One source of truth. Always.

**The one rule that prevents all the mess:**
> Code is disposable and lives in git. Data is precious and lives only on the
> VPS at `/opt/marketdata`. Never put data in the git repo.

---

## Part 1 — Windows desktop

### 1.1 Install prerequisites

**[WINDOWS / PowerShell as Administrator]**
```powershell
winget install -e --id Git.Git
winget install -e --id Python.Python.3.12
```

Close PowerShell and reopen it (so PATH updates). Verify:

**[WINDOWS / PowerShell]**
```powershell
git --version
python --version
```

### 1.2 Create your code folder

**[WINDOWS / PowerShell]**
```powershell
mkdir C:\dev
cd C:\dev
```

> **Why `C:\dev` and not Desktop/Documents?** OneDrive syncs those folders and
> will fight with git, corrupting your repo. Keep code out of synced folders.

Unzip the pipeline I gave you into `C:\dev\crypto-data-pipeline`.

### 1.3 Put it in git

**[WINDOWS / PowerShell]**
```powershell
cd C:\dev\crypto-data-pipeline
git init
git add .
git commit -m "initial data pipeline"
```

Now create an **empty private repo** on github.com (no README), then:

**[WINDOWS / PowerShell]**
```powershell
git remote add origin https://github.com/YOURNAME/crypto-data-pipeline.git
git branch -M main
git push -u origin main
```

---

## Part 2 — The VPS

### 2.1 Create the droplet

On digitalocean.com:
- **Image:** Ubuntu 24.04 LTS
- **Plan:** Basic → Regular → **$12/mo (2GB RAM / 50GB SSD)**
- **Auth:** SSH key (not password)
- **Region:** whichever is closest to you

> **Why 2GB and not the $6 option?** pyarrow needs headroom to build parquet
> files. The $6/1GB droplet will OOM during backfill. 50GB disk is comfortable
> for years of hourly data on a modest universe.

### 2.2 Connect

**[WINDOWS / PowerShell]**
```powershell
ssh root@YOUR_DROPLET_IP
```

Everything after this point runs **on the VPS** until I say otherwise.

### 2.3 Provision

**[VPS / bash]**
```bash
apt-get update && apt-get install -y git
mkdir -p /opt/cdp && cd /opt/cdp
git clone https://github.com/YOURNAME/crypto-data-pipeline.git .
bash scripts/setup_vps.sh
```

### 2.4 Backfill

**[VPS / bash]**
```bash
cd /opt/cdp
export CDP_DATA_ROOT=/opt/marketdata

tmux new -s backfill
./.venv/bin/python -m cdp.ingest --backfill
```

> **Use tmux.** The backfill takes 30–90 minutes. Without tmux, closing your
> laptop kills it. With tmux: press `Ctrl+B` then `D` to detach, close the
> laptop, and later `tmux attach -t backfill` to check on it.

### 2.5 Verify

**[VPS / bash]**
```bash
./.venv/bin/python -m cdp.quality
```

**Read the output. Do not skip this.** If completeness is below 98% or you see
flagged outliers, tell me before running any backtest.

### 2.6 Automate

**[VPS / bash]**
```bash
chmod +x /opt/cdp/scripts/daily_update.sh
crontab -e
```

Add this line, save, exit:
```
15 1 * * * /opt/cdp/scripts/daily_update.sh >> /opt/marketdata/logs/cron.log 2>&1
```

---

## Part 3 — The daily loop

Once set up, this is your entire workflow:

**[WINDOWS]** — edit code, then:
```powershell
cd C:\dev\crypto-data-pipeline
git add .
git commit -m "what I changed"
git push
```

**[VPS]** — pull and run:
```bash
cd /opt/cdp
git pull
./.venv/bin/python -m cdp.ingest
```

That's it. Two commands on each side.

---

## Reading the data

**[VPS / bash]**
```bash
cd /opt/cdp
export CDP_DATA_ROOT=/opt/marketdata
./.venv/bin/python
```

```python
from cdp import store

# what have I got?
print(store.summary())

# hourly perp bars
df = store.read("perp_klines", ["BTCUSDT"], start="2023-01-01")

# cross-sectional matrix -- what a strategy actually consumes
wide = store.read("perp_klines", start="2024-01-01").pivot(
    index="ts", columns="symbol", values="close")

# funding
f = store.read("funding", ["BTCUSDT"])
```

---

## Known limits (be honest about these)

| Dataset | History | Note |
|---|---|---|
| `spot_klines` | 2017+ | Deep. Your research backbone. |
| `perp_klines` | 2019-09+ | Binance futures launch. |
| `funding` | 2019-09+ | 8-hourly. From REST, not bulk. |
| `metrics` (OI) | **~30 days only** | Binance does not retain history. |

**The OI limitation is the important one.** You cannot backtest an
open-interest signal on more than a month of data — because the history does
not exist anywhere for free. The cron job accumulates it going forward, so it
becomes usable in ~6 months. Start collecting now, use it later.

**Survivorship bias.** `CORE_UNIVERSE` is ten coins that exist *today*. A
backtest on it is biased upward — you've implicitly excluded everything that
died. This is a real distortion in crypto, where the death rate is high. Treat
any cross-sectional result from this universe as an optimistic upper bound
until we build a point-in-time listing table.
