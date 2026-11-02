#!/usr/bin/env python3
"""Render "This Day in WWII History" Instagram posts.

Each day of the year lives in calendar/MM-DD.json. For a given date this script:
  1. looks the photo up on Wikimedia Commons and refuses it unless Commons marks it public domain,
  2. frames it on a 1080x1350 (4:5) card with the date and a caption on the border,
  3. writes the Instagram caption (story + credit + 5 hashtags) next to the image.

  python3 make_post.py                       # today's post
  python3 make_post.py --date 2026-11-08     # one day
  python3 make_post.py --from 2026-11-02 --days 14
  python3 make_post.py --avatar              # profile picture
Output lands in posts/YYYY-MM-DD/ (post.jpg, caption.txt, source.json).
"""
import argparse
import datetime as dt
import json
import os
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

import commons

ROOT = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 1350
SAFE_W = 900  # text width; Instagram's 3:4 grid crop trims ~34px from each side of a 4:5 post

SUP = "/System/Library/Fonts/Supplemental/"
FONTS = {
    "label": (SUP + "Futura.ttc", 2),        # Futura Bold
    "small": (SUP + "Futura.ttc", 0),        # Futura Medium
    "date": (SUP + "Baskerville.ttc", 4),    # Baskerville SemiBold
    "caption": (SUP + "Baskerville.ttc", 0), # Baskerville Regular
    "big": (SUP + "Futura.ttc", 4),          # Futura Condensed ExtraBold (avatar)
}

STYLES = {
    # Archival print on a dark museum wall.
    "dark": dict(bg="#15130f", grain=10, rule="#b8954d", accent="#c9a65a", date="#f1ead9",
                 caption="#e6dfcd", muted="#8f8673", mat="#e9e1cc"),
    # Cream scrapbook page with oxblood accents.
    "paper": dict(bg="#ebe2cd", grain=14, rule="#7d2a22", accent="#7d2a22", date="#1d1a15",
                  caption="#26221b", muted="#6f6656", mat="#fbf7ee"),
}


def font(kind, size):
    path, index = FONTS[kind]
    return ImageFont.truetype(path, size, index=index)


def load_config():
    path = os.path.join(ROOT, "config.json")
    return json.load(open(path)) if os.path.exists(path) else {}


# ---------- drawing helpers ----------

def tracked_width(text, f, tracking):
    return sum(f.getlength(c) for c in text) + tracking * (len(text) - 1)


def draw_tracked(draw, cx, y, text, f, fill, tracking):
    """Draw letter-spaced text centred on cx with its top at y."""
    x = cx - tracked_width(text, f, tracking) / 2
    for c in text:
        draw.text((x, y), c, font=f, fill=fill)
        x += f.getlength(c) + tracking


def star(draw, cx, cy, r, fill):
    import math
    pts = []
    for i in range(10):
        rad = r if i % 2 == 0 else r * 0.42
        a = math.pi / 2 + i * math.pi / 5
        pts.append((cx + rad * math.cos(a), cy - rad * math.sin(a)))
    draw.polygon(pts, fill=fill)


def wrap(text, f, width):
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if f.getlength(trial) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = w
    return lines + [line] if line else lines


def balanced_wrap(text, f, width):
    """Wrap into the fewest lines, then even out line lengths so the last line isn't a stub."""
    n = len(wrap(text, f, width))
    lo, hi = int(width * 0.5), width
    while lo < hi:
        mid = (lo + hi) // 2
        if len(wrap(text, f, mid)) <= n:
            hi = mid
        else:
            lo = mid + 1
    return wrap(text, f, lo)


def grain(size, amount):
    """Grey film-grain texture centred on mid-grey; `amount` sets its strength."""
    noise = Image.effect_noise(size, 64).convert("L")
    return noise.point(lambda v: 128 + (v - 128) * amount // 64)


# ---------- photo handling ----------

def prepare_photo(entry, info):
    cache = os.path.join(ROOT, "cache", re.sub(r"[^\w.-]+", "_", info["title"][5:])[:120] + ".jpg")
    commons.download(info, cache)
    im = Image.open(cache)
    im = ImageOps.exif_transpose(im).convert("RGB")
    l, t, r, b = entry["image"].get("crop", [0, 0, 0, 0])
    w, h = im.size
    im = im.crop((round(w * l), round(h * t), round(w * (1 - r)), round(h * (1 - b))))
    if entry["image"].get("tone", "auto") == "auto":
        sat = sum(im.convert("HSV").getchannel("S").resize((64, 64)).getdata()) / 4096 / 255
        if sat < 0.2:  # black-and-white or faded sepia print: neutral grey, gentle contrast
            im = ImageOps.autocontrast(im.convert("L"), cutoff=0.4).convert("RGB")
    return im


def fit(im, max_w, max_h):
    scale = min(max_w / im.width, max_h / im.height)
    size = (round(im.width * scale), round(im.height * scale))
    out = im.resize(size, Image.LANCZOS)
    return out.filter(ImageFilter.UnsharpMask(radius=1.0, percent=45, threshold=2))


# ---------- the card ----------

def render(entry, post_date, info, style_name="dark", handle=""):
    s = STYLES[style_name]
    card = Image.new("RGB", (W, H), s["bg"])
    noise = Image.merge("RGB", [grain((W, H), s["grain"])] * 3)
    card = Image.blend(card, noise, 0.035)
    d = ImageDraw.Draw(card)

    # double keyline around the whole card
    d.rectangle((26, 26, W - 27, H - 27), outline=s["rule"], width=2)
    d.rectangle((34, 34, W - 35, H - 35), outline=s["rule"], width=1)

    # header: series label, date, "N years ago"
    label = font("label", 25)
    y = 72
    draw_tracked(d, W / 2, y, "THIS DAY IN WWII HISTORY", label, s["accent"], 6.5)
    lw = tracked_width("THIS DAY IN WWII HISTORY", label, 6.5)
    for side in (-1, 1):
        star(d, W / 2 + side * (lw / 2 + 30), y + 13, 9, s["accent"])

    event_date = dt.date(entry["year"], post_date.month, post_date.day)
    date_text = event_date.strftime("%B ") + str(event_date.day) + event_date.strftime(", %Y")
    df = font("date", 74)
    d.text((W / 2, 126), date_text.upper(), font=df, fill=s["date"], anchor="mt")

    years = post_date.year - entry["year"]
    sub = f"{years} YEARS AGO TODAY"
    sf = font("small", 19)
    sw = tracked_width(sub, sf, 5)
    sy = 224
    draw_tracked(d, W / 2, sy, sub, sf, s["muted"], 5)
    for side in (-1, 1):
        x0 = W / 2 + side * (sw / 2 + 22)
        d.line((x0, sy + 11, x0 + side * 150, sy + 11), fill=s["rule"], width=1)
    header_bottom = sy + 34

    # footer credit (fixed at the bottom of the frame)
    credit = f"PHOTO: {entry['image']['credit'].upper()}  ·  PUBLIC DOMAIN"
    if handle:
        credit += f"  ·  @{handle.lstrip('@').upper()}"
    cf, track = font("small", 16), 3.2
    while tracked_width(credit, cf, track) > SAFE_W and track > 1:
        track -= 0.4
    footer_y = H - 78
    draw_tracked(d, W / 2, footer_y, credit, cf, s["muted"], track)

    # caption on the border: largest size that fits in three balanced lines
    for size in range(36, 25, -1):
        cap_font = font("caption", size)
        lines = balanced_wrap(entry["border_caption"], cap_font, SAFE_W)
        if len(lines) <= 3:
            break
    line_h = round(size * 1.32)
    cap_h = line_h * len(lines)

    # photo: as large as the space between header and caption allows, on a cream "print" mat
    mat = 12
    gap = 34
    avail_h = (footer_y - 30) - header_bottom - cap_h - 3 * gap
    photo = fit(prepare_photo(entry, info), 960 - 2 * mat, avail_h - 2 * mat)
    block_h = photo.height + 2 * mat + gap + cap_h
    top = header_bottom + ((footer_y - 30) - header_bottom - block_h) // 2
    px = (W - photo.width) // 2
    d.rectangle((px - mat, top, px + photo.width + mat - 1, top + photo.height + 2 * mat - 1), fill=s["mat"])
    card.paste(photo, (px, top + mat))
    d.rectangle((px - mat, top, px + photo.width + mat - 1, top + photo.height + 2 * mat - 1), outline=s["rule"], width=1)

    cy = top + photo.height + 2 * mat + gap
    for i, line in enumerate(lines):
        d.text((W / 2, cy + i * line_h), line, font=cap_font, fill=s["caption"], anchor="mt")
    return card


def instagram_caption(entry):
    parts = [entry["hook"], *entry["body"]]
    if entry.get("closer"):
        parts.append(entry["closer"])
    parts.append(f"📷 {entry['image']['note']} Photo: {entry['image']['credit']} (public domain, via Wikimedia Commons).")
    parts.append(" ".join(entry["hashtags"]))
    return "\n\n".join(parts) + "\n"


def make_post(post_date, style=None):
    cfg = load_config()
    key = post_date.strftime("%m-%d")
    path = os.path.join(ROOT, "calendar", f"{key}.json")
    if not os.path.exists(path):
        raise SystemExit(f"No calendar entry for {key} ({path}). Add one, then re-run.")
    entry = json.load(open(path, encoding="utf-8"))
    assert len(entry["hashtags"]) == 5, f"{key}: need exactly 5 hashtags"

    info = commons.file_info(entry["image"]["file"])
    if not commons.is_public_domain(info):
        raise SystemExit(f"{key}: {info['title']} is not marked public domain on Commons ({info['license']}). Pick another photo.")

    out = os.path.join(ROOT, "posts", post_date.isoformat())
    os.makedirs(out, exist_ok=True)
    card = render(entry, post_date, info, style or cfg.get("style", "dark"), cfg.get("handle", ""))
    card.save(os.path.join(out, "post.jpg"), quality=95, subsampling=0)
    caption = instagram_caption(entry)
    with open(os.path.join(out, "caption.txt"), "w", encoding="utf-8") as f:
        f.write(caption)
    keep = ("title", "page", "license", "artist", "credit", "date", "description")
    json.dump({k: info[k] for k in keep}, open(os.path.join(out, "source.json"), "w"), indent=2, ensure_ascii=False)
    print(f"{post_date}  {entry['headline']}  ->  posts/{post_date.isoformat()}/  ({len(caption)} chars, {info['license']})")
    return out


def make_avatar(style="dark"):
    s = STYLES[style]
    size = 1080
    im = Image.new("RGB", (size, size), s["bg"])
    im = Image.blend(im, Image.merge("RGB", [grain((size, size), s["grain"])] * 3), 0.035)
    d = ImageDraw.Draw(im)
    c = size / 2
    for r, w in ((470, 6), (446, 2)):
        d.ellipse((c - r, c - r, c + r, c + r), outline=s["rule"], width=w)
    top = font("label", 58)
    draw_tracked(d, c, 250, "THIS DAY IN", top, s["accent"], 10)
    d.text((c, 548), "WWII", font=font("big", 330), fill=s["date"], anchor="mm")
    draw_tracked(d, c, 735, "HISTORY", top, s["accent"], 18)
    for dx in (-150, 0, 150):
        star(d, c + dx, 850, 22, s["accent"])
    out = os.path.join(ROOT, "profile", "avatar.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    im.save(out)
    print(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--from", dest="start", help="first date of a batch, YYYY-MM-DD")
    ap.add_argument("--days", type=int, default=1, help="number of days in the batch")
    ap.add_argument("--style", choices=sorted(STYLES), help="override config.json style")
    ap.add_argument("--avatar", action="store_true", help="render the profile picture")
    a = ap.parse_args()
    if a.avatar:
        make_avatar(a.style or load_config().get("style", "dark"))
    else:
        first = dt.date.fromisoformat(a.start or a.date or dt.date.today().isoformat())
        for i in range(a.days):
            make_post(first + dt.timedelta(days=i), a.style)
