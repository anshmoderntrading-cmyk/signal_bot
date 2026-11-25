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


def _load_dotenv(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
    """Read KEY=VALUE lines from .env (handy on a laptop)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

# DATA_SOURCE: "forex" = real market (Yahoo/Twelve Data), "quotex" = Quotex OTC (laptop)
DATA_SOURCE = os.getenv("DATA_SOURCE", "forex").strip().lower()
QUOTEX_EMAIL = os.getenv("QUOTEX_EMAIL", "").strip()
QUOTEX_PASSWORD = os.getenv("QUOTEX_PASSWORD", "").strip()
# Quotex website domain (whichever one opens Quotex for you in the browser), e.g. qxbroker.com
QUOTEX_HOST = os.getenv("QUOTEX_HOST", "").strip().replace("https://", "").replace("http://", "").strip("/")

# Optional: only this Telegram chat may enter the Quotex OTP (your own chat id)
ADMIN_CHAT_ID = _int_env("ADMIN_CHAT_ID", 0)
# OWNER_ID: full power (settings + add/remove admins). Falls back to ADMIN_CHAT_ID.
OWNER_ID = _int_env("OWNER_ID", 0) or ADMIN_CHAT_ID

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Forex pairs only
_DEFAULT = "EURUSD,GBPUSD,USDJPY,AUDUSD,AUDJPY,EURJPY,GBPJPY,USDCAD,NZDUSD,EURGBP"
SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOLS", _DEFAULT).split(",") if s.strip()]
if DATA_SOURCE == "quotex":  # Quotex OTC names: EURUSD_otc
    SYMBOLS = [s.replace("_OTC", "") + "_otc" for s in SYMBOLS]

INTERVAL = "1m"
EXPIRY_MINUTES = _int_env("EXPIRY_MINUTES", 1)       # trade expiry
SIGNAL_EVERY_MINUTES = max(1, _int_env("SIGNAL_EVERY_MINUTES", 1))  # an automatic signal every N minutes
GAP_MINUTES = max(0, _int_env("GAP_MINUTES", 1))  # wait this long after a trade ends before the next trade
NO_REPEAT_LAST = max(0, _int_env("NO_REPEAT_LAST", 3))  # don't repeat a pair used in the last N signals
MIN_SCORE = _int_env("MIN_SCORE", 4)          # strategy v1 threshold (0-8)
STRATEGY = os.getenv("STRATEGY", "v2").strip().lower()   # v2 = trend/level strategy with filters
MIN_SCORE_V2 = _int_env("MIN_SCORE_V2", 5)    # strategy v2 threshold (0-7); higher = fewer, stronger signals
# QUALITY_ONLY=1: send a signal only when a setup is strong enough (fewer signals, fewer losses)
# QUALITY_ONLY=0: always send the best available setup every cycle (more signals, more losses)
QUALITY_ONLY = os.getenv("QUALITY_ONLY", "1") != "0"
# skip a pair when its recent live record is bad (after PAIR_MIN_TRADES trades, win% below PAIR_MIN_WINRATE)
MIN_PAYOUT = _int_env("MIN_PAYOUT", 85)  # Quotex: skip pairs whose payout % is below this
# Quotex: scan every open currency pair with payout >= MIN_PAYOUT (not only SYMBOLS). 0 = use SYMBOLS only
AUTO_PAIRS = os.getenv("AUTO_PAIRS", "1") != "0"
AUTO_STOP_WINS = max(0, _int_env("AUTO_STOP_WINS", 5))  # stop the session after N wins in a row (0 = off)
MTG_STEPS = max(0, _int_env("MTG_STEPS", 1))        # martingale steps after a loss
MTG_MULT = os.getenv("MTG_MULT", "2.2").strip()      # shown in the MTG signal (amount multiplier)
# strict strategies (Order Block / auto / v2): if no setup for this many minutes, send the best
# normal setup instead, so members get at least one signal every N minutes (0 = never fall back)
MAX_WAIT_MINUTES = max(0, _int_env("MAX_WAIT_MINUTES", 5))
# Mini App settings page (GitHub Pages of this repo). Empty = keep the old big button keyboard.
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://anshmoderntrading-cmyk.github.io/signal_bot/").strip()
PAIR_MIN_TRADES = _int_env("PAIR_MIN_TRADES", 8)
PAIR_MIN_WINRATE = _int_env("PAIR_MIN_WINRATE", 45)
SEND_RESULTS = os.getenv("SEND_RESULTS", "1") != "0"  # short WIN/LOSS reply after expiry (0 = off)

STATS_FILE = os.getenv("STATS_FILE", os.path.join(os.path.dirname(__file__), "stats.json"))
