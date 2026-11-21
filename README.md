# Telegram Live Signal Bot (1-Minute Expiry)

Live Binance market data → Support/Resistance + indicator strategy → signal on Telegram → WIN/LOSS result after expiry → live accuracy tracking.

## Setup
1. On Telegram, message @BotFather and send `/newbot` → copy the token.
2. Install:
   pip install -r requirements.txt
3. Run:
   export TELEGRAM_BOT_TOKEN="your_token"
   python bot.py
4. Send `/start` to your bot on Telegram.

## Commands
/start – start receiving signals · /stop – stop · /stats – win/loss/accuracy · /scan – check right now · /coins – list of coins

## Pairs
Forex: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, EURJPY, XAUUSD (gold), via Yahoo Finance (no key needed)
Crypto: BTCUSDT, ETHUSDT ..., via Binance
Optional: a free key from twelvedata.com → TWELVEDATA_API_KEY (more reliable forex data; free plan allows 8 requests/min, so use at most ~1-2 pairs)
Note: the forex market is closed from Friday night to Monday morning, and the bot automatically sends no forex signals then.

## Settings (env vars, see .env.example)
SYMBOLS=EURUSD,BTCUSDT   EXPIRY_MINUTES=1   MIN_SCORE=4  (higher = fewer, stricter signals)

## Your own strategy
Edit the `analyze()` function in `strategy.py`: add conditions and change the scores.

## Check accuracy (backtest) — do this first!
python backtest.py BTCUSDT 5000
This shows the real accuracy on past data. Only trust the strategy if it holds up there.

## 24/7 Deployment
### Option A: VPS + Docker (recommended, ~₹400-500/month)
    cp .env.example .env      # put your token in it
    docker compose up -d --build
    docker compose logs -f    # view logs
### Option B: VPS without Docker
    sudo mkdir -p /opt/signal_bot && sudo cp -r . /opt/signal_bot && cd /opt/signal_bot
    pip install -r requirements.txt && cp .env.example .env   # add your token
    sudo cp signal-bot.service /etc/systemd/system/
    sudo systemctl enable --now signal-bot
### Option C: Render.com
Push the code to GitHub → Render → New Blueprint → select the repo (render.yaml is included) → put TELEGRAM_BOT_TOKEN in the dashboard.
