"""
Backtest: test the strategy on past data and check its REAL accuracy.
Usage:  python backtest.py BTCUSDT 5000   |   python backtest.py EURUSD 5000
Rule: signal on candle close -> entry = that close, result = close after EXPIRY candles.
"""
import sys
from strategy import analyze
from data import fetch_history
import config


def run(df, expiry=1, min_score=4, window=200):
    wins = losses = draws = 0
    i = window
    while i < len(df) - expiry:
        sig = analyze(df.iloc[i - window:i + 1], min_score)
        if sig:
            entry, exit_ = df["close"].iloc[i], df["close"].iloc[i + expiry]
            if exit_ == entry:
                draws += 1
            elif (exit_ > entry) == (sig["direction"] == "CALL"):
                wins += 1
            else:
                losses += 1
            i += expiry  # no overlapping trades
        i += 1
    total = wins + losses
    return wins, losses, draws, (100 * wins / total if total else 0.0)


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    df = fetch_history(sym, n)
    print(f"{sym}: {len(df)} candles")
    for ms in (3, 4, 5, 6):
        w, l, d, acc = run(df, config.EXPIRY_MINUTES, ms)
        print(f"MIN_SCORE={ms}: trades={w + l}  win={w}  loss={l}  draw={d}  accuracy={acc:.1f}%")
