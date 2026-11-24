"""
Backtest: measure the REAL accuracy of the strategies on past candles.

Quotex OTC/live (phone, with QUOTEX_EMAIL/PASSWORD in .env):
    python backtest.py                 -> all pairs, OTC, last ~16 hours
    python backtest.py EURUSD_otc      -> one pair
    python backtest.py live            -> live (non-OTC) pairs
Real forex / crypto (DATA_SOURCE=forex):
    python backtest.py EURUSD 5000

Rule (same as the live bot): signal on closed candle i -> the trade starts one minute later
(entry = close of candle i+1, exit = close of candle i+2), because members need time to
place the trade. No overlapping trades.
"""
import sys
import time

import pandas as pd

import config
from strategy import analyze, analyze_v2
from rules import order_block_signals


def analyze_ob_bt(df, min_score=0, force=False):
    d = order_block_signals(df.tail(200).reset_index(drop=True))[-1]
    return {"direction": "CALL" if d > 0 else "PUT"} if d else None


TESTS = [  # (name, function, min_score, force)
    ("old: signal every time", analyze, 4, True),
    ("old: score>=4", analyze, 4, False),
    ("v2: score>=4", analyze_v2, 4, False),
    ("v2: score>=5", analyze_v2, 5, False),
    ("v2: score>=6", analyze_v2, 6, False),
    ("order block", analyze_ob_bt, 0, False),
]


def run(df, fn, min_score, force, expiry=1, window=200, delay=1):
    w = l = 0
    i = window
    closes = df["close"].values
    while i < len(df) - expiry - delay:
        sig = fn(df.iloc[i - window:i + 1], min_score, force=force)
        if sig:
            entry, exit_ = closes[i + delay], closes[i + delay + expiry]
            if exit_ != entry:
                if (exit_ > entry) == (sig["direction"] == "CALL"):
                    w += 1
                else:
                    l += 1
            i += expiry + delay
        i += 1
    return w, l


def fetch_quotex(symbols, minutes):
    from quotex_data import QuotexFeed, candles_to_df
    qx = QuotexFeed(config.QUOTEX_EMAIL, config.QUOTEX_PASSWORD, host=config.QUOTEX_HOST)
    qx.connect()
    out = {}
    for s in symbols:
        print(f"Downloading {s} ({minutes} candles)...", flush=True)

        async def get(sym=s):
            async with qx.lock:
                return await qx.client.get_historical_candles(sym, minutes * 60, 60, max_workers=3)
        try:
            df = candles_to_df(qx._run(get(), timeout=300))
            out[s] = df
            print(f"  {len(df)} candles")
        except Exception as e:
            print("  failed:", e)
    return out


def fetch_forex(symbols, n):
    from data import fetch_history
    return {s: fetch_history(s, n) for s in symbols}


def main():
    args = [a for a in sys.argv[1:]]
    n = next((int(a) for a in args if a.isdigit()), 1000)
    args = [a for a in args if not a.isdigit()]
    base = [s.replace("_otc", "").replace("_OTC", "") for s in config.SYMBOLS]
    if config.DATA_SOURCE == "quotex":
        if args and args[0].lower() == "live":
            syms = base
        elif args:
            syms = args
        else:
            syms = [s + "_otc" for s in base]
        data = fetch_quotex(syms, n)
    else:
        syms = args or config.SYMBOLS
        data = fetch_forex(syms, n)

    totals = {t[0]: [0, 0] for t in TESTS}
    print()
    for sym, df in data.items():
        if len(df) < 300:
            print(f"{sym}: not enough candles ({len(df)})")
            continue
        line = [f"{sym:12s}"]
        for name, fn, ms, force in TESTS:
            w, l = run(df.reset_index(drop=True), fn, ms, force)
            totals[name][0] += w
            totals[name][1] += l
            acc = 100 * w / (w + l) if w + l else 0
            line.append(f"{acc:5.1f}% ({w + l:3d})")
        print(" | ".join(line), flush=True)

    print("\n================ RESULT (all pairs) ================")
    print(f"{'strategy':26s} {'trades':>7s} {'win':>5s} {'loss':>5s} {'accuracy':>9s}")
    for name, (w, l) in totals.items():
        acc = 100 * w / (w + l) if w + l else 0
        print(f"{name:26s} {w + l:7d} {w:5d} {l:5d} {acc:8.1f}%")
    print("\nNote: above ~55-58% over 200+ trades is good for 1-minute trades.")
    print("Fewer trades with higher accuracy is usually better than many trades.")


if __name__ == "__main__":
    t = time.time()
    main()
    print(f"\n(done in {time.time() - t:.0f}s)")
