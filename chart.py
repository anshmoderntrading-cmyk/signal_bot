"""Trade result image: candles + entry/exit + WIN/LOSS (Pillow, no matplotlib)."""
import io
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


def _font(size):
    from PIL import ImageFont
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf",
                 "/system/fonts/Roboto-Regular.ttf", "/system/fonts/DroidSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def trade_chart(pair, direction, df, start_ms, entry, exit_price, result, expiry_min=1):
    """Return PNG bytes, or None if Pillow is not installed."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    end_ms = start_ms + expiry_min * 60_000
    d = df[df["close_time"] <= end_ms - 1].tail(30)
    if d.empty:
        return None

    W, H = 1000, 600
    L, R, T, B = 20, 110, 90, 70  # margins (right side = price scale)
    bg, grid, txt = (19, 23, 34), (40, 46, 60), (220, 224, 232)
    green, red, blue = (38, 166, 154), (239, 83, 80), (66, 135, 245)
    img = Image.new("RGB", (W, H), bg)
    dr = ImageDraw.Draw(img)
    f_big, f_mid, f_small = _font(34), _font(22), _font(16)

    lo = min(d["low"].min(), entry, exit_price)
    hi = max(d["high"].max(), entry, exit_price)
    pad = (hi - lo) * 0.12 or hi * 0.0005
    lo, hi = lo - pad, hi + pad
    y = lambda p: T + (hi - p) / (hi - lo) * (H - T - B)
    n = len(d)
    cw = (W - L - R) / n
    x = lambda i: L + cw * i + cw / 2
    fmt = (lambda p: f"{p:.3f}") if hi > 20 else (lambda p: f"{p:.5f}")

    for k in range(6):  # grid + price scale
        p = lo + (hi - lo) * k / 5
        dr.line([(L, y(p)), (W - R, y(p))], fill=grid)
        dr.text((W - R + 8, y(p) - 9), fmt(p), fill=txt, font=f_small)

    trade_i = None
    for i, (_, c) in enumerate(d.iterrows()):
        ct = int(c["close_time"])
        if start_ms <= ct < end_ms:
            trade_i = i
            dr.rectangle([x(i) - cw / 2, T, x(i) + cw / 2, H - B], fill=(35, 42, 62))
        col = green if c["close"] >= c["open"] else red
        dr.line([(x(i), y(c["high"])), (x(i), y(c["low"]))], fill=col, width=2)
        top, bot = y(max(c["open"], c["close"])), y(min(c["open"], c["close"]))
        dr.rectangle([x(i) - cw * 0.35, top, x(i) + cw * 0.35, max(bot, top + 1)], fill=col)
        if i % 5 == 0:
            t = datetime.fromtimestamp((ct + 1) / 1000 - 60, timezone.utc).astimezone(IST)
            dr.text((x(i) - 20, H - B + 10), t.strftime("%H:%M"), fill=txt, font=f_small)

    # entry line + arrow, exit marker
    ye, yx = y(entry), y(exit_price)
    for xx in range(L, W - R, 14):
        dr.line([(xx, ye), (xx + 7, ye)], fill=blue, width=2)
    dr.text((W - R + 8, ye - 9), fmt(entry), fill=blue, font=f_small)
    if trade_i is not None:
        xe = x(trade_i) - cw / 2
        up = direction == "CALL"
        col = green if up else red
        tri = [(xe, ye + (14 if up else -14)), (xe - 12, ye + (34 if up else -34)), (xe + 12, ye + (34 if up else -34))]
        dr.polygon(tri, fill=col)
        xx = x(trade_i) + cw / 2
        dr.ellipse([xx - 7, yx - 7, xx + 7, yx + 7], fill=(255, 255, 255))
        dr.line([(xe, ye), (xx, yx)], fill=(255, 255, 255), width=2)

    # header
    side = "BUY" if direction == "CALL" else "SELL"
    st = datetime.fromtimestamp(start_ms / 1000, timezone.utc).astimezone(IST)
    en = datetime.fromtimestamp(end_ms / 1000, timezone.utc).astimezone(IST)
    dr.text((L, 18), f"{pair}  {side}", fill=green if side == "BUY" else red, font=f_big)
    dr.text((L, 58), f"{st:%I:%M %p} - {en:%I:%M %p}   Entry {fmt(entry)} -> Exit {fmt(exit_price)}",
            fill=txt, font=f_small)
    label = {"win": "WIN", "loss": "LOSS", "draw": "DRAW"}[result]
    lc = {"win": green, "loss": red, "draw": (150, 150, 150)}[result]
    dr.rounded_rectangle([W - 230, 18, W - 20, 72], radius=10, fill=lc)
    dr.text((W - 125, 45), label, fill=(255, 255, 255), font=f_big, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
