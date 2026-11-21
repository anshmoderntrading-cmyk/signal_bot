"""
Market data:
  * Crypto (symbols ending in USDT, e.g. BTCUSDT) -> Binance public API (no key)
  * Forex (EURUSD, GBPUSD, USDJPY, XAUUSD ...)    -> Yahoo Finance (no key, default)
                                                   or Twelve Data (TWELVEDATA_API_KEY set)
All functions return the same DataFrame format:
  open_time, open, high, low, close, volume, close_time (ms)
"""
import os
import time
import requests
import pandas as pd

BINANCE_HOSTS = ["https://api.binance.com", "https://data-api.binance.vision", "https://api1.binance.com"]
HOSTS = BINANCE_HOSTS  # backward compatibility
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY", "")
UA = {"User-Agent": "Mozilla/5.0"}
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time"]


def is_crypto(symbol: str) -> bool:
    return symbol.upper().endswith(("USDT", "BUSD", "USDC", "BTC"))


# ---------------- Binance (crypto) ----------------
def _binance(symbol, limit=300, end_time=None):
    params = {"symbol": symbol, "interval": "1m", "limit": min(limit, 1000)}
    if end_time:
        params["endTime"] = end_time
    last_err = None
    for host in BINANCE_HOSTS:
        try:
            r = requests.get(f"{host}/api/v3/klines", params=params, timeout=10)
            r.raise_for_status()
            df = pd.DataFrame(r.json(), columns=COLS + ["q", "t", "b1", "b2", "ig"])[COLS]
            for c in ("open", "high", "low", "close", "volume"):
                df[c] = df[c].astype(float)
            df["close_time"] = df["close_time"].astype("int64")
            df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
            return df
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Binance fetch failed for {symbol}: {last_err}")


# ---------------- Yahoo Finance (forex) ----------------
def _yahoo_symbol(symbol):
    s = symbol.upper().replace("/", "")
    if s in ("XAUUSD", "GOLD"):
        return "GC=F"
    return f"{s}=X"


def _parse_yahoo(js):
    res = js["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({"ts": res["timestamp"], "open": q["open"], "high": q["high"],
                       "low": q["low"], "close": q["close"], "volume": q.get("volume")})
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0).astype(float)
    df["ts"] = (df["ts"] // 60) * 60  # align to minute
    df = df.drop_duplicates("ts", keep="last")
    ms = df["ts"].astype("int64") * 1000
    df["open_time"] = pd.to_datetime(ms, unit="ms", utc=True)
    df["close_time"] = ms + 59_999
    return df[COLS].reset_index(drop=True)


def _yahoo(symbol, limit=300, rng="1d"):
    last_err = None
    for host in ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"):
        try:
            r = requests.get(f"{host}/v8/finance/chart/{_yahoo_symbol(symbol)}",
                             params={"interval": "1m", "range": rng}, headers=UA, timeout=10)
            r.raise_for_status()
            return _parse_yahoo(r.json()).iloc[-limit:]
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Yahoo fetch failed for {symbol}: {last_err}")


# ---------------- Twelve Data (forex, needs free API key) ----------------
def _twelve_symbol(symbol):
    s = symbol.upper().replace("/", "")
    return f"{s[:3]}/{s[3:]}"


def _parse_twelve(js):
    if js.get("status") == "error":
        raise RuntimeError(js.get("message"))
    df = pd.DataFrame(js["values"])[::-1]
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].astype(float)
    df["volume"] = df["volume"].astype(float) if "volume" in df else 0.0
    t = pd.to_datetime(df["datetime"], utc=True)
    df["open_time"] = t
    ms = (t - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)
    df["close_time"] = ms.astype("int64") + 59_999
    return df[COLS].reset_index(drop=True)


def _twelve(symbol, limit=300):
    r = requests.get("https://api.twelvedata.com/time_series",
                     params={"symbol": _twelve_symbol(symbol), "interval": "1min",
                             "outputsize": min(limit, 5000), "timezone": "UTC", "apikey": TWELVE_KEY},
                     timeout=15)
    r.raise_for_status()
    return _parse_twelve(r.json())


# ---------------- public API ----------------
def get_klines(symbol: str, interval: str = "1m", limit: int = 300) -> pd.DataFrame:
    if is_crypto(symbol):
        return _binance(symbol, limit)
    if TWELVE_KEY:
        return _twelve(symbol, limit)
    return _yahoo(symbol, limit)


def closed_candles(df: pd.DataFrame, now_ms: int) -> pd.DataFrame:
    """Keep closed candles only."""
    return df[df["close_time"] < now_ms]


def is_fresh(df: pd.DataFrame, now_ms: int, max_age_min: int = 3) -> bool:
    """False when the market is closed (weekend) or data is stale."""
    return len(df) > 0 and now_ms - int(df["close_time"].iloc[-1]) < max_age_min * 60_000


def fetch_history(symbol: str, total: int = 3000) -> pd.DataFrame:
    """Past candles for the backtest."""
    if not is_crypto(symbol):
        if TWELVE_KEY:
            return _twelve(symbol, min(total, 5000))
        return _yahoo(symbol, total, rng="7d")  # Yahoo: 1m data max 7 days
    frames, end = [], None
    while sum(len(f) for f in frames) < total:
        df = _binance(symbol, 1000, end)
        if df.empty:
            break
        frames.insert(0, df)
        end = int(df["close_time"].iloc[0]) - 60_000  # before the first candle's open
        time.sleep(0.2)
    out = pd.concat(frames).drop_duplicates("open_time").reset_index(drop=True)
    return out.iloc[-total:]
