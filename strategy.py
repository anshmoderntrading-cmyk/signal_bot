"""
Strategy: Support/Resistance + confluence of indicators.

Every condition adds +1 point to CALL (UP) or PUT (DOWN).
A signal is only issued if one side reaches MIN_SCORE and beats the other side by 2+.

Conditions:
 1. Price near support (CALL) / near resistance (PUT)       -> +2 (main condition)
 2. RSI(14) oversold <35 (CALL) / overbought >65 (PUT)
 3. Price touched/closed outside lower/upper Bollinger Band (20,2)
 4. Rejection candle: long lower wick (CALL) / long upper wick (PUT)
 5. EMA trend: EMA9 > EMA21 (CALL) / EMA9 < EMA21 (PUT)
 6. Stochastic(14,3) crossing up from <20 (CALL) / down from >80 (PUT)
 7. Volume above 20-candle average (confirmation)
You can change the weights / thresholds here to build your own strategy.
"""
import numpy as np
import pandas as pd


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema9"] = ema(df["close"], 9)
    df["ema21"] = ema(df["close"], 21)
    df["rsi"] = rsi(df["close"])
    df["atr"] = atr(df)
    mid = df["close"].rolling(20).mean()
    sd = df["close"].rolling(20).std()
    df["bb_up"], df["bb_low"] = mid + 2 * sd, mid - 2 * sd
    ll, hh = df["low"].rolling(14).min(), df["high"].rolling(14).max()
    df["stoch_k"] = (100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)).rolling(3).mean()
    df["stoch_d"] = df["stoch_k"].rolling(3).mean()
    df["vol_ma"] = df["volume"].rolling(20).mean()
    return df


def support_resistance(df: pd.DataFrame, lookback=120, left=3, right=3, tol_atr=0.5):
    """Find swing highs/lows (pivots) and cluster nearby levels together."""
    d = df.iloc[-lookback:]
    highs, lows = d["high"].values, d["low"].values
    piv_h, piv_l = [], []
    for i in range(left, len(d) - right):
        if highs[i] == highs[i - left:i + right + 1].max():
            piv_h.append(highs[i])
        if lows[i] == lows[i - left:i + right + 1].min():
            piv_l.append(lows[i])
    tol = df["atr"].iloc[-1] * tol_atr

    def cluster(levels):
        levels = sorted(levels)
        out = []
        for lv in levels:
            if out and abs(lv - out[-1][0]) <= tol:
                n = out[-1][1] + 1
                out[-1] = ((out[-1][0] * out[-1][1] + lv) / n, n)
            else:
                out.append((lv, 1))
        return out  # (level, touches)

    return cluster(piv_l), cluster(piv_h)


def analyze(df: pd.DataFrame, min_score: int = 4, force: bool = False):
    """df = CLOSED candles only. Returns signal dict or None."""
    if len(df) < 60:
        return None
    df = add_indicators(df)
    c, p = df.iloc[-1], df.iloc[-2]
    price, a = c["close"], c["atr"]
    if not a or np.isnan(a):
        return None
    supports, resistances = support_resistance(df)
    call, put, why_c, why_p = 0, 0, [], []

    # 1. Support / Resistance (levels with 2+ touches are stronger)
    near_s = [lv for lv, t in supports
              if t >= 2 and (0 <= price - lv <= 0.6 * a or c["low"] <= lv <= price)]
    near_r = [lv for lv, t in resistances
              if t >= 2 and (0 <= lv - price <= 0.6 * a or c["high"] >= lv >= price)]
    if near_s:
        call += 2; why_c.append(f"Near support {near_s[-1]:.4f}")
    if near_r:
        put += 2; why_p.append(f"Near resistance {near_r[0]:.4f}")

    # 2. RSI
    if c["rsi"] < 35:
        call += 1; why_c.append(f"RSI oversold {c['rsi']:.1f}")
    elif c["rsi"] > 65:
        put += 1; why_p.append(f"RSI overbought {c['rsi']:.1f}")

    # 3. Bollinger
    if c["low"] <= c["bb_low"]:
        call += 1; why_c.append("Lower Bollinger touched")
    if c["high"] >= c["bb_up"]:
        put += 1; why_p.append("Upper Bollinger touched")

    # 4. Rejection wick
    body = abs(c["close"] - c["open"]) or 1e-12
    lw = min(c["open"], c["close"]) - c["low"]
    uw = c["high"] - max(c["open"], c["close"])
    if lw > 1.5 * body and lw > uw:
        call += 1; why_c.append("Bullish rejection wick")
    if uw > 1.5 * body and uw > lw:
        put += 1; why_p.append("Bearish rejection wick")

    # 5. EMA trend
    if c["ema9"] > c["ema21"]:
        call += 1; why_c.append("EMA9 > EMA21 (uptrend)")
    else:
        put += 1; why_p.append("EMA9 < EMA21 (downtrend)")

    # 6. Stochastic cross
    if p["stoch_k"] < p["stoch_d"] and c["stoch_k"] > c["stoch_d"] and p["stoch_k"] < 20:
        call += 1; why_c.append("Stochastic bullish cross")
    if p["stoch_k"] > p["stoch_d"] and c["stoch_k"] < c["stoch_d"] and p["stoch_k"] > 80:
        put += 1; why_p.append("Stochastic bearish cross")

    # 7. Volume
    if c["volume"] > c["vol_ma"]:
        if call > put:
            call += 1; why_c.append("Volume above average")
        elif put > call:
            put += 1; why_p.append("Volume above average")

    max_score = 8
    if call >= min_score and call - put >= 2:
        return {"direction": "CALL", "score": call, "max": max_score, "reasons": why_c,
                "price": price, "rsi": c["rsi"], "edge": call - put}
    if put >= min_score and put - call >= 2:
        return {"direction": "PUT", "score": put, "max": max_score, "reasons": why_p,
                "price": price, "rsi": c["rsi"], "edge": put - call}
    if force and call != put:  # always give the stronger side (auto mode)
        d, sc, why = ("CALL", call, why_c) if call > put else ("PUT", put, why_p)
        return {"direction": d, "score": sc, "max": max_score, "reasons": why,
                "price": price, "rsi": c["rsi"], "edge": abs(call - put)}
    return None
