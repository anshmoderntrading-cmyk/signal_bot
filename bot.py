"""
Telegram Signal Bot: live Binance data -> strategy -> signal -> result after expiry.
Run:  TELEGRAM_BOT_TOKEN=xxxx python bot.py
Commands: /start  /stop  /stats  /scan  /coins
"""
import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta

import requests

import config
from data import get_klines, closed_candles, is_fresh, is_crypto
from strategy import analyze

API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
IST = timezone(timedelta(hours=5, minutes=30))
lock = threading.Lock()


# ---------------- storage ----------------
def load():
    if os.path.exists(config.STATS_FILE):
        with open(config.STATS_FILE) as f:
            return json.load(f)
    return {"subscribers": [], "win": 0, "loss": 0, "draw": 0, "history": []}


def save():
    with open(config.STATS_FILE, "w") as f:
        json.dump(state, f, indent=1)


state = load()
last_signal_time = {}


# ---------------- telegram ----------------
def send(chat_id, text):
    try:
        requests.post(f"{API}/sendMessage",
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print("send error:", e)


def broadcast(text):
    for cid in list(state["subscribers"]):
        send(cid, text)


def stats_text():
    w, l, d = state["win"], state["loss"], state["draw"]
    t = w + l
    acc = 100 * w / t if t else 0
    last = state["history"][-10:]
    lines = "\n".join(f"{h['symbol']} {h['direction']} → {h['result']}" for h in last) or "—"
    return (f"📊 <b>Live Stats</b>\nTotal: {t + d} | ✅ Win: {w} | ❌ Loss: {l} | ➖ Draw: {d}\n"
            f"🎯 Accuracy: <b>{acc:.1f}%</b>\n\nLast 10:\n{lines}")


def handle(msg):
    cid = msg["chat"]["id"]
    txt = (msg.get("text") or "").strip().lower()
    with lock:
        if txt.startswith("/start"):
            if cid not in state["subscribers"]:
                state["subscribers"].append(cid); save()
            send(cid, "✅ Subscribed! Every minute the market is scanned and signals land here.\n"
                      "Commands: /stats /scan /coins /stop\n\n"
                      "⚠️ This is not financial advice. Trade with risk management.")
        elif txt.startswith("/stop"):
            if cid in state["subscribers"]:
                state["subscribers"].remove(cid); save()
            send(cid, "🛑 Unsubscribed.")
        elif txt.startswith("/stats"):
            send(cid, stats_text())
        elif txt.startswith("/coins"):
            send(cid, "Scanning: " + ", ".join(config.SYMBOLS))
        elif txt.startswith("/scan"):
            threading.Thread(target=manual_scan, args=(cid,), daemon=True).start()


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
def fp(x):
    return f"{x:.2f}" if x >= 1000 else f"{x:.5f}"


def fmt_signal(sym, sig, entry_time, expiry_time):
    market = "Crypto" if is_crypto(sym) else "Forex"
    arrow = "🟢 CALL (UP) ⬆️" if sig["direction"] == "CALL" else "🔴 PUT (DOWN) ⬇️"
    conf = int(100 * sig["score"] / sig["max"])
    reasons = "\n".join("• " + r for r in sig["reasons"])
    return (f"📢 <b>NEW SIGNAL</b>\n\n💱 Pair: <b>{sym}</b> ({market})\n📈 Direction: <b>{arrow}</b>\n"
            f"💰 Entry price: {fp(sig['price'])}\n"
            f"🕐 Entry: {entry_time.astimezone(IST):%H:%M:%S} IST\n"
            f"⏳ Expiry: {config.EXPIRY_MINUTES} min ({expiry_time.astimezone(IST):%H:%M:%S} IST)\n"
            f"⭐ Strength: {sig['score']}/{sig['max']} ({conf}%)\n\n<b>Reasons:</b>\n{reasons}")


def check_result(sym, sig, entry_close_ms):
    """Wait for expiry, then compare the expiry candle's close with the entry."""
    target_close = entry_close_ms + config.EXPIRY_MINUTES * 60_000
    time.sleep(max(0, (target_close - time.time() * 1000) / 1000) + 3)
    exit_price = None
    for _ in range(12):  # forex data can lag a few seconds
        try:
            df = get_klines(sym, config.INTERVAL, 10)
            row = df[df["close_time"] == target_close]
            if len(row):
                exit_price = float(row["close"].iloc[0]); break
        except Exception as e:
            print("result fetch error:", e)
        time.sleep(5)
    if exit_price is None:
        broadcast(f"⚠️ {sym}: could not fetch the result price."); return
    entry = sig["price"]
    if exit_price == entry:
        res, icon = "DRAW", "➖"
    elif (exit_price > entry) == (sig["direction"] == "CALL"):
        res, icon = "WIN", "✅"
    else:
        res, icon = "LOSS", "❌"
    pct = (exit_price - entry) / entry * 100
    with lock:
        state[res.lower()] += 1
        state["history"].append({"symbol": sym, "direction": sig["direction"], "entry": entry,
                                 "exit": exit_price, "result": res, "time": int(time.time())})
        state["history"] = state["history"][-500:]
        save()
        w, l = state["win"], state["loss"]
    acc = 100 * w / (w + l) if w + l else 0
    broadcast(f"{icon} <b>RESULT: {res}</b>\n💱 {sym} {sig['direction']}\n"
              f"Entry: {fp(entry)} → Exit: {fp(exit_price)} ({pct:+.3f}%)\n"
              f"📊 Overall accuracy: {acc:.1f}% ({w}W / {l}L)")


def scan_symbol(sym, now_ms, force_chat=None):
    df = closed_candles(get_klines(sym, config.INTERVAL, 300), now_ms)
    if not is_fresh(df, now_ms):
        return False  # market closed (forex weekend) / stale data
    sig = analyze(df, config.MIN_SCORE)
    if not sig:
        return False
    if force_chat is None:
        last = last_signal_time.get(sym, 0)
        if now_ms - last < config.COOLDOWN_MINUTES * 60_000:
            return False
        last_signal_time[sym] = now_ms
    entry_close_ms = int(df["close_time"].iloc[-1])
    entry_time = datetime.fromtimestamp((entry_close_ms + 1) / 1000, timezone.utc)
    expiry_time = entry_time + timedelta(minutes=config.EXPIRY_MINUTES)
    text = fmt_signal(sym, sig, entry_time, expiry_time)
    if force_chat is None:
        broadcast(text)
        threading.Thread(target=check_result, args=(sym, sig, entry_close_ms), daemon=True).start()
    else:
        send(force_chat, text + "\n\n(manual scan: result not tracked)")
    return True


def manual_scan(cid):
    now = int(time.time() * 1000)
    found = False
    for s in config.SYMBOLS:
        try:
            found |= scan_symbol(s.strip(), now, force_chat=cid)
        except Exception as e:
            print(s, e)
    if not found:
        send(cid, "🔍 No strong setup right now. Wait for the next candle.")


def scanner_loop():
    while True:
        # run 1 second after every minute closes
        time.sleep(60 - (time.time() % 60) + 1)
        if not state["subscribers"]:
            continue
        now = int(time.time() * 1000)
        for s in config.SYMBOLS:
            try:
                scan_symbol(s.strip(), now)
            except Exception as e:
                print("scan error", s, e)


if __name__ == "__main__":
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN first (token from @BotFather).")
    print("Bot running... send /start to your bot on Telegram")
    threading.Thread(target=scanner_loop, daemon=True).start()
    poll_updates()
