import os


def _int_env(name, default):
    """Read a number from env; on a wrong value, warn and use the default (don't crash)."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"WARNING: {name} must be a number (e.g. {default}). Using default {default}.")
        return default


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Forex pairs only
SYMBOLS = [s.strip().upper() for s in os.getenv(
    "SYMBOLS", "EURUSD,GBPUSD,USDJPY,AUDUSD,AUDJPY,EURJPY,GBPJPY,USDCAD,NZDUSD,EURGBP").split(",") if s.strip()]

INTERVAL = "1m"
EXPIRY_MINUTES = _int_env("EXPIRY_MINUTES", 1)       # trade expiry
SIGNAL_EVERY_MINUTES = _int_env("SIGNAL_EVERY_MINUTES", 2)  # an automatic signal every N minutes
MIN_SCORE = _int_env("MIN_SCORE", 4)
SEND_RESULTS = os.getenv("SEND_RESULTS", "1") != "0"  # short WIN/LOSS reply after expiry (0 = off)

STATS_FILE = os.getenv("STATS_FILE", os.path.join(os.path.dirname(__file__), "stats.json"))
