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


COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time"]


def candles_to_df(candles) -> pd.DataFrame:
    rows = [c for c in (candles or []) if isinstance(c, dict) and c.get("open") is not None]
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
    def __init__(self, email, password, client=None, otp_callback=None):
        self.email, self.password = email, password
        self.otp_callback = otp_callback  # async fn(message) -> code (e.g. asked on Telegram)
        self.connected = False
        self.client = client
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.lock = None

    def _run(self, coro, timeout=60):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    async def _connect(self):
        if self.lock is None:
            self.lock = asyncio.Lock()
        if self.client is None:
            _patch_curl_cffi()
            from pyquotex.stable_api import Quotex
            self.client = Quotex(email=self.email, password=self.password, lang="en",
                                 on_otp_callback=self.otp_callback)
        for attempt in range(5):
            ok, reason = await self.client.connect()
            if ok:
                print("Quotex connected")
                self.connected = True
                return True
            print(f"Quotex login failed ({reason}), retry {attempt + 1}/5")
            await asyncio.sleep(5 * (attempt + 1))
        raise RuntimeError("Quotex login failed. Check email/password or OTP.")

    def connect(self):
        return self._run(self._connect(), timeout=300)

    async def _candles(self, asset, limit):
        async with self.lock:
            if not await self.client.check_connect():
                await self._connect()
            data = await self.client.get_candles(asset, time.time(), limit * 60, 60)
            return candles_to_df(data)

    def connect_forever(self):
        """Keep trying to log in in the background (bot keeps running meanwhile)."""
        def worker():
            while not self.connected:
                try:
                    self.connect()
                except Exception as e:
                    print("Quotex connect error:", e)
                    time.sleep(60)
        threading.Thread(target=worker, daemon=True).start()

    def get_klines(self, asset, interval="1m", limit=300):
        if not self.connected:
            raise RuntimeError("Quotex not connected yet")
        return self._run(self._candles(asset, limit)).iloc[-limit:]

    async def _is_open(self, asset):
        async with self.lock:
            _, info = await self.client.check_asset_open(asset)
            return bool(info[2])

    def is_open(self, asset):
        try:
            return self._run(self._is_open(asset), timeout=30)
        except Exception as e:
            print("asset check error", asset, e)
            return True  # unknown -> let the fresh-data check decide
