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

## Buttons
🟢 Signal ON → an automatic signal every 2 minutes (SIGNAL_EVERY_MINUTES)
🔴 Signal STOP → signals stop
Format:
  AUD/JPY LIVE 🟢 BUY
  ⏱️ 1 Min
  🕒 03:24 PM – 03:25 PM
After expiry, a short ✅ WIN / ❌ LOSS reply (turn off with SEND_RESULTS=0). Forex pairs only.

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
### Option C: Render.com (FREE plan)
Push the code to GitHub → Render → New Blueprint → select the repo (render.yaml is included) → put TELEGRAM_BOT_TOKEN in the dashboard.
A free web service sleeps after 15 minutes without traffic. To stop that, go to cron-job.org or uptimerobot.com
and set up a monitor that pings your Render URL (https://<name>.onrender.com) every 5 minutes.
Limits of the free plan: a restart/redeploy resets stats.json (Live Stats); the 750 free hours/month are enough for 1 service.

## Quotex OTC signals (run on a laptop)
⚠️ Uses an unofficial library (pyquotex): it can break whenever Quotex changes, and Quotex may block your account. Use a demo or small account.
1. Install Python 3.12+ (python.org; on Windows tick "Add to PATH") and Git (git-scm.com).
2. In @BotFather, make a **new bot** for OTC (two programs can't run on the Render bot's token at once).
3. Download this repo (GitHub → Code → Download ZIP) and extract it.
4. Windows: double-click `run_otc.bat` → .env opens in Notepad → fill in the token, Quotex email, password → save → run `run_otc.bat` again.
   Mac/Linux: `./run_otc.sh`
5. On first login Quotex may send a code to your email: type it into the black window.
6. Press 🟢 Signal ON on Telegram → "EUR/USD OTC LIVE 🟢 BUY" signals every 2 minutes.
The bot runs only while the laptop is on and the window is open.

## Find a strategy from real data (research)
    python research.py          # OTC pairs (stop the bot first: both use the same Quotex login)
    python research.py live     # live pairs, Mon-Fri
Tests many rules x expiries on ~2 days of candles, with a train/test split and a luck (significance) check.
Rules that pass are saved to best_rules.json. To use them:
    sed -i 's/^STRATEGY=.*//' .env; echo 'STRATEGY=auto' >> .env
If NOTHING passes, the data shows no reliable edge - the honest answer is: don't trade it with real money.
