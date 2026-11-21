"""
Forex Signal Bot: only 2 buttons (Signal ON / Signal STOP).
While ON, a signal arrives automatically every SIGNAL_EVERY_MINUTES minutes:

  AUD/JPY LIVE 🟢 BUY
  ⏱️ 1 Min
  🕒 03:24 PM – 03:25 PM
"""
import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

import config
from data import get_klines, closed_candles, is_fresh
from strategy import analyze

QX = None
OTP = {"waiting": False, "code": None}


async def ask_otp_on_telegram(message):
    """Quotex sent a login code to your email: ask for it on Telegram and wait."""
    import asyncio
    OTP.update(waiting=True, code=None)
    targets = [config.ADMIN_CHAT_ID] if config.ADMIN_CHAT_ID else list(state["subscribers"])
    print("Quotex OTP needed. Waiting for the code on Telegram... (send /start to the bot if no one is subscribed)")
    asked = set()
    for _ in range(600):  # up to 10 minutes
        for cid in (targets or list(state["subscribers"])):
            if cid not in asked:
                send(cid, "🔐 Quotex sent a login code to your email.\nType that code here (numbers only).")
                asked.add(cid)
        if OTP["code"]:
            OTP["waiting"] = False
            return OTP["code"]
        await asyncio.sleep(1)
    OTP["waiting"] = False
    return ""


if config.DATA_SOURCE == "quotex" and not (config.QUOTEX_EMAIL and config.QUOTEX_PASSWORD):
    print("WARNING: DATA_SOURCE=quotex but QUOTEX_EMAIL/QUOTEX_PASSWORD are not set -> using real forex.")
    config.SYMBOLS = [s.replace("_otc", "") for s in config.SYMBOLS]
elif config.DATA_SOURCE == "quotex":
    from quotex_data import QuotexFeed
    QX = QuotexFeed(config.QUOTEX_EMAIL, config.QUOTEX_PASSWORD, otp_callback=ask_otp_on_telegram,
                    host=config.QUOTEX_HOST)
    get_klines = QX.get_klines  # noqa: F811  (OTC candles from Quotex)

API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
IST = timezone(timedelta(hours=5, minutes=30))
BTN_ON, BTN_STOP = "🟢 Signal ON", "🔴 Signal STOP"
KEYBOARD = {"keyboard": [[{"text": BTN_ON}, {"text": BTN_STOP}]], "resize_keyboard": True}
lock = threading.Lock()


# ---------------- storage ----------------
def load():
    if os.path.exists(config.STATS_FILE):
        try:
            with open(config.STATS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"subscribers": [], "win": 0, "loss": 0, "draw": 0}


def save():
    with open(config.STATS_FILE, "w") as f:
        json.dump(state, f)


state = load()


# ---------------- telegram ----------------
def send(chat_id, text, reply_to=None, keyboard=False):
    payload = {"chat_id": chat_id, "text": text}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    if keyboard:
        payload["reply_markup"] = KEYBOARD
    try:
        r = requests.post(f"{API}/sendMessage", json=payload, timeout=10).json()
        return r.get("result", {}).get("message_id")
    except Exception as e:
        print("send error:", e)


def handle(msg):
    cid = msg["chat"]["id"]
    txt = (msg.get("text") or "").strip()
    allowed = (cid == config.ADMIN_CHAT_ID) if config.ADMIN_CHAT_ID else (cid in state["subscribers"])
    if OTP["waiting"] and txt.isdigit() and allowed:
        OTP["code"] = txt
        send(cid, "✅ Code received, logging in to Quotex...")
        return
    with lock:
        if txt == BTN_ON or txt.lower().startswith(("/start", "/on")):
            if cid not in state["subscribers"]:
                state["subscribers"].append(cid); save()
            note = "" if market_open() else "\n⚠️ The forex market is closed right now (weekend). Signals will start when it opens."
            send(cid, f"✅ Signal ON\nA signal every {config.SIGNAL_EVERY_MINUTES} min.{note}", keyboard=True)
        elif txt == BTN_STOP or txt.lower().startswith(("/stop", "/off")):
            if cid in state["subscribers"]:
                state["subscribers"].remove(cid); save()
            send(cid, "⛔ Signal STOP", keyboard=True)
        else:
            send(cid, "Use the button 👇", keyboard=True)


def poll_updates():
    offset = None
    while True:
        try:
            r = requests.get(f"{API}/getUpdates", params={"timeout": 30, "offset": offset}, timeout=40).json()
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                if "message" in u:
                    handle(u["message"])
        except Exception as e:
            print("poll error:", e); time.sleep(5)


# ---------------- signals ----------------
def market_open(now=None):
    """Forex: open Sun 22:00 UTC – Fri 22:00 UTC. Quotex OTC: always open."""
    if QX is not None:
        return True
    now = now or datetime.now(timezone.utc)
    wd, h = now.weekday(), now.hour
    if wd == 5:
        return False
    if wd == 4 and h >= 22:
        return False
    if wd == 6 and h < 22:
        return False
    return True


def pair_name(sym):
    base = sym.split("_")[0]
    otc = " OTC" if sym.lower().endswith("_otc") else ""
    return f"{base[:3]}/{base[3:]}{otc}"


def fmt_signal(sym, direction, start, end):
    side = "🟢 BUY" if direction == "CALL" else "🔴 SELL"
    t = lambda d: d.astimezone(IST).strftime("%I:%M %p")
    return (f"{pair_name(sym)} LIVE {side}\n"
            f"⏱️ {config.EXPIRY_MINUTES} Min\n"
            f"🕒 {t(start)} – {t(end)}")


def best_signal(now_ms):
    """Scan all pairs and pick the strongest setup."""
    best = None
    for sym in config.SYMBOLS:
        try:
            df = closed_candles(get_klines(sym, config.INTERVAL, 300), now_ms)
            if not is_fresh(df, now_ms):
                continue
            if QX is not None and not QX.is_open(sym):
                continue
            sig = analyze(df, config.MIN_SCORE, force=True)
            if not sig:
                continue
            key = (sig["score"], sig["edge"])
            if best is None or key > best[0]:
                best = (key, sym, sig, int(df["close_time"].iloc[-1]))
        except Exception as e:
            print("scan error", sym, e)
    return best


def check_result(sym, sig, entry_close_ms, msg_ids):
    target = entry_close_ms + config.EXPIRY_MINUTES * 60_000
    time.sleep(max(0, (target - time.time() * 1000) / 1000) + 3)
    exit_price = None
    for _ in range(12):
        try:
            df = get_klines(sym, config.INTERVAL, 10)
            row = df[df["close_time"] == target]
            if len(row):
                exit_price = float(row["close"].iloc[0]); break
        except Exception as e:
            print("result error:", e)
        time.sleep(5)
    if exit_price is None:
        return
    entry = sig["price"]
    if exit_price == entry:
        res = "draw"
    elif (exit_price > entry) == (sig["direction"] == "CALL"):
        res = "win"
    else:
        res = "loss"
    with lock:
        state[res] += 1; save()
    if config.SEND_RESULTS:
        text = {"win": "✅ WIN", "loss": "❌ LOSS", "draw": "➖ DRAW"}[res]
        for cid, mid in msg_ids.items():
            send(cid, text, reply_to=mid)


def scanner_loop():
    while True:
        time.sleep(60 - (time.time() % 60) + 1)   # 1 second after each candle closes
        minute = int(time.time() // 60)
        if minute % config.SIGNAL_EVERY_MINUTES:
            continue
        if not state["subscribers"] or not market_open():
            continue
        now_ms = int(time.time() * 1000)
        best = best_signal(now_ms)
        if not best:
            continue
        _, sym, sig, entry_close_ms = best
        start = datetime.fromtimestamp((entry_close_ms + 1) / 1000, timezone.utc)
        end = start + timedelta(minutes=config.EXPIRY_MINUTES)
        text = fmt_signal(sym, sig["direction"], start, end)
        msg_ids = {}
        for cid in list(state["subscribers"]):
            mid = send(cid, text)
            if mid:
                msg_ids[cid] = mid
        threading.Thread(target=check_result, args=(sym, sig, entry_close_ms, msg_ids), daemon=True).start()


# ---------------- keep-alive web server (Render free) ----------------
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        w, l = state["win"], state["loss"]
        acc = 100 * w / (w + l) if w + l else 0
        body = f"OK | subscribers: {len(state['subscribers'])} | W {w} / L {l} | {acc:.1f}%".encode()
        self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200); self.end_headers()

    def log_message(self, *a):
        pass


def start_web():
    port = int(os.getenv("PORT", "0") or 0)
    if port:
        threading.Thread(target=HTTPServer(("0.0.0.0", port), Health).serve_forever, daemon=True).start()
        print(f"Health server on port {port}")


if __name__ == "__main__":
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN first (token from @BotFather).")
    print("Bot running...")
    start_web()
    if QX is not None:
        print("Logging in to Quotex... (if a code arrives by email, send it to the bot on Telegram)")
        QX.connect_forever()
    threading.Thread(target=scanner_loop, daemon=True).start()
    poll_updates()
