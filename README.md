# NIFTY ATM Tracker — 9:16 vs 3:29

Each weekday this records NIFTY's **ATM option** based on the **9:16 spot price**, then
re-prices that same Call (CE) and Put (PE) at **3:29**, and shows the history on a webpage.

A scheduled GitHub Action runs the scraper twice a day and commits the data; GitHub
Pages serves a table of every day's spot, chosen ATM strike, and the CE/PE values at
9:16 and 3:29.

```
fetch_atm.py                 → nsepython scraper: picks ATM from 9:16 spot, re-prices at 3:29
index.html                   → the webpage (reads data.json)
data.json                    → stored history (refreshed by the Action)
requirements.txt             → nsepython
.github/workflows/update.yml → two scheduled runs (9:16 & 3:29 IST) + manual trigger
```

## How it works

The 9:16 run reads the option chain, finds the strike nearest the spot for the nearest
expiry, and stores the spot, strike, and the CE/PE last price. The 3:29 run finds today's
record and re-prices that **same** strike/expiry, storing the close values. The script
decides what to do from the stored record (not the clock), so a delayed run still behaves
correctly, and a duplicate morning run won't prematurely fill the close.

**Distinct fingerprint:** this repo overrides nsepython's request headers with its own
pool of non-Chrome browser fingerprints (Firefox / Safari) and picks one at random per
run, so it doesn't look like an identical bot to other scrapers you run.

## One-time setup

1. Create a new GitHub repo and upload these files (keep `.github/workflows/update.yml`
   in place).
2. **Settings → Pages** → deploy from branch `main` / root → your page is at
   `https://<username>.github.io/<repo>/`.
3. **Settings → Actions → General → Workflow permissions → Read and write** (lets the
   Action commit `data.json`).
4. **Actions tab → Track NIFTY ATM → Run workflow** to test it once.

## Schedule

`03:46 UTC` = 09:16 IST (open capture) and `09:59 UTC` = 15:29 IST (close capture),
weekdays. GitHub's scheduler isn't second-precise and can run a few minutes late, so the
script saves the **actual** fetch time with each value.

## Important: cloud IP blocking

NSE frequently throttles or blocks datacenter IPs, including GitHub Actions runners.
Rotating browser headers helps with bot heuristics but **not** with IP reputation, so a
cloud run may sometimes return an empty chain (the script raises a clear error when that
happens). If it's unreliable on Actions, run it from your own machine or a small VPS on a
residential/most-trusted IP:

```bash
pip install -r requirements.txt
python fetch_atm.py          # run once ~9:16, once ~3:29 (e.g. via your own cron)
python -m http.server        # then open http://localhost:8000 to view
```

Unofficial, for personal use. Always verify against NSE directly.
