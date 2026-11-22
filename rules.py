"""
Candidate trading rules for the data-driven strategy search (research.py) and the live bot (STRATEGY=auto).
Every rule returns an array of +1 (CALL), -1 (PUT) or 0 (no trade) for each closed candle.
The SAME code is used for research and live signals, so live behaviour matches the test.
"""
import numpy as np
import pandas as pd


def _rsi(close, n):
    d = np.diff(close, prepend=close[0])
    up = pd.Series(np.clip(d, 0, None)).ewm(alpha=1 / n, adjust=False).mean().values
    dn = pd.Series(np.clip(-d, 0, None)).ewm(alpha=1 / n, adjust=False).mean().values
    rs = np.divide(up, dn, out=np.full_like(up, np.inf), where=dn > 0)
    return 100 - 100 / (1 + rs)


def _features(df):
    o, h, l, c = (df[k].values.astype(float) for k in ("open", "high", "low", "close"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().values
    s = pd.Series(c)
    mid, sd = s.rolling(20).mean().values, s.rolling(20).std().values
    color = np.sign(c - o)  # +1 green, -1 red, 0 doji
    body = abs(c - o)
    uw = h - np.maximum(o, c)
    lw = np.minimum(o, c) - l
    return dict(o=o, h=h, l=l, c=c, atr=atr, mid=mid, sd=sd, color=color, body=body, uw=uw, lw=lw,
                rsi7=_rsi(c, 7), rsi14=_rsi(c, 14),
                ema9=s.ewm(span=9, adjust=False).mean().values,
                ema21=s.ewm(span=21, adjust=False).mean().values)


def _streak(color, n):
    """+1 where the last n candles are all green, -1 where all red."""
    out = np.zeros(len(color))
    for i in range(n - 1, len(color)):
        w = color[i - n + 1:i + 1]
        if np.all(w > 0):
            out[i] = 1
        elif np.all(w < 0):
            out[i] = -1
    return out


def all_rules(df):
    """name -> signal array (+1 CALL / -1 PUT / 0)."""
    f = _features(df)
    c, atr = f["c"], f["atr"]
    R = {}
    for n in (2, 3, 4, 5):
        st = _streak(f["color"], n)
        R[f"streak{n}_reverse"] = -st
        R[f"streak{n}_follow"] = st
    for per in (7, 14):
        r = f[f"rsi{per}"]
        for lo, hi in ((20, 80), (25, 75), (30, 70)):
            R[f"rsi{per}_{lo}_{hi}_reverse"] = np.where(r < lo, 1, np.where(r > hi, -1, 0))
    for k in (2.0, 2.5):
        up, dn = f["mid"] + k * f["sd"], f["mid"] - k * f["sd"]
        R[f"bb{k}_reverse"] = np.where(c > up, -1, np.where(c < dn, 1, 0))
        R[f"bb{k}_follow"] = -R[f"bb{k}_reverse"]
    for k in (1.0, 1.5):
        big = f["body"] > k * atr
        R[f"bigcandle{k}_reverse"] = np.where(big, -f["color"], 0)
        R[f"bigcandle{k}_follow"] = np.where(big, f["color"], 0)
    wick = 0.6 * (f["h"] - f["l"])
    R["wick_reverse"] = np.where(f["uw"] > wick, -1, np.where(f["lw"] > wick, 1, 0))
    R["ema_trend_follow"] = np.where((f["ema9"] > f["ema21"]) & (f["color"] > 0), 1,
                                     np.where((f["ema9"] < f["ema21"]) & (f["color"] < 0), -1, 0))
    R["ema_trend_pullback"] = np.where((f["ema9"] > f["ema21"]) & (f["color"] < 0), 1,
                                       np.where((f["ema9"] < f["ema21"]) & (f["color"] > 0), -1, 0))
    for name in R:  # no signals while indicators warm up
        R[name] = np.asarray(R[name], dtype=float)
        R[name][:30] = 0
    return R


def signal_now(df, rule_name):
    """Live: signal of one rule on the last closed candle (+1/-1/0)."""
    if len(df) < 60:
        return 0
    return int(all_rules(df.tail(200).reset_index(drop=True))[rule_name][-1])
