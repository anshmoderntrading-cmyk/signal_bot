"""Honest record from results.csv:  python stats.py"""
import csv
import os
import sys

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.csv")
if not os.path.exists(path):
    sys.exit("No results yet (results.csv not found).")
rows = [r for r in csv.DictReader(open(path)) if r["result"] in ("win", "loss")]
if not rows:
    sys.exit("No finished trades yet.")


def line(name, rs):
    w = sum(r["result"] == "win" for r in rs)
    n = len(rs)
    acc = 100 * w / n
    z = (acc / 100 - 0.5) / (0.25 / n) ** 0.5
    print(f"{name:28s} {n:5d} trades  {w:4d} W  {n - w:4d} L  {acc:5.1f}%   z={z:4.1f}")


print("=== OVERALL ===")
line("all trades", rows)
print("\n=== BY RULE / STRATEGY ===")
for key in sorted({(r["strategy"], r["rule"], r["expiry_min"]) for r in rows}):
    line(f"{key[0]} {key[1]} {key[2]}m".strip(), [r for r in rows if (r["strategy"], r["rule"], r["expiry_min"]) == key])
print("\n=== BY PAIR ===")
for p in sorted({r["pair"] for r in rows}):
    line(p, [r for r in rows if r["pair"] == p])
print("\n=== BY DAY ===")
for d in sorted({r["time_ist"][:10] for r in rows}):
    line(d, [r for r in rows if r["time_ist"].startswith(d)])
n = len(rows)
print(f"\nBreak-even at 85% payout = 54.1%.  "
      f"{'Too few trades to judge (need 100+).' if n < 100 else 'z >= 2 over 100+ trades = real evidence.'}")
