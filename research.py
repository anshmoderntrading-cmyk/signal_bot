"""
Data-driven strategy search with an honest train/test split.

    python research.py            -> OTC pairs, last ~2 days (3000 candles each)
    python research.py live       -> live (non-OTC) pairs   (Mon-Fri)
    python research.py 5000       -> more candles

For every rule (rules.py) x expiry (1,2,3,5 min):
  * the first 60% of the data = TRAIN, the last 40% = TEST (data the rule was not chosen on)
  * a rule PASSES only if it is good on BOTH parts
Passed rules are saved to best_rules.json; the bot uses them when STRATEGY=auto.
Entry timing matches the live bot: signal on candle i, trade starts one minute later.
"""
import json
import sys
import time

import numpy as np
from statistics import NormalDist

import config
from rules import all_rules

EXPIRIES = (1, 2, 3, 5)
DELAY = 1            # live bot: the trade starts on the next minute after the signal
TRAIN_FRAC = 0.6
# pass rules (all pairs together)
G_MIN_ACC, G_MIN_TRAIN, G_MIN_TEST = 55.0, 200, 120
# pass rules (one pair only) - stricter, small samples are noisy
P_MIN_ACC, P_MIN_TRAIN, P_MIN_TEST = 57.0, 60, 40


def evaluate(sig, close, expiry, lo, hi):
    """wins, trades for signals at indices [lo, hi)."""
    n = len(close)
    hi = min(hi, n - DELAY - expiry)
    if hi <= lo:
        return 0, 0
    s = sig[lo:hi]
    ret = close[lo + DELAY + expiry:hi + DELAY + expiry] - close[lo + DELAY:hi + DELAY]
    m = (s != 0) & (ret != 0)
    wins = int(np.sum(np.sign(ret[m]) == s[m]))
    return wins, int(np.sum(m))


def pct(w, t):
    return 100.0 * w / t if t else 0.0


def zscore(w, t, expiry):
    """How far above a coin flip (50%) the result is, in standard deviations.
    Trades with expiry > 1 min overlap, so the effective sample is t / expiry."""
    n = t / max(expiry, 1)
    if n <= 0:
        return 0.0
    return (pct(w, t) / 100 - 0.5) / (0.25 / n) ** 0.5


def z_needed(num_tests, alpha=0.05):
    """Bonferroni: with many rules tested, a few look good by luck; demand stronger evidence."""
    return NormalDist().inv_cdf(1 - alpha / max(num_tests, 1))


def main():
    args = sys.argv[1:]
    n = next((int(a) for a in args if a.isdigit()), 3000)
    live = any(a.lower() == "live" for a in args)
    base = [s.replace("_otc", "").replace("_OTC", "") for s in config.SYMBOLS]
    if config.DATA_SOURCE == "quotex":
        from backtest import fetch_quotex
        syms = base if live else [s + "_otc" for s in base]
        data = fetch_quotex(syms, n)
    else:
        from backtest import fetch_forex
        data = fetch_forex(config.SYMBOLS, n)

    pooled = {}   # (rule, expiry) -> [train_w, train_t, test_w, test_t]
    per_pair = []  # (sym, rule, expiry, trw, trt, tew, tet)
    for sym, df in data.items():
        df = df.reset_index(drop=True)
        if len(df) < 500:
            print(f"{sym}: not enough candles ({len(df)}), skipped")
            continue
        close = df["close"].values.astype(float)
        split = int(len(df) * TRAIN_FRAC)
        sigs = all_rules(df)
        for rule, sig in sigs.items():
            for e in EXPIRIES:
                trw, trt = evaluate(sig, close, e, 0, split)
                tew, tet = evaluate(sig, close, e, split, len(df))
                p = pooled.setdefault((rule, e), [0, 0, 0, 0])
                p[0] += trw; p[1] += trt; p[2] += tew; p[3] += tet
                per_pair.append((sym, rule, e, trw, trt, tew, tet))

    rows = sorted(pooled.items(), key=lambda kv: pct(kv[1][2], kv[1][3]), reverse=True)
    print("\n========== TOP 15 RULES (all pairs together) ==========")
    print(f"{'rule':28s} {'exp':>3s} {'train%':>7s} {'(n)':>6s} {'TEST%':>7s} {'(n)':>6s} {'z':>5s}")
    for (rule, e), (trw, trt, tew, tet) in rows[:15]:
        print(f"{rule:28s} {e:>3d} {pct(trw, trt):7.1f} {trt:6d} {pct(tew, tet):7.1f} {tet:6d} "
              f"{zscore(tew, tet, e):5.1f}")

    n_global = len(pooled)
    n_pair = len(per_pair)
    zg, zp = z_needed(n_global), z_needed(n_pair)
    z_train = NormalDist().inv_cdf(0.95)
    print(f"\n(tested {n_global} rule/expiry combos on all pairs and {n_pair} per pair; "
          f"to beat luck the TEST result needs z >= {zg:.2f} (all pairs) / {zp:.2f} (one pair))")
    chosen = []
    for (rule, e), (trw, trt, tew, tet) in rows:
        if (trt >= G_MIN_TRAIN and tet >= G_MIN_TEST and pct(trw, trt) >= G_MIN_ACC
                and pct(tew, tet) >= G_MIN_ACC and zscore(trw, trt, e) >= z_train
                and zscore(tew, tet, e) >= zg):
            chosen.append({"rule": rule, "expiry": e, "pairs": "ALL",
                           "train_acc": round(pct(trw, trt), 1), "test_acc": round(pct(tew, tet), 1),
                           "test_trades": tet, "z": round(zscore(tew, tet, e), 2)})
    for sym, rule, e, trw, trt, tew, tet in per_pair:
        if (trt >= P_MIN_TRAIN and tet >= P_MIN_TEST and pct(trw, trt) >= P_MIN_ACC
                and pct(tew, tet) >= P_MIN_ACC and zscore(trw, trt, e) >= z_train
                and zscore(tew, tet, e) >= zp):
            chosen.append({"rule": rule, "expiry": e, "pairs": [sym],
                           "train_acc": round(pct(trw, trt), 1), "test_acc": round(pct(tew, tet), 1),
                           "test_trades": tet, "z": round(zscore(tew, tet, e), 2)})
    chosen.sort(key=lambda r: r["test_acc"], reverse=True)

    print("\n========== PASSED (good on BOTH train and test) ==========")
    if not chosen:
        print("NONE. No rule beat a coin flip reliably on unseen data (after allowing for luck).")
        print("=> On this data the market behaves like a coin flip for these rules.")
    for r in chosen[:20]:
        who = "ALL pairs" if r["pairs"] == "ALL" else r["pairs"][0]
        print(f"{r['rule']:28s} {r['expiry']} min  {who:12s} train {r['train_acc']}%  "
              f"TEST {r['test_acc']}% ({r['test_trades']} trades, z={r['z']})")

    out = {"generated": time.strftime("%Y-%m-%d %H:%M"), "mode": "live" if live else "otc",
           "candles": n, "rules": chosen}
    with open("best_rules.json", "w") as f:
        json.dump(out, f, indent=1)
    print(f"\nSaved {len(chosen)} rule(s) to best_rules.json")
    if chosen:
        print("Bot will use them with STRATEGY=auto (see README).")


if __name__ == "__main__":
    t = time.time()
    main()
    print(f"(done in {time.time() - t:.0f}s)")
