"""
Quotex OTC candles via the UNOFFICIAL pyquotex library.
  pip install git+https://github.com/cleitonleonel/pyquotex.git
Login: QUOTEX_EMAIL / QUOTEX_PASSWORD (.env). The first login may ask for an OTP/email code in the terminal.
WARNING: unofficial. It can break whenever Quotex changes; using it may violate Quotex's terms.
"""
import asyncio
import threading
import time

import pandas as pd

def _patch_curl_cffi():
    """pyquotex calls response.reason_phrase (httpx name); curl_cffi only has .reason -> crash
    that hides the real error. Add the missing attribute so the real HTTP status is shown."""
    try:
        from curl_cffi.requests import Response
        if not hasattr(Response, "reason_phrase"):
            Response.reason_phrase = property(
                lambda r: f"HTTP {r.status_code} {getattr(r, 'reason', '')}".strip())
    except Exception:
        pass


# real (fiat) currency codes - a pair is forex only if BOTH halves are in this list
FIAT = {
    "USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "CNY", "CNH", "HKD", "SGD", "INR", "BRL",
    "BDT", "PKR", "EGP", "NGN", "DZD", "ARS", "COP", "MXN", "IDR", "PHP", "TRY", "ZAR", "RUB", "THB",
    "MYR", "KRW", "SEK", "NOK", "DKK", "PLN", "HUF", "CZK", "ILS", "SAR", "AED", "QAR", "KWD", "MAD",
    "TND", "KES", "UAH", "VND", "CLP", "PEN", "LKR", "NPR", "IQD", "JOD", "BHD", "OMR", "RON", "BGN",
    "ISK", "TWD", "KZT", "GHS", "UGX", "TZS", "XOF", "XAF",
}


METALS = {"XAU", "XAG", "XPT", "XPD"}


def is_crypto_like(name):
    """6-letter XXXUSD style asset that is not forex and not a metal (ETCUSD, DASUSD, BTCUSD...)."""
    s = str(name).replace("_otc", "")
    return len(s) == 6 and s.isalpha() and s[:3] not in METALS and not is_forex(name)


def is_forex(name):
    s = str(name).replace("_otc", "")
    return len(s) == 6 and s[:3] in FIAT and s[3:] in FIAT

COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time"]


def candles_to_df(candles) -> pd.DataFrame:
    rows = []
    for c in candles or []:
        if isinstance(c, list) and len(c) >= 5:  # [time, open, close, high, low]
            c = {"time": c[0], "open": c[1], "close": c[2], "high": c[3], "low": c[4]}
        if isinstance(c, dict) and c.get("open") is not None:
            t = c.get("time", c.get("start_time"))
            if t is not None:
                rows.append({"time": t, "open": c["open"], "high": c["high"],
                             "low": c["low"], "close": c["close"]})
    if not rows:
        return pd.DataFrame(columns=COLS)
    df = pd.DataFrame(rows)
    df["time"] = (df["time"].astype("int64") // 60) * 60
    df = df.drop_duplicates("time", keep="last").sort_values("time")
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].astype(float)
    df["volume"] = 0.0
    ms = df["time"] * 1000
    df["open_time"] = pd.to_datetime(ms, unit="ms", utc=True)
    df["close_time"] = ms + 59_999
    return df[COLS].reset_index(drop=True)


class QuotexFeed:
    def __init__(self, email, password, client=None, otp_callback=None, host=None):
        self.email, self.password = email, password
        self.host = host or None
        self.otp_callback = otp_callback  # async fn(message) -> code (e.g. asked on Telegram)
        self.connected = False
        self.client = client
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.lock = None
        self.bad = {}    # asset -> time until which it is skipped (no data from Quotex)
        self.cache = {}  # asset -> DataFrame (full history fetched once, then only new candles)

    def _run(self, coro, timeout=60):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return fut.result(timeout)
        except BaseException:
            fut.cancel()  # a stuck request must not keep holding the lock and block every later call
            raise

    async def _connect(self):
        if self.lock is None:
            self.lock = asyncio.Lock()
        if self.client is None:
            _patch_curl_cffi()
            from pyquotex.stable_api import Quotex
            self.client = Quotex(email=self.email, password=self.password, lang="en",
                                 host=self.host, on_otp_callback=self.otp_callback)
            print(f"Quotex host: {getattr(self.client, 'host', '?')}")
        for attempt in range(2):
            ok, reason = await self.client.connect()
            if ok:
                print("Quotex connected")
                self.connected = True
                return True
            print(f"Quotex login failed ({reason}), retry {attempt + 1}/2")
            await asyncio.sleep(5 * (attempt + 1))
        raise RuntimeError("Quotex login failed. Check email/password or OTP.")

    def connect(self):
        return self._run(self._connect(), timeout=300)

    async def _candles(self, asset, limit):
        async with self.lock:
            if not await self.client.check_connect():
                await self._connect()
            cached = self.cache.get(asset)
            hist = []
            if limit > 30 and (cached is None or len(cached) < 60):  # history only the first time
                try:
                    hist = await asyncio.wait_for(
                        self.client.get_historical_candles(asset, limit * 60, 60, max_workers=1), 25) or []
                except Exception as e:
                    print("history error", asset, e)
            recent = []
            try:  # latest candles (fast, most up to date)
                recent = await asyncio.wait_for(self.client.get_candles(asset, time.time(), 3600, 60), 15) or []
            except Exception as e:
                print("recent candles error", asset, e)
            new = candles_to_df(list(hist) + list(recent))  # recent overrides same minute
            if cached is not None and len(cached):
                new = (pd.concat([cached, new]).drop_duplicates("close_time", keep="last")
                       .sort_values("close_time").reset_index(drop=True))
            new = new.iloc[-max(limit, 300):].reset_index(drop=True)
            if len(new):
                self.cache[asset] = new
            return new

    def connect_forever(self):
        """Keep trying to log in in the background (bot keeps running meanwhile)."""
        def worker():
            wait = 120
            while not self.connected:
                try:
                    self.connect()
                except Exception as e:
                    print("Quotex connect error:", e)
                    print(f"Next login try in {wait // 60} min (frequent retries keep the block longer)")
                    time.sleep(wait)
                    wait = min(wait * 2, 900)  # 2, 4, 8, 15 min
        threading.Thread(target=worker, daemon=True).start()

    def get_klines(self, asset, interval="1m", limit=300):
        if not self.connected:
            raise RuntimeError("Quotex not connected yet")
        if self.bad.get(asset, 0) > time.time():
            raise RuntimeError("skipped for a few minutes (Quotex sent no data)")
        try:
            df = self._run(self._candles(asset, limit), timeout=60).iloc[-limit:]
        except Exception:
            self.bad[asset] = time.time() + 600
            raise
        if limit > 30 and len(df) < 60:
            self.bad[asset] = time.time() + 600   # no usable history -> don't waste time on it for 10 min
        return df

    async def _is_open(self, asset):
        async with self.lock:
            _, info = await self.client.check_asset_open(asset)
            return bool(info[2])

    async def _payout(self, asset):
        async with self.lock:
            await self.client.get_instruments()
            p = self.client.get_payout_by_asset(asset, "1")  # 1-minute payout %
            if p in (None, "", 0):
                for i in (self.client.api.instruments or []):
                    if i[1] == asset:
                        p = i[5]
                        break
            try:
                p = float(p)
            except (TypeError, ValueError):
                return None
            return p * 100 if 0 < p <= 1 else p

    def payout(self, asset):
        """Current payout % for 1-minute trades, or None if unknown."""
        try:
            return self._run(self._payout(asset), timeout=30)
        except Exception as e:
            print("payout error", asset, e)
            return None

    async def _tradable(self, otc, min_payout, crypto=False):
        import re
        async with self.lock:
            inst = await self.client.get_instruments() or []
            out = []
            for i in inst:
                try:
                    name, is_open = i[1], bool(i[14])
                except Exception:
                    continue
                if not re.fullmatch(r"[A-Z]{6}(_otc)?", str(name)):
                    continue
                if not (is_forex(name) or (crypto and is_crypto_like(name))):
                    continue  # currency pairs (+ crypto if enabled); never metals / stocks
                if name.endswith("_otc") != otc or not is_open:
                    continue
                p = self.client.get_payout_by_asset(name, "1")
                if p in (None, "", 0):
                    p = i[5]
                try:
                    p = float(p)
                except (TypeError, ValueError):
                    continue
                p = p * 100 if 0 < p <= 1 else p
                if p >= min_payout:
                    out.append((name, p))
            out.sort(key=lambda x: -x[1])
            return out

    def tradable_pairs(self, otc=True, min_payout=85, limit=15, crypto=False):
        """All open currency pairs (+ crypto if enabled) with payout >= min_payout, best payout first."""
        try:
            return self._run(self._tradable(otc, min_payout, crypto), timeout=60)[:limit]
        except Exception as e:
            print("pair list error:", e)
            return []

    def is_open(self, asset):
        try:
            return self._run(self._is_open(asset), timeout=30)
        except Exception as e:
            print("asset check error", asset, e)
            return True  # unknown -> let the fresh-data check decide
