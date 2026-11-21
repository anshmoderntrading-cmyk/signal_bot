import os

# Telegram bot token: get it from @BotFather
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Coins to scan (Binance symbols)
# Forex: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, EURJPY, XAUUSD (gold)
# Crypto: BTCUSDT, ETHUSDT ...  (both can be mixed)
SYMBOLS = os.getenv("SYMBOLS", "EURUSD,GBPUSD,USDJPY,AUDUSD,BTCUSDT,ETHUSDT").split(",")

INTERVAL = "1m"          # candle timeframe
EXPIRY_MINUTES = int(os.getenv("EXPIRY_MINUTES", "1"))   # trade expiry
MIN_SCORE = int(os.getenv("MIN_SCORE", "4"))   # minimum confluence score; higher = fewer but stricter signals
COOLDOWN_MINUTES = 5     # no repeat signal on the same coin within this many minutes

STATS_FILE = os.getenv("STATS_FILE", os.path.join(os.path.dirname(__file__), "stats.json"))
