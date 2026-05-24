"""
NSE NIFTY ATM tracker.

Runs twice on weekdays:
  * ~09:16 IST  -> reads the option chain, finds the ATM strike from the 09:16 spot,
                   and records the ATM Call (CE) and Put (PE) last price.
  * ~15:29 IST  -> re-prices that SAME strike/expiry and records the close value.

Uses nsepython's nse_optionchain_scrapper. To avoid looking like the same client as
other scrapers, this repo overrides nsepython's request headers with its own pool of
browser fingerprints (Firefox / Safari) — deliberately different from a Chrome-based
scraper — and picks one at random each run.

The script is self-healing: the 09:16 run fills the "open" fields; the 15:29 run sees
those filled and fills the "close" fields for the strike chosen at 09:16. It decides
what to do from the stored record, not from the wall clock, so a delayed run still
behaves correctly.

NOTE: NSE often throttles datacenter IPs (incl. GitHub Actions runners). Different
headers help with bot heuristics but not IP reputation, so runs from a cloud runner
may intermittently return empty data. Running from your own machine/VPS is more
reliable. See README.
"""

import os
import json
import random
import datetime as dt
import zoneinfo

import nsepython

SYMBOL = "NIFTY"
DATA_FILE = "data.json"
IST = zoneinfo.ZoneInfo("Asia/Kolkata")

# A small pool of NON-Chrome fingerprints, chosen at random each run, so repeated
# calls don't all look like one identical bot.
HEADER_POOL = [
    {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-GB,en;q=0.7,en-US;q=0.3",
        "accept-encoding": "gzip, deflate, br",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0",
        "upgrade-insecure-requests": "1",
        "sec-fetch-dest": "document", "sec-fetch-mode": "navigate", "sec-fetch-site": "none",
        "te": "trailers", "connection": "keep-alive",
    },
    {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "accept-encoding": "gzip, deflate, br",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "upgrade-insecure-requests": "1",
        "sec-fetch-dest": "document", "sec-fetch-mode": "navigate", "sec-fetch-site": "none",
        "connection": "keep-alive",
    },
    {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-IN,en;q=0.9",
        "accept-encoding": "gzip, deflate, br",
        "user-agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
        "upgrade-insecure-requests": "1",
        "sec-fetch-dest": "document", "sec-fetch-mode": "navigate", "sec-fetch-site": "none",
        "te": "trailers", "connection": "keep-alive",
    },
]


def configure_headers():
    """Point nsepython at one of our fingerprints for this run."""
    nsepython.headers = random.choice(HEADER_POOL)


def fetch_chain():
    """Fetch the raw NIFTY option chain (overridable in tests)."""
    return nsepython.nse_optionchain_scrapper(SYMBOL)


def pick_atm(chain):
    """From the chain, choose the strike nearest the spot for the nearest expiry."""
    rec = chain["records"]
    spot = float(rec["underlyingValue"])
    expiry = rec["expiryDates"][0]
    cand = [d for d in rec["data"]
            if d.get("expiryDate") == expiry and "CE" in d and "PE" in d]
    if not cand:
        raise RuntimeError("no CE/PE rows for the nearest expiry")
    atm = min(cand, key=lambda d: abs(float(d["strikePrice"]) - spot))
    strike = atm["strikePrice"]
    return {
        "spot": spot, "expiry": expiry, "atm_strike": strike,
        "ce_ltp": atm["CE"].get("lastPrice"),
        "pe_ltp": atm["PE"].get("lastPrice"),
        "ce_label": f"{SYMBOL} {expiry} {strike} CE",
        "pe_label": f"{SYMBOL} {expiry} {strike} PE",
    }


def price_strike(chain, expiry, strike):
    """Re-price a known strike/expiry. Returns (ce_ltp, pe_ltp, spot)."""
    rec = chain["records"]
    for d in rec["data"]:
        if d.get("expiryDate") == expiry and float(d["strikePrice"]) == float(strike):
            return d.get("CE", {}).get("lastPrice"), d.get("PE", {}).get("lastPrice"), float(rec["underlyingValue"])
    return None, None, float(rec["underlyingValue"])


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"symbol": SYMBOL, "updated_ist": None, "records": []}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def run(now=None):
    configure_headers()
    now = now or dt.datetime.now(IST)
    today = now.date().isoformat()

    chain = fetch_chain()
    if not chain or "records" not in chain or not chain["records"].get("data"):
        raise RuntimeError(
            "Empty option chain — NSE likely blocked this request "
            "(common from cloud IPs). Try re-running or run from your own machine."
        )

    data = load_data()
    records = data["records"]
    rec = next((r for r in records if r["date"] == today), None)

    if rec is None or rec.get("ce_open") is None:
        # OPEN capture (the ~09:16 run).
        atm = pick_atm(chain)
        if rec is None:
            rec = {"date": today}
            records.append(rec)
        rec.update({
            "expiry": atm["expiry"], "atm_strike": atm["atm_strike"],
            "spot_open": round(atm["spot"], 2),
            "ce_label": atm["ce_label"], "pe_label": atm["pe_label"],
            "ce_open": atm["ce_ltp"], "pe_open": atm["pe_ltp"],
            "open_time": now.strftime("%H:%M:%S IST"),
            "ce_close": rec.get("ce_close") if rec else None,
            "pe_close": rec.get("pe_close") if rec else None,
            "spot_close": rec.get("spot_close") if rec else None,
            "close_time": rec.get("close_time") if rec else None,
        })
        print(f"OPEN captured: ATM {atm['atm_strike']} | CE {atm['ce_ltp']} | PE {atm['pe_ltp']} | spot {atm['spot']}")
    elif rec.get("ce_close") is None and now.hour >= 13:
        # CLOSE capture (the ~15:29 run): re-price the strike chosen at open.
        ce, pe, spot = price_strike(chain, rec["expiry"], rec["atm_strike"])
        rec.update({
            "ce_close": ce, "pe_close": pe, "spot_close": round(spot, 2),
            "close_time": now.strftime("%H:%M:%S IST"),
        })
        print(f"CLOSE captured: ATM {rec['atm_strike']} | CE {ce} | PE {pe} | spot {spot}")
    else:
        print("Nothing to do (open already captured; close fills only after 13:00 IST).")

    records.sort(key=lambda r: r["date"], reverse=True)
    data["updated_ist"] = now.strftime("%d %b %Y, %I:%M %p IST")
    save_data(data)


if __name__ == "__main__":
    run()
