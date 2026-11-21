"""Professional trade result card: header, info cards, candle chart with entry/exit, result badge.
Pure Pillow (no matplotlib). Drawn at 2x and downscaled for smooth edges."""
import io
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
S = 2  # supersampling factor

# colours
BG_TOP, BG_BOT = (11, 15, 25), (20, 26, 42)
PANEL, PANEL_EDGE = (24, 31, 48), (40, 50, 74)
GRID, MUTED, TEXT = (38, 47, 68), (130, 142, 168), (232, 236, 245)
GREEN, GREEN_DK = (0, 200, 140), (0, 120, 86)
RED, RED_DK = (255, 77, 94), (150, 36, 48)
BLUE, GOLD = (77, 148, 255), (255, 196, 61)

_FONT_CACHE = {}


def _font(size, bold=False):
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    from PIL import ImageFont
    names = (["DejaVuSans-Bold.ttf", "/system/fonts/Roboto-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"]
             if bold else [])
    names += ["DejaVuSans.ttf", "/system/fonts/Roboto-Regular.ttf", "/system/fonts/DroidSans.ttf",
              "Arial.ttf", "arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    f = None
    for n in names:
        try:
            f = ImageFont.truetype(n, size * S)
            break
        except Exception:
            continue
    if f is None:
        try:
            f = ImageFont.load_default(size=size * S)
        except Exception:
            f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


def _pip(pair):
    return 0.01 if "JPY" in pair else (0.1 if "XAU" in pair else 0.0001)


def trade_chart(pair, direction, df, start_ms, entry, exit_price, result, expiry_min=1):
    """Return PNG bytes of the result card, or None if Pillow is unavailable."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    end_ms = start_ms + expiry_min * 60_000
    d = df[df["close_time"] <= end_ms - 1].tail(36).reset_index(drop=True)
    if d.empty:
        return None

    W, H = 1280, 740
    img = Image.new("RGB", (W * S, H * S), BG_TOP)
    dr = ImageDraw.Draw(img)
    s = lambda v: v * S  # noqa: E731

    # background gradient
    for yy in range(H * S):
        t = yy / (H * S)
        c = tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3))
        dr.line([(0, yy), (W * S, yy)], fill=c)

    up = direction == "CALL"
    side_col = GREEN if up else RED
    res_col = {"win": GREEN, "loss": RED, "draw": MUTED}[result]
    fmt = (lambda p: f"{p:.3f}") if max(entry, exit_price) > 20 else (lambda p: f"{p:.5f}")
    st = datetime.fromtimestamp(start_ms / 1000, timezone.utc).astimezone(IST)
    en = datetime.fromtimestamp(end_ms / 1000, timezone.utc).astimezone(IST)

    # ---------- header ----------
    base, otc = (pair.replace(" OTC", ""), " OTC" in pair)
    dr.text((s(40), s(34)), base, fill=TEXT, font=_font(44, True))
    x0 = 40 + dr.textlength(base, font=_font(44, True)) / S + 16
    if otc:
        dr.rounded_rectangle([s(x0), s(44), s(x0 + 62), s(76)], radius=s(8), fill=(52, 63, 92))
        dr.text((s(x0 + 31), s(60)), "OTC", fill=GOLD, font=_font(18, True), anchor="mm")
        x0 += 74
    lbl = ("BUY  ▲" if up else "SELL  ▼")
    bw = dr.textlength(lbl, font=_font(22, True)) / S + 32
    dr.rounded_rectangle([s(x0), s(42), s(x0 + bw), s(78)], radius=s(18), fill=side_col)
    dr.text((s(x0 + bw / 2), s(60)), lbl, fill=(10, 14, 22), font=_font(22, True), anchor="mm")
    dr.text((s(40), s(92)), f"{st:%I:%M} - {en:%I:%M %p} IST  •  {expiry_min} Min Expiry  •  {st:%d %b %Y}",
            fill=MUTED, font=_font(18))

    # result badge (top right)
    rx1, ry0, rx0, ry1 = W - 40, 30, W - 300, 118
    dr.rounded_rectangle([s(rx0), s(ry0), s(rx1), s(ry1)], radius=s(18), fill=res_col)
    dr.rounded_rectangle([s(rx0 + 4), s(ry0 + 4), s(rx1 - 4), s(ry1 - 4)], radius=s(15),
                         outline=(255, 255, 255), width=s(2))
    word = {"win": "WIN", "loss": "LOSS", "draw": "DRAW"}[result]
    sym = {"win": "✔", "loss": "✖", "draw": "="}[result]
    dr.text((s((rx0 + rx1) / 2), s(68)), f"{sym} {word}", fill=(255, 255, 255),
            font=_font(46, True), anchor="mm")

    # ---------- chart panel: clean candles only (broker-app style), nothing drawn on top ----------
    CUP, CDN = (54, 192, 12), (216, 72, 56)       # bright green / red like the trading app
    CHART_BG = (33, 38, 52)
    d = d.tail(18).reset_index(drop=True)          # fewer candles -> bigger, clearer candles
    px0, py0, px1, py1 = 40, 140, W - 40, H - 40
    dr.rounded_rectangle([s(px0), s(py0), s(px1), s(py1)], radius=s(16), fill=CHART_BG)
    L, R, T, B = px0 + 16, px1 - 120, py0 + 30, py1 - 52
    lo, hi = d["low"].min(), d["high"].max()
    pad = (hi - lo) * 0.10 or hi * 0.0005
    lo, hi = lo - pad, hi + pad
    Y = lambda p: T + (hi - p) / (hi - lo) * (B - T)  # noqa: E731
    n = len(d)
    step = (R - L) / n
    X = lambda i: L + step * i + step / 2  # noqa: E731

    for k in range(4):  # price scale on the right, no grid lines over the candles
        p = lo + (hi - lo) * (k + 0.5) / 4
        dr.text((s(R + 18), s(Y(p))), fmt(p), fill=(214, 220, 232), font=_font(17), anchor="lm")

    bwid = step * 0.74
    for i, c in d.iterrows():
        o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
        col = CUP if cl >= o else CDN
        dr.line([(s(X(i)), s(Y(h))), (s(X(i)), s(Y(l)))], fill=col, width=s(2))
        top, bot = Y(max(o, cl)), Y(min(o, cl))
        if bot - top < 3:
            mid = (top + bot) / 2
            top, bot = mid - 1.5, mid + 1.5
        dr.rectangle([s(X(i) - bwid / 2), s(top), s(X(i) + bwid / 2), s(bot)], fill=col)
        if i % 4 == 1:
            t = datetime.fromtimestamp((int(c["close_time"]) + 1) / 1000 - 60, timezone.utc).astimezone(IST)
            dr.text((s(X(i)), s(B + 30)), t.strftime("%H:%M"), fill=(214, 220, 232), font=_font(17), anchor="mm")

    last = d.iloc[-1]  # current price pill on the scale (outside the candles)
    yl = Y(last["close"])
    dr.rounded_rectangle([s(R + 8), s(yl - 17), s(px1 - 8), s(yl + 17)], radius=s(17), fill=(33, 150, 243))
    dr.text((s((R + 8 + px1 - 8) / 2), s(yl)), fmt(last["close"]), fill=(255, 255, 255),
            font=_font(16, True), anchor="mm")

    out = img.resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
