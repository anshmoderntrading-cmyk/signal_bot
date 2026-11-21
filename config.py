import os


def _int_env(name, default):
    """Read a number from env; on a wrong value, warn and use the default (don't crash)."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"WARNING: {name} must be a number (e.g. {default}) but has a wrong value. "
              f"Using the default {default}. Check this variable in the Render Environment.")
        return default


# Telegram bot token: get it from @BotFather
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Coins to scan (Binance symbols)
# Forex: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, EURJPY, XAUUSD (gold)
# Crypto: BTCUSDT, ETHUSDT ...  (both can be mixed)
SYMBOLS = os.getenv("SYMBOLS", "EURUSD,GBPUSD,USDJPY,AUDUSD,BTCUSDT,ETHUSDT").split(",")

INTERVAL = "1m"          # candle timeframe
EXPIRY_MINUTES = _int_env("EXPIRY_MINUTES", 1)   # trade expiry
MIN_SCORE = _int_env("MIN_SCORE", 4)   # minimum confluence score; higher = fewer but stricter signals
COOLDOWN_MINUTES = 5     # no repeat signal on the same coin within this many minutes

STATS_FILE = os.getenv("STATS_FILE", os.path.join(os.path.dirname(__file__), "stats.json"))
