"""
Forex Signal Bot: only 2 buttons (Signal ON / Signal STOP).
While ON: one trade at a time -> signal, 1-min trade, result + chart, GAP_MINUTES pause, next signal:

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
from chart import trade_chart

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
state.setdefault("stickers", {"win": [], "loss": []})
pending_sticker = {}  # chat_id -> sticker file_id waiting for "win"/"loss"
recent_pairs = []  # last few signalled pairs, so every signal comes from a different market


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


def send_photo(chat_id, png, caption="", reply_to=None):
    data = {"chat_id": chat_id, "caption": caption}
    if reply_to:
        data["reply_to_message_id"] = reply_to
    try:
        r = requests.post(f"{API}/sendPhoto", data=data,
                          files={"photo": ("trade.png", png, "image/png")}, timeout=30).json()
        return r.get("ok", False)
    except Exception as e:
        print("photo error:", e)
        return False


def send_sticker(chat_id, file_id):
    try:
        requests.post(f"{API}/sendSticker", json={"chat_id": chat_id, "sticker": file_id}, timeout=10)
    except Exception as e:
        print("sticker error:", e)


def handle(msg):
    cid = msg["chat"]["id"]
    txt = (msg.get("text") or "").strip()
    allowed = (cid == config.ADMIN_CHAT_ID) if config.ADMIN_CHAT_ID else (cid in state["subscribers"])
    if OTP["waiting"] and txt.isdigit() and allowed:
        OTP["code"] = txt
        send(cid, "✅ Code received, logging in to Quotex...")
        return
    if "sticker" in msg:  # user sends a sticker -> ask whether it is for WIN or LOSS
        pending_sticker[cid] = msg["sticker"]["file_id"]
        send(cid, "🎨 Sticker received!\nIs this for a WIN or a LOSS? Type: win  or  loss", keyboard=True)
        return
    low = txt.lower()
    if cid in pending_sticker and low in ("win", "loss", "itm", "otm"):
        kind = "win" if low in ("win", "itm") else "loss"
        with lock:
            state["stickers"][kind].append(pending_sticker.pop(cid))
            save()
            n = len(state["stickers"][kind])
        send(cid, f"✅ Saved. {n} sticker(s) will now be sent after every {kind.upper()}.\n"
                  "Add more: send another sticker. Remove all: /clearstickers", keyboard=True)
        return
    if low.startswith("/clearstickers"):
        with lock:
            state["stickers"] = {"win": [], "loss": []}
            save()
        send(cid, "🗑️ All stickers removed.", keyboard=True)
        return
    with lock:
        if txt == BTN_ON or txt.lower().startswith(("/start", "/on")):
            if cid not in state["subscribers"]:
                state["subscribers"].append(cid); save()
            note = "" if market_open() else "\n⚠️ The forex market is closed right now (weekend). Signals will start when it opens."
            send(cid, f"✅ Signal ON\nOne trade at a time: result + chart, then the next signal after {config.GAP_MINUTES} min.{note}", keyboard=True)
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
    return (f"{pair_name(sym)} {side}\n"
            f"⏱️ {config.EXPIRY_MINUTES} Min\n"
            f"🕒 {t(start)} – {t(end)}")


def best_signal(now_ms):
    """Scan all pairs and pick the strongest setup."""
    best = None
    stats = {"ok": 0, "stale": 0, "closed": 0, "no_setup": 0, "error": 0, "few_candles": 0}
    for sym in config.SYMBOLS:
        try:
            df = closed_candles(get_klines(sym, config.INTERVAL, 300), now_ms)
            if len(df) < 60:
                stats["few_candles"] += 1
                continue
            if not is_fresh(df, now_ms):
                stats["stale"] += 1
                continue
            if QX is not None and not QX.is_open(sym):
                stats["closed"] += 1
                continue
            sig = analyze(df, config.MIN_SCORE, force=True)
            if not sig:
                stats["no_setup"] += 1
                continue
            stats["ok"] += 1
            fresh = sym not in recent_pairs  # prefer a market we haven't just used
            key = (fresh, sig["score"], sig["edge"])
            if best is None or key > best[0]:
                best = (key, sym, sig, int(df["close_time"].iloc[-1]))
        except Exception as e:
            stats["error"] += 1
            print("scan error", sym, e)
    pick = f" -> {best[1]} {best[2]['direction']}" if best else " -> no signal"
    print(time.strftime("%H:%M"), "scan:", stats, pick)
    return best


def check_result(sym, sig, start_ms, msg_ids):
    """Trade window [start, start+expiry]: entry = price at start, exit = price at end."""
    entry_close = start_ms - 1                       # candle that closes exactly at start
    exit_close = entry_close + config.EXPIRY_MINUTES * 60_000
    time.sleep(max(0, (exit_close - time.time() * 1000) / 1000) + 3)
    entry = exit_price = None
    df = None
    for _ in range(12):
        try:
            df = get_klines(sym, config.INTERVAL, 40)
            e = df[df["close_time"] == entry_close]
            x = df[df["close_time"] == exit_close]
            if len(e) and len(x):
                entry, exit_price = float(e["close"].iloc[0]), float(x["close"].iloc[0])
                break
        except Exception as ex:
            print("result error:", ex)
        time.sleep(5)
    if exit_price is None:
        return
    if exit_price == entry:
        res = "draw"
    elif (exit_price > entry) == (sig["direction"] == "CALL"):
        res = "win"
    else:
        res = "loss"
    print(time.strftime("%H:%M"), "result", sym, sig["direction"], entry, "->", exit_price, res.upper())
    with lock:
        state[res] += 1; save()
    if config.SEND_RESULTS:
        text = {"win": "✅ WIN", "loss": "❌ LOSS", "draw": "➖ DRAW"}[res]
        png = None
        try:
            png = trade_chart(pair_name(sym), sig["direction"], df, start_ms, entry, exit_price, res,
                              config.EXPIRY_MINUTES)
        except Exception as e:
            print("chart error:", e)
        stickers = list(state.get("stickers", {}).get("win" if res == "win" else "loss", []))
        for cid, mid in msg_ids.items():
            if not (png and send_photo(cid, png, text, reply_to=mid)):
                send(cid, text, reply_to=mid)
            if res != "draw":
                for st in stickers:
                    send_sticker(cid, st)


def wait_next_minute():
    time.sleep(60 - (time.time() % 60) + 1)   # 1 second after a candle closes


def scanner_loop():
    """One trade at a time: signal -> trade window -> result (+ chart) -> gap -> next signal."""
    next_start_min = 0  # earliest allowed start (epoch seconds) for the next trade
    while True:
        if not state["subscribers"] or not market_open():
            wait_next_minute()
            continue
        now_ms = int(time.time() * 1000)
        best = best_signal(now_ms)
        if not best:
            wait_next_minute()
            continue
        _, sym, sig, _ = best
        recent_pairs.append(sym)
        del recent_pairs[:-config.NO_REPEAT_LAST or None]
        # trade starts at the next full minute (>=10 s lead) and not before the gap is over
        now = time.time()
        start_s = (int(now) // 60 + 1) * 60
        if start_s - now < 10:
            start_s += 60
        start_s = max(start_s, next_start_min)
        start = datetime.fromtimestamp(start_s, timezone.utc)
        end = start + timedelta(minutes=config.EXPIRY_MINUTES)
        text = fmt_signal(sym, sig["direction"], start, end)
        msg_ids = {}
        for cid in list(state["subscribers"]):
            mid = send(cid, text)
            if mid:
                msg_ids[cid] = mid
        check_result(sym, sig, start_s * 1000, msg_ids)  # waits until the trade is finished
        end_s = start_s + config.EXPIRY_MINUTES * 60
        next_start_min = end_s + config.GAP_MINUTES * 60
        # next signal is sent right away; its trade starts after the gap


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
