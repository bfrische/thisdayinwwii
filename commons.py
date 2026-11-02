#!/usr/bin/env python3
"""Wikimedia Commons helpers: find WWII photos, confirm they are public domain, download them.

  python3 commons.py search "Operation Torch landing"      # ranked candidates with license
  python3 commons.py info "File:Some photo.jpg"             # full license/credit details
  python3 commons.py sheet out.jpg "File:A.jpg" "File:B.jpg" # numbered contact sheet to eyeball
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://commons.wikimedia.org/w/api.php"
UA = "ThisDayInWWIIHistory/1.0 (personal Instagram post generator)"
PHOTO_MIMES = {"image/jpeg", "image/png", "image/tiff", "image/webp"}


def _get(url, tries=6):
    """GET with Wikimedia-friendly pacing: back off and retry when rate-limited (HTTP 429/503)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == tries - 1:
                raise
            wait = int(e.headers.get("Retry-After") or 0) or 5 * 2 ** attempt
            time.sleep(min(wait, 60))


def api(**params):
    params.update(format="json", formatversion="2")
    return json.loads(_get(API + "?" + urllib.parse.urlencode(params)))


def _text(md, key):
    raw = md.get(key, {}).get("value", "")
    return html.unescape(re.sub(r"<[^>]+>", "", str(raw))).strip()


def _parse(page):
    ii = page["imageinfo"][0]
    md = ii.get("extmetadata", {})
    return {
        "title": page["title"],
        "width": ii["width"],
        "height": ii["height"],
        "mime": ii["mime"],
        "url": ii["url"],
        "thumburl": ii.get("thumburl", ii["url"]),
        "page": ii["descriptionurl"],
        "license": _text(md, "LicenseShortName"),
        "license_code": _text(md, "License"),
        "copyrighted": _text(md, "Copyrighted"),
        "artist": _text(md, "Artist"),
        "credit": _text(md, "Credit"),
        "description": _text(md, "ImageDescription"),
        "date": _text(md, "DateTimeOriginal"),
        "categories": _text(md, "Categories"),
    }


def normalize(title):
    title = title.replace("_", " ").strip()
    return title if title.startswith("File:") else "File:" + title


def is_public_domain(info):
    """True only when Commons itself marks the file as public domain (or a CC0 dedication)."""
    lic = info["license"].lower()
    code = info["license_code"].lower()
    return info["copyrighted"] == "False" or lic.startswith("public domain") or code == "cc0" or code.startswith("pd")


def file_info(title, width=1920):
    data = api(action="query", titles=normalize(title), prop="imageinfo",
               iiprop="url|size|mime|extmetadata", iiurlwidth=width)
    page = data["query"]["pages"][0]
    if "imageinfo" not in page:
        raise LookupError(f"Not found on Commons: {title}")
    return _parse(page)


def search(query, limit=20, width=500):
    data = api(action="query", generator="search", gsrsearch=query, gsrnamespace=6,
               gsrlimit=limit, prop="imageinfo", iiprop="url|size|mime|extmetadata",
               iiurlwidth=width)
    pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
    return [_parse(p) for p in pages if "imageinfo" in p and p["imageinfo"][0]["mime"] in PHOTO_MIMES]


def download(info, dest):
    if not os.path.exists(dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(_get(info["thumburl"]))
    return dest


def contact_sheet(titles, out, cell=420):
    from PIL import Image, ImageDraw, ImageFont
    import io
    cols = 3
    rows = (len(titles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 30)), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 22)
    for i, t in enumerate(titles):
        info = file_info(t, width=500); time.sleep(0.5)
        im = Image.open(io.BytesIO(_get(info["thumburl"]))).convert("RGB")
        im.thumbnail((cell - 10, cell - 10))
        x, y = (i % cols) * cell, (i // cols) * (cell + 30)
        sheet.paste(im, (x + (cell - im.width) // 2, y + 30 + (cell - im.height) // 2))
        tag = f"#{i + 1} {'PD' if is_public_domain(info) else 'NOT PD'} {info['width']}x{info['height']}"
        draw.text((x + 8, y + 4), tag, fill="black" if is_public_domain(info) else "red", font=font)
    sheet.save(out, quality=85)
    return out


def _short(s, n):
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    if cmd == "search":
        for i, r in enumerate(search(args[0], limit=int(args[1]) if len(args) > 1 else 20), 1):
            flag = "PD " if is_public_domain(r) else "-- "
            print(f"{i:>2} {flag}{r['width']}x{r['height']}  {r['title']}")
            print(f"      {_short(r['date'], 30)} | {_short(r['artist'] or r['credit'], 60)} | {r['license']}")
            print(f"      {_short(r['description'], 220)}")
    elif cmd == "info":
        for t in args:
            info = file_info(t)
            info["public_domain"] = is_public_domain(info)
            print(json.dumps(info, indent=2, ensure_ascii=False))
    elif cmd == "sheet":
        print(contact_sheet(args[1:], args[0]))
    else:
        print(__doc__)
