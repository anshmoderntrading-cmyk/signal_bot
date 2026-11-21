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

    W, H = 1280, 760
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
    dr.text((s(40), s(92)), f"{st:%d %b %Y}  •  {expiry_min} Min Expiry  •  IST",
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

    # ---------- info cards ----------
    move = (exit_price - entry) / _pip(pair)
    cards = [("ENTRY", fmt(entry), BLUE), ("EXIT", fmt(exit_price), TEXT),
             ("MOVE", f"{move:+.1f} pips", res_col),
             ("TIME", f"{st:%I:%M} → {en:%I:%M %p}", TEXT)]
    cx, cy, cw, ch, gap = 40, 140, (W - 80 - 3 * 16) / 4, 86, 16
    for i, (k, v, col) in enumerate(cards):
        x = cx + i * (cw + gap)
        dr.rounded_rectangle([s(x), s(cy), s(x + cw), s(cy + ch)], radius=s(14), fill=PANEL,
                             outline=PANEL_EDGE, width=s(1))
        dr.text((s(x + 20), s(cy + 16)), k, fill=MUTED, font=_font(16, True))
        fs = 28
        while fs > 16 and dr.textlength(v, font=_font(fs, True)) / S > cw - 36:
            fs -= 2
        dr.text((s(x + 20), s(cy + 42)), v, fill=col, font=_font(fs, True))

    # ---------- chart panel ----------
    px0, py0, px1, py1 = 40, 248, W - 40, H - 64
    dr.rounded_rectangle([s(px0), s(py0), s(px1), s(py1)], radius=s(18), fill=PANEL,
                         outline=PANEL_EDGE, width=s(1))
    L, R, T, B = px0 + 20, px1 - 170, py0 + 24, py1 - 44
    lo = min(d["low"].min(), entry, exit_price)
    hi = max(d["high"].max(), entry, exit_price)
    pad = (hi - lo) * 0.10 or hi * 0.0005
    lo, hi = lo - pad, hi + pad
    Y = lambda p: T + (hi - p) / (hi - lo) * (B - T)  # noqa: E731
    n = len(d)
    step = (R - L) / n
    X = lambda i: L + step * i + step / 2  # noqa: E731

    for k in range(6):
        p = lo + (hi - lo) * k / 5
        dr.line([(s(L), s(Y(p))), (s(R), s(Y(p)))], fill=GRID, width=s(1))
        dr.text((s(R + 14), s(Y(p))), fmt(p), fill=MUTED, font=_font(15), anchor="lm")

    trade_i = None
    for i, c in d.iterrows():
        if start_ms <= int(c["close_time"]) < end_ms:
            trade_i = i
    if trade_i is not None:  # trade zone
        zx0, zx1 = X(trade_i) - step / 2, X(trade_i) + step / 2
        zone = Image.new("RGBA", (int(s(zx1 - zx0)), int(s(B - T))), side_col + (40,))
        img.paste(zone, (int(s(zx0)), int(s(T))), zone)
        dr.line([(s(zx0), s(T)), (s(zx0), s(B))], fill=side_col, width=s(2))
        dr.line([(s(zx1), s(T)), (s(zx1), s(B))], fill=side_col, width=s(2))

    for i, c in d.iterrows():
        o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
        col = GREEN if cl >= o else RED
        dr.line([(s(X(i)), s(Y(h))), (s(X(i)), s(Y(l)))], fill=col, width=s(2))
        top, bot = Y(max(o, cl)), Y(min(o, cl))
        bwid = max(step * 0.62, 3)
        dr.rounded_rectangle([s(X(i) - bwid / 2), s(top), s(X(i) + bwid / 2), s(max(bot, top + 1.5))],
                             radius=s(2), fill=col)
        if i % 6 == 0:
            t = datetime.fromtimestamp((int(c["close_time"]) + 1) / 1000 - 60, timezone.utc).astimezone(IST)
            dr.text((s(X(i)), s(B + 22)), t.strftime("%H:%M"), fill=MUTED, font=_font(15), anchor="mm")

    # entry line + tag
    ye, yx = Y(entry), Y(exit_price)
    xx = L
    while xx < R:
        dr.line([(s(xx), s(ye)), (s(min(xx + 10, R)), s(ye))], fill=BLUE, width=s(2))
        xx += 18

    def tag(yv, text, col, fg=(10, 14, 22)):
        dr.rounded_rectangle([s(R + 6), s(yv - 15), s(px1 - 10), s(yv + 15)], radius=s(7), fill=col)
        dr.text((s((R + 6 + px1 - 10) / 2), s(yv)), text, fill=fg, font=_font(15, True), anchor="mm")

    ty_e, ty_x = ye, yx
    if abs(ty_x - ty_e) < 34:  # keep the two tags apart
        if ty_x >= ty_e:
            ty_x = ty_e + 34
        else:
            ty_x = ty_e - 34
    tag(ty_e, f"ENTRY {fmt(entry)}", BLUE, (255, 255, 255))
    tag(ty_x, f"EXIT {fmt(exit_price)}", res_col, (255, 255, 255) if result != "win" else (10, 14, 22))

    if trade_i is not None:
        xe, xx_ = X(trade_i) - step / 2, X(trade_i) + step / 2
        dr.line([(s(xe), s(ye)), (s(xx_), s(yx))], fill=(255, 255, 255), width=s(3))
        r = 8
        dr.ellipse([s(xe - r), s(ye - r), s(xe + r), s(ye + r)], fill=BLUE, outline=(255, 255, 255), width=s(2))
        dr.ellipse([s(xx_ - r), s(yx - r), s(xx_ + r), s(yx + r)], fill=res_col, outline=(255, 255, 255), width=s(2))
        # exit line from the exit dot to its tag
        dr.line([(s(xx_ + r), s(yx)), (s(R + 6), s(ty_x))], fill=res_col, width=s(2))

    # ---------- footer ----------
    dr.text((s(40), s(H - 32)), "Auto signal • Support/Resistance + RSI + Bollinger + EMA",
            fill=MUTED, font=_font(16), anchor="lm")
    dr.text((s(W - 40), s(H - 32)), "Not financial advice", fill=MUTED, font=_font(16), anchor="rm")

    out = img.resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
