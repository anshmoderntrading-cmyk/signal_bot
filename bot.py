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
from strategy import analyze, analyze_v2
from rules import signal_now

RULES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "best_rules.json")
_rules_cache = {"mtime": None, "data": None}


def load_rules():
    """Rules found by research.py (reloaded automatically when the file changes)."""
    try:
        mt = os.path.getmtime(RULES_FILE)
    except OSError:
        return None
    if mt != _rules_cache["mtime"]:
        try:
            with open(RULES_FILE) as f:
                _rules_cache["data"] = json.load(f)
            _rules_cache["mtime"] = mt
        except Exception as e:
            print("best_rules.json error:", e)
            return None
    return _rules_cache["data"]


def active_strategy():
    return state.get("strategy") or config.STRATEGY


def analyze_ob(sym, df):
    d = signal_now(df, "order_block")
    if not d:
        return None
    return {"direction": "CALL" if d > 0 else "PUT", "score": 5, "max": 5, "reasons": ["order_block"],
            "price": float(df["close"].iloc[-1]), "edge": 0}


def analyze_auto(sym, df):
    data = load_rules()
    if not data:
        return None
    for r in data.get("rules", []):
        if r["pairs"] != "ALL" and sym not in r["pairs"]:
            continue
        d = signal_now(df, r["rule"])
        if d:
            return {"direction": "CALL" if d > 0 else "PUT", "score": r["test_acc"], "max": 100,
                    "reasons": [r["rule"]], "price": float(df["close"].iloc[-1]), "edge": 0,
                    "expiry": int(r["expiry"])}
    return None
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
BTN_LIVE, BTN_OTC = "📈 LIVE Market", "🌙 OTC Market"
BTN_STATUS = "⚙️ Status"
BTN_FX_ONLY, BTN_CRYPTO = "💱 Only Currency", "🪙 Currency + Crypto"
BTN_OB, BTN_NORMAL = "📦 Order Block", "📊 Normal"
EXPIRY_BTNS = {f"{m} Min": m for m in range(1, 6)}
KEYBOARD = {"keyboard": [[{"text": BTN_ON}, {"text": BTN_STOP}],
                         [{"text": BTN_LIVE}, {"text": BTN_OTC}],
                         [{"text": t} for t in EXPIRY_BTNS],
                         [{"text": BTN_FX_ONLY}, {"text": BTN_CRYPTO}],
                         [{"text": BTN_OB}, {"text": BTN_NORMAL}],
                         [{"text": BTN_STATUS}]], "resize_keyboard": True}
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
state.setdefault("mode", "otc")
state.setdefault("admins", [])
state.setdefault("blocked_pairs", [])
state.setdefault("crypto", False)
state.setdefault("strategy", "")
state.setdefault("session_stickers", {})   # {"start": {...}, "close": {...}}
state.setdefault("session", {"w": 0, "l": 0, "streak": 0})  # "" = use .env STRATEGY; "ob" = order block  # include OTC crypto (ETCUSD, DASUSD...) in the pair list  # pairs the admin removed (e.g. not visible in their Quotex app)  # chat ids added by the owner
state.setdefault("pair_results", {})  # pair -> last 20 results ("win"/"loss")  # Quotex only: "otc" (every day) or "live" (real market, Mon-Fri)
pending_sticker = {}  # chat_id -> sticker file_id waiting for "win"/"loss"
recent_pairs = []
last_scan = {"text": "no scan yet"}  # last few signalled pairs, so every signal comes from a different market


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


def is_owner(cid):
    return bool(config.OWNER_ID) and cid == config.OWNER_ID


def is_admin(cid):
    """Owner + admins added by the owner may change settings. No owner set -> everyone (single-user bot)."""
    if not config.OWNER_ID:
        return True
    return is_owner(cid) or cid in state.get("admins", [])


def current_expiry(sig=None):
    """Admin-chosen expiry (buttons) wins; otherwise the rule's own expiry; otherwise .env."""
    if state.get("expiry"):
        return int(state["expiry"])
    if sig and sig.get("expiry"):
        return int(sig["expiry"])
    return config.EXPIRY_MINUTES


def status_text():
    w, l = state.get("win", 0), state.get("loss", 0)
    acc = f"{100 * w / (w + l):.1f}%" if w + l else "-"
    mode = ("🌙 OTC" if state.get("mode") != "live" else "📈 LIVE") if QX is not None else "📈 LIVE"
    exp = f"{state['expiry']} Min" if state.get("expiry") else "auto (from strategy)"
    on = "🟢 ON" if state["subscribers"] else "🔴 OFF"
    if QX is not None:
        conn = "🟢 connected" if QX.connected else "🔴 NOT connected (login blocked/retrying)"
    else:
        conn = "real forex feed"
    rules = ""
    if config.STRATEGY == "auto":
        data = load_rules()
        n = len(data.get("rules", [])) if data else 0
        rules = f" ({n} rule{'s' if n != 1 else ''} loaded)" + ("  ⚠️ no rules -> no signals!" if n == 0 else "")
    return (f"⚙️ Settings\n"
            f"Quotex: {conn}\nLast scan: {last_scan['text']}\n"
            f"Signals: {on}\nMarket: {mode}\nExpiry: {exp}\n"
            f"Pairs: {'currency + crypto' if state.get('crypto') else 'currency only'}\n"
            f"Strategy: {'📦 Order Block' if active_strategy() == 'ob' else config.STRATEGY + rules}\nMin payout: {config.MIN_PAYOUT}%\n"
            f"Gap after trade: {config.GAP_MINUTES} min\n"
            f"Session: {state['session']['w']} W / {state['session']['l']} L, "
            f"win streak {state['session']['streak']} (auto-stop at {config.AUTO_STOP_WINS})\n"
            f"Channels ON: {', '.join(str(c) for c in state['subscribers'] if c < 0) or 'none'}\n"
            f"Session stickers: start {'✅' if state['session_stickers'].get('start') else '❌'}"
            f" / close {'✅' if state['session_stickers'].get('close') else '❌'}\n"
            f"Record: {w} W / {l} L ({acc})")


def handle(msg):
    cid = msg["chat"]["id"]
    txt = (msg.get("text") or "").strip()
    allowed = (cid == config.ADMIN_CHAT_ID) if config.ADMIN_CHAT_ID else (cid in state["subscribers"])
    if OTP["waiting"] and txt.isdigit() and allowed:
        OTP["code"] = txt
        send(cid, "✅ Code received, logging in to Quotex...")
        return
    if "sticker" in msg:  # user sends a sticker -> ask whether it is for WIN or LOSS
        if not is_admin(cid):
            return
        pending_sticker[cid] = (msg["sticker"]["file_id"], msg["sticker"]["file_unique_id"])
        send(cid, "🎨 Sticker received! What is it for? Type one word:\n"
                  "win  /  loss  /  start (Session Starts)  /  close (Session Closed)", keyboard=True)
        return
    low = txt.lower()
    if cid in pending_sticker and low in ("start", "close", "session start", "session close"):
        fid, uid = pending_sticker.pop(cid)
        kind = "start" if "start" in low else "close"
        with lock:
            state["session_stickers"][kind] = {"file_id": fid, "unique_id": uid}
            save()
        send(cid, ("✅ Saved as SESSION START.\nPost this sticker in your channel -> signals start there."
                   if kind == "start" else
                   "✅ Saved as SESSION CLOSED.\nPost it in your channel -> signals stop there.\n"
                   f"The bot also posts it itself after {config.AUTO_STOP_WINS} wins in a row."),
             keyboard=True)
        return
    if cid in pending_sticker and low in ("win", "loss", "itm", "otm"):
        kind = "win" if low in ("win", "itm") else "loss"
        with lock:
            state["stickers"][kind].append(pending_sticker.pop(cid)[0])
            save()
            n = len(state["stickers"][kind])
        send(cid, f"✅ Saved. {n} sticker(s) will now be sent after every {kind.upper()}.\n"
                  "Add more: send another sticker. Remove all: /clearstickers", keyboard=True)
        return
    if low.startswith("/clearstickers"):
        if not is_admin(cid):
            send(cid, "⛔ Only the admin can change settings.", keyboard=True); return
        with lock:
            state["stickers"] = {"win": [], "loss": []}
            save()
        send(cid, "🗑️ All stickers removed.", keyboard=True)
        return
    with lock:
        if txt == BTN_ON or txt.lower().startswith(("/start", "/on")):
            if cid not in state["subscribers"]:
                state["subscribers"].append(cid); save()
            mode = ("🌙 OTC" if state.get("mode") != "live" else "📈 LIVE") if QX is not None else "📈 LIVE"
            note = "" if market_open() else "\n⚠️ The live market is closed right now (weekend). Press 🌙 OTC Market, or wait for Monday."
            note = f"\nMode: {mode}" + note
            send(cid, f"✅ Signal ON\nOne trade at a time: result + chart, then the next signal after {config.GAP_MINUTES} min.{note}", keyboard=True)
        elif txt in EXPIRY_BTNS:
            if not is_admin(cid):
                send(cid, "⛔ Only the admin can change settings.", keyboard=True); return
            state["expiry"] = EXPIRY_BTNS[txt]; save()
            send(cid, f"⏱️ Expiry set: {state['expiry']} Min\nAll new signals will be {state['expiry']}-minute trades.",
                 keyboard=True)
        elif low.startswith(("/addadmin", "/removeadmin", "/admins")):
            if not is_owner(cid):
                send(cid, "⛔ Only the owner can manage admins.", keyboard=True); return
            parts = txt.split()
            if low.startswith("/admins"):
                lst = "\n".join(f"• {a}" for a in state["admins"]) or "(none)"
                send(cid, f"👑 Owner: {config.OWNER_ID}\n🛡️ Admins:\n{lst}", keyboard=True); return
            if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
                send(cid, "Usage: /addadmin 123456789   or   /removeadmin 123456789\n"
                          "(the person gets their ID by sending /id to this bot)", keyboard=True); return
            aid = int(parts[1])
            if low.startswith("/addadmin"):
                if aid not in state["admins"]:
                    state["admins"].append(aid); save()
                send(cid, f"✅ {aid} is now an admin.", keyboard=True)
                send(aid, "🛡️ You are now an admin of this bot. You can change market, expiry and stickers.",
                     keyboard=True)
            else:
                if aid in state["admins"]:
                    state["admins"].remove(aid); save()
                send(cid, f"🗑️ {aid} is no longer an admin.", keyboard=True)
        elif low.startswith("/pairs"):
            syms = [s.replace("_otc", "") for s in current_symbols()]
            names = ", ".join(f"{s[:3]}/{s[3:]}" for s in syms) or "(none right now)"
            bl = ", ".join(state["blocked_pairs"]) or "(none)"
            send(cid, f"📋 Pairs being scanned now (payout >= {config.MIN_PAYOUT}%):\n{names}\n\n"
                      f"🚫 Blocked: {bl}\n\nRemove a pair: /block USDBDT\nAllow again: /unblock USDBDT",
                 keyboard=True)
        elif low.startswith(("/block", "/unblock")):
            if not is_admin(cid):
                send(cid, "⛔ Only the admin can change settings.", keyboard=True); return
            parts = txt.upper().split()[1:]
            pairs = [p.replace("/", "").replace("_OTC", "").replace("(OTC)", "").replace("OTC", "")
                     for p in parts]
            pairs = [p for p in pairs if len(p) == 6 and p.isalpha()]
            if not pairs:
                send(cid, "Usage: /block USDBDT   (several: /block USDBDT USDPKR)", keyboard=True); return
            for p in pairs:
                if low.startswith("/block") and p not in state["blocked_pairs"]:
                    state["blocked_pairs"].append(p)
                elif low.startswith("/unblock") and p in state["blocked_pairs"]:
                    state["blocked_pairs"].remove(p)
            save()
            send(cid, f"{'🚫 Blocked' if low.startswith('/block') else '✅ Allowed'}: {', '.join(pairs)}\n"
                      f"Blocked list: {', '.join(state['blocked_pairs']) or '(none)'}", keyboard=True)
        elif low.startswith("/resetrecord"):
            if not is_admin(cid):
                send(cid, "⛔ Only the admin can change settings.", keyboard=True); return
            if low.strip() not in ("/resetrecord yes", "/resetrecord_yes"):
                w, l = state.get("win", 0), state.get("loss", 0)
                send(cid, f"⚠️ This resets the record ({w} W / {l} L) to 0.\n"
                          "The old trade list is kept in a backup file.\n\nTo confirm tap: /resetrecord_yes",
                     keyboard=True)
                return
            old = (state.get("win", 0), state.get("loss", 0))
            state["win"] = state["loss"] = state["draw"] = 0
            state["pair_results"] = {}
            save()
            backup = ""
            if os.path.exists(RESULTS_CSV):
                backup = f"results_{time.strftime('%Y%m%d_%H%M')}.csv"
                os.replace(RESULTS_CSV, os.path.join(os.path.dirname(RESULTS_CSV), backup))
            send(cid, f"🔄 Record reset. Old: {old[0]} W / {old[1]} L"
                      + (f" (saved as {backup})" if backup else "") + "\nNew record starts from 0 W / 0 L.",
                 keyboard=True)
        elif low.startswith("/id"):
            role = "👑 Owner" if is_owner(cid) else ("🛡️ Admin" if is_admin(cid) and config.OWNER_ID else "Member")
            send(cid, f"Your chat ID: {cid}\nRole: {role}", keyboard=True)
        elif txt in (BTN_OB, BTN_NORMAL):
            if not is_admin(cid):
                send(cid, "⛔ Only the admin can change settings.", keyboard=True); return
            state["strategy"] = "ob" if txt == BTN_OB else ""; save()
            send(cid, "📦 Order Block strategy ON\nSignal only when price comes back into an order block "
                      "zone and rejects it. Fewer signals, waits for the setup." if state["strategy"] == "ob"
                 else f"📊 Normal strategy ({config.STRATEGY})", keyboard=True)
        elif txt in (BTN_FX_ONLY, BTN_CRYPTO):
            if not is_admin(cid):
                send(cid, "⛔ Only the admin can change settings.", keyboard=True); return
            state["crypto"] = txt == BTN_CRYPTO; save()
            _pairs_cache["t"] = 0  # rebuild the pair list on the next scan
            send(cid, "🪙 Crypto ON: currency + crypto pairs (ETC, DASH, ZEC...)" if state["crypto"]
                 else "💱 Only currency pairs (no crypto)", keyboard=True)
        elif txt == BTN_STATUS or low.startswith("/status"):
            send(cid, status_text(), keyboard=True)
        elif txt == BTN_LIVE or low.startswith("/live"):
            if not is_admin(cid):
                send(cid, "⛔ Only the admin can change settings.", keyboard=True); return
            state["mode"] = "live"; save()
            note = "" if forex_week_open() else "\n⚠️ The live market is closed now (weekend). Signals start Monday ~3:30 AM IST, or press 🌙 OTC Market."
            send(cid, f"📈 LIVE Market selected\nReal market pairs (Mon-Fri).{note}", keyboard=True)
        elif txt == BTN_OTC or low.startswith("/otc"):
            if not is_admin(cid):
                send(cid, "⛔ Only the admin can change settings.", keyboard=True); return
            state["mode"] = "otc"; save()
            send(cid, "🌙 OTC Market selected\nOTC pairs (every day, 24/7).", keyboard=True)
        elif txt == BTN_STOP or txt.lower().startswith(("/stop", "/off")):
            if cid in state["subscribers"]:
                state["subscribers"].remove(cid); save()
            send(cid, "⛔ Signal STOP", keyboard=True)
        else:
            send(cid, "Use the button 👇", keyboard=True)


def session_summary():
    s = state["session"]
    n = s["w"] + s["l"]
    acc = f" ({100 * s['w'] / n:.0f}%)" if n else ""
    return f"📊 Session result: {s['w']} WIN / {s['l']} LOSS{acc}"


def start_session(chat_id):
    with lock:
        if chat_id not in state["subscribers"]:
            state["subscribers"].append(chat_id)
        state["session"] = {"w": 0, "l": 0, "streak": 0}
        save()
    print("session started in", chat_id)


def stop_session(chat_ids, reason="", post_sticker=False):
    """Stop signals for these chats and post the summary (+ Session Closed sticker if asked)."""
    summary = session_summary()
    with lock:
        for c in chat_ids:
            if c in state["subscribers"]:
                state["subscribers"].remove(c)
        save()
    close = state["session_stickers"].get("close")
    for c in chat_ids:
        if post_sticker and close:
            send_sticker(c, close["file_id"])
        send(c, (reason + "\n" if reason else "") + summary)
    print("session stopped in", chat_ids, reason)


def handle_channel(post):
    """Admin posts the Session Starts / Session Closed sticker in the channel."""
    cid = post["chat"]["id"]
    st = post.get("sticker")
    if not st:
        return
    uid = st.get("file_unique_id")
    ss = state["session_stickers"]
    if ss.get("start") and uid == ss["start"]["unique_id"]:
        start_session(cid)
    elif ss.get("close") and uid == ss["close"]["unique_id"]:
        stop_session([cid])


def poll_updates():
    offset = None
    while True:
        try:
            r = requests.get(f"{API}/getUpdates", params={"timeout": 30, "offset": offset}, timeout=40).json()
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                if "message" in u:
                    handle(u["message"])
                elif "channel_post" in u:
                    handle_channel(u["channel_post"])
        except Exception as e:
            print("poll error:", e); time.sleep(5)


# ---------------- signals ----------------
_pairs_cache = {"t": 0, "mode": None, "list": []}


def current_symbols():
    """Pairs to scan. Quotex + AUTO_PAIRS: every open currency pair with payout >= MIN_PAYOUT
    (refreshed every 5 min); otherwise the fixed SYMBOLS list."""
    if QX is None:
        blocked = set(state.get("blocked_pairs", []))
        return [s for s in config.SYMBOLS if s not in blocked]
    live = state.get("mode") == "live"
    base = [s.replace("_otc", "") for s in config.SYMBOLS]
    fixed = base if live else [s + "_otc" for s in base]
    if not config.AUTO_PAIRS or not QX.connected:
        return fixed
    if time.time() - _pairs_cache["t"] > 300 or _pairs_cache["mode"] != state.get("mode"):
        found = QX.tradable_pairs(otc=not live, min_payout=config.MIN_PAYOUT,
                                  crypto=bool(state.get("crypto")))
        if found:
            print("pairs with payout >= %d%%:" % config.MIN_PAYOUT,
                  ", ".join(f"{n.replace('_otc', '')} {int(p)}%" for n, p in found))
        _pairs_cache.update(t=time.time(), mode=state.get("mode"), list=[n for n, _ in found])
    lst = _pairs_cache["list"] or fixed
    blocked = set(state.get("blocked_pairs", []))
    return [s for s in lst if s.replace("_otc", "") not in blocked]


def market_open(now=None):
    """OTC: always open. Live / real forex: Sun 22:00 UTC – Fri 22:00 UTC."""
    if QX is not None and state.get("mode") != "live":
        return True
    return forex_week_open(now)


def forex_week_open(now=None):
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
    tag = " OTC" if sym.lower().endswith("_otc") else " LIVE"
    return f"{base[:3]}/{base[3:]}{tag}"


def fmt_signal(sym, direction, start, end, expiry=None):
    expiry = expiry or config.EXPIRY_MINUTES
    side = "🟢 BUY" if direction == "CALL" else "🔴 SELL"
    t = lambda d: d.astimezone(IST).strftime("%I:%M %p")
    return (f"{pair_name(sym)} {side}\n"
            f"⏱️ {expiry} Min\n"
            f"🕒 {t(start)} – {t(end)}")


def pair_is_weak(sym):
    r = state.get("pair_results", {}).get(sym, [])
    if len(r) < config.PAIR_MIN_TRADES:
        return False
    return 100 * r.count("win") / len(r) < config.PAIR_MIN_WINRATE


def best_signal(now_ms):
    """Scan all pairs and pick the strongest setup."""
    best = None
    stats = {"ok": 0, "stale": 0, "closed": 0, "no_setup": 0, "error": 0, "few_candles": 0, "weak_pair": 0, "low_payout": 0}
    payouts = {}
    for sym in current_symbols():
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
            if QX is not None:
                pay = QX.payout(sym)
                payouts[sym.replace("_otc", "")] = "?" if pay is None else int(pay)
                if pay is None or pay < config.MIN_PAYOUT:
                    stats["low_payout"] += 1
                    continue
            if pair_is_weak(sym):
                stats["weak_pair"] += 1
                continue
            force = not config.QUALITY_ONLY
            if active_strategy() == "ob":
                sig = analyze_ob(sym, df)
            elif config.STRATEGY == "auto":
                sig = analyze_auto(sym, df)
            elif config.STRATEGY == "v2":
                sig = analyze_v2(df, config.MIN_SCORE_V2, force=force)
            else:
                sig = analyze(df, config.MIN_SCORE, force=force)
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
    if config.STRATEGY == "auto":
        data = load_rules()
        if not data or not data.get("rules"):
            pick += "  (STRATEGY=auto but best_rules.json has no rules: run python research.py)"
        elif QX is not None and data.get("mode") != state.get("mode"):
            pick += f"  (note: rules were researched for {data.get('mode')}, mode is {state.get('mode')})"
    print(time.strftime("%H:%M"), "scan:", stats, pick)
    why = []
    if stats["error"]: why.append(f"{stats['error']} data errors")
    if stats["low_payout"]: why.append(f"{stats['low_payout']} payout<{config.MIN_PAYOUT}%")
    if stats["no_setup"]: why.append(f"{stats['no_setup']} no setup")
    if stats["closed"]: why.append(f"{stats['closed']} closed")
    if stats["stale"]: why.append(f"{stats['stale']} no fresh data")
    if stats["weak_pair"]: why.append(f"{stats['weak_pair']} weak pair")
    last_scan["text"] = (f"{time.strftime('%H:%M')} -> " + (f"{best[1]} {best[2]['direction']}" if best else
                         "no signal (" + (", ".join(why) or "nothing") + ")"))
    if payouts:
        print("   payout %:", payouts)
    return best


RESULTS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.csv")


def log_result(sym, sig, start_ms, expiry, entry, exit_price, res):
    """Every trade is appended to results.csv -> honest record (python stats.py)."""
    new = not os.path.exists(RESULTS_CSV)
    try:
        with open(RESULTS_CSV, "a") as f:
            if new:
                f.write("time_ist,pair,direction,expiry_min,strategy,rule,entry,exit,result\n")
            t = datetime.fromtimestamp(start_ms / 1000, timezone.utc).astimezone(IST)
            rule = (sig.get("reasons") or [""])[0] if active_strategy() in ("auto", "ob") else ""
            f.write(f"{t:%Y-%m-%d %H:%M},{sym},{sig['direction']},{expiry},{active_strategy()},"
                    f"{rule},{entry},{exit_price},{res}\n")
    except Exception as e:
        print("results.csv error:", e)


def check_result(sym, sig, start_ms, msg_ids):
    """Trade window [start, start+expiry]: entry = price at start, exit = price at end."""
    entry_close = start_ms - 1                       # candle that closes exactly at start
    expiry = sig.get("expiry", config.EXPIRY_MINUTES)
    exit_close = entry_close + expiry * 60_000
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
    log_result(sym, sig, start_ms, expiry, entry, exit_price, res)
    with lock:
        s = state["session"]
        if res == "win":
            s["w"] += 1; s["streak"] += 1
        elif res == "loss":
            s["l"] += 1; s["streak"] = 0
        state[res] += 1
        if res != "draw":
            pr = state.setdefault("pair_results", {}).setdefault(sym, [])
            pr.append(res)
            del pr[:-20]
        save()
    if config.SEND_RESULTS:
        text = {"win": "✅ WIN", "loss": "❌ LOSS", "draw": "➖ DRAW"}[res]
        png = None
        try:
            png = trade_chart(pair_name(sym), sig["direction"], df, start_ms, entry, exit_price, res,
                              expiry)
        except Exception as e:
            print("chart error:", e)
        stickers = list(state.get("stickers", {}).get("win" if res == "win" else "loss", []))
        for cid, mid in msg_ids.items():
            if not (png and send_photo(cid, png, text, reply_to=mid)):
                send(cid, text, reply_to=mid)
            if res != "draw":
                for st in stickers:
                    send_sticker(cid, st)
    if config.AUTO_STOP_WINS and state["session"]["streak"] >= config.AUTO_STOP_WINS:
        channels = [c for c in state["subscribers"] if c < 0]  # channels/groups have negative ids
        targets = channels or list(state["subscribers"])
        stop_session(targets, f"🏁 {config.AUTO_STOP_WINS} wins in a row - session closed automatically.",
                     post_sticker=True)


def wait_next_minute():
    time.sleep(60 - (time.time() % 60) + 1)   # 1 second after a candle closes


def scanner_loop():
    """One trade at a time: signal -> trade window -> result (+ chart) -> gap -> next signal."""
    next_start_min = 0  # earliest allowed start (epoch seconds) for the next trade
    while True:
        if not state["subscribers"] or not market_open() or (QX is not None and not QX.connected):
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
        expiry = current_expiry(sig)
        sig["expiry"] = expiry
        end = start + timedelta(minutes=expiry)
        text = fmt_signal(sym, sig["direction"], start, end, expiry)
        msg_ids = {}
        for cid in list(state["subscribers"]):
            mid = send(cid, text)
            if mid:
                msg_ids[cid] = mid
        check_result(sym, sig, start_s * 1000, msg_ids)  # waits until the trade is finished
        end_s = start_s + expiry * 60
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
