#!/usr/bin/env python3
"""Publish today's "This Day in WWII History" post to Instagram through the official Instagram API.

The daily launchd job (launchd/com.thisdayinwwii.publish.plist) runs this at the posting time. For today it:
  1. does nothing before publish.start_date, before publish.time, or if today is already published,
  2. builds posts/YYYY-MM-DD/ from the calendar if it doesn't exist yet,
  3. makes sure post.jpg is public on GitHub (Instagram fetches the image from a link),
  4. renews the Instagram token about once a week (an unrenewed token dies after 60 days),
  5. publishes, then records the result in posts/YYYY-MM-DD/published.json so no day posts twice.

  python3 publish.py                  # what the daily job runs
  python3 publish.py --check          # verify everything for the next post; never publishes
  python3 publish.py --check --date 2026-11-16
  python3 publish.py --save-token     # store the token you just copied (reads the clipboard)
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(ROOT, ".env")
GRAPH = "https://graph.instagram.com"
TOKEN_KEY, RENEWED_KEY = "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_TOKEN_RENEWED"


class ApiError(Exception):
    pass


def log(msg):
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}", flush=True)


def notify(msg):
    """Desktop notification, so a failed run doesn't go unnoticed."""
    script = f'display notification {json.dumps(msg, ensure_ascii=False)} with title "This Day in WWII"'
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def load_config():
    cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
    return cfg, cfg["publish"]


# ---------- .env (token storage; never committed, never printed) ----------

def read_env():
    env = {}
    if os.path.exists(ENV_PATH):
        for line in open(ENV_PATH, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip("\"'")
    return env


def write_env(key, value):
    lines = open(ENV_PATH, encoding="utf-8").read().splitlines() if os.path.exists(ENV_PATH) else []
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    tmp = ENV_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ENV_PATH)


# ---------- Instagram API ----------

def api(method, path, **params):
    url = f"{GRAPH}/{path}"
    data = urllib.parse.urlencode(params).encode() if method == "POST" else None
    if method == "GET":
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method), timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            body = json.loads(body).get("error", {}).get("message", body)
        except ValueError:
            pass
        raise ApiError(f"Instagram said ({e.code}): {body}") from None


def renew_token_weekly(env):
    """Swap the token for a fresh 60-day one once a week. Tokens must be a day old to renew."""
    token = env[TOKEN_KEY]
    today = dt.date.today()
    last = env.get(RENEWED_KEY)
    if not last:
        write_env(RENEWED_KEY, today.isoformat())
        return token
    if (today - dt.date.fromisoformat(last)).days < 7:
        return token
    try:
        data = api("GET", "refresh_access_token", grant_type="ig_refresh_token", access_token=token)
    except ApiError as e:
        log(f"Token renewal failed, will retry next run: {e}")
        return token
    write_env(TOKEN_KEY, data["access_token"])
    write_env(RENEWED_KEY, today.isoformat())
    log(f"Token renewed, good for {int(data.get('expires_in', 0)) // 86400} more days")
    return data["access_token"]


def account(token, version):
    return api("GET", f"{version}/me", fields="user_id,username", access_token=token)


def find_existing(token, version, ig_id, hook):
    """A post with today's caption already on the account (e.g. one scheduled in the app)."""
    recent = api("GET", f"{version}/{ig_id}/media", fields="id,caption,permalink,timestamp", limit=10, access_token=token)
    for m in recent.get("data", []):
        if (m.get("caption") or "").startswith(hook[:80]):
            return m
    return None


def publish_image(token, version, ig_id, image_url, caption):
    container = api("POST", f"{version}/{ig_id}/media", image_url=image_url, caption=caption, access_token=token)["id"]
    for _ in range(30):  # Instagram has to fetch and process the image first; allow ~5 minutes
        status = api("GET", f"{version}/{container}", fields="status_code", access_token=token).get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise ApiError(f"Instagram couldn't process the image (status {status})")
        time.sleep(10)
    else:
        raise ApiError("Instagram took more than 5 minutes to process the image")
    media_id = api("POST", f"{version}/{ig_id}/media_publish", creation_id=container, access_token=token)["id"]
    info = api("GET", f"{version}/{media_id}", fields="permalink,timestamp", access_token=token)
    return media_id, info.get("permalink", "")


# ---------- the post and its public link ----------

def post_dir(day):
    return os.path.join(ROOT, "posts", day.isoformat())


def ensure_post(day):
    """Build the day's post from the calendar if it hasn't been built yet. Returns an error or None."""
    if os.path.exists(os.path.join(post_dir(day), "post.jpg")):
        return None
    if not os.path.exists(os.path.join(ROOT, "calendar", day.strftime("%m-%d.json"))):
        return f"No post for {day:%B %-d}: the calendar has no entry for that day yet."
    sys.path.insert(0, ROOT)
    import make_post
    try:
        make_post.make_post(day)
    except SystemExit as e:
        return f"Couldn't build the post for {day}: {e}"
    return None


def image_url(pub, day):
    return f"https://raw.githubusercontent.com/{pub['github_repo']}/{pub['branch']}/posts/{day.isoformat()}/post.jpg"


def is_public(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30) as r:
            return r.status == 200 and r.headers.get("Content-Type", "").startswith("image/jpeg")
    except urllib.error.URLError:
        return False


def push_post(day):
    """Commit and push the day's folder so GitHub serves the image."""
    git = lambda *a: subprocess.run(["git", "-C", ROOT, *a], capture_output=True, text=True)
    git("add", f"posts/{day.isoformat()}")
    if git("diff", "--cached", "--quiet").returncode:
        git("commit", "-m", f"Add post for {day.isoformat()}")
    result = git("push", "origin", "HEAD")
    if result.returncode:
        log(f"git push failed: {result.stderr.strip()}")


def make_public(pub, day):
    url = image_url(pub, day)
    if is_public(url):
        return url
    push_post(day)
    for _ in range(18):  # GitHub can take a minute to serve a new file
        if is_public(url):
            return url
        time.sleep(10)
    return None


# ---------- commands ----------

def daily(cfg, pub):
    env = read_env()
    token = renew_token_weekly(env) if env.get(TOKEN_KEY) else ""
    today, now = dt.date.today(), dt.datetime.now()
    start = dt.date.fromisoformat(pub["start_date"])
    if today < start:
        log(f"Automatic posting starts {start:%B %-d}; nothing to do today.")
        return 0
    record = os.path.join(post_dir(today), "published.json")
    if os.path.exists(record):
        log(f"{today} is already published.")
        return 0
    hour, minute = map(int, pub["time"].split(":"))
    if now.time() < dt.time(hour, minute):
        log(f"Too early; today's post goes out at {pub['time']}.")
        return 0

    def fail(msg):
        log("FAILED: " + msg)
        notify(msg)
        return 1

    if not token:
        return fail("Today's post wasn't published: there's no Instagram token in .env yet.")
    problem = ensure_post(today)
    if problem:
        return fail(problem)
    url = make_public(pub, today)
    if not url:
        return fail("Today's post wasn't published: its image isn't reachable on GitHub.")
    entry = json.load(open(os.path.join(ROOT, "calendar", today.strftime("%m-%d.json")), encoding="utf-8"))
    caption = open(os.path.join(post_dir(today), "caption.txt"), encoding="utf-8").read().strip()
    try:
        me = account(token, pub["api_version"])
        if me.get("username", "").lower() != cfg["handle"].lstrip("@").lower():
            return fail(f"The token belongs to @{me.get('username')}, not @{cfg['handle']}. Nothing was posted.")
        existing = find_existing(token, pub["api_version"], me["user_id"], entry["hook"])
        if existing:
            media_id, link, how = existing["id"], existing.get("permalink", ""), "already on Instagram"
        else:
            media_id, link = publish_image(token, pub["api_version"], me["user_id"], url, caption)
            how = "published by the daily job"
    except ApiError as e:
        return fail(f"Today's post wasn't published. {e}")
    with open(record, "w") as f:
        json.dump({"media_id": media_id, "permalink": link, "recorded": now.isoformat(timespec="seconds"), "how": how},
                  f, indent=2)
    log(f"{how}: {entry['headline']} {link}")
    if how.startswith("published"):
        notify(f"Posted: {entry['headline']}")
    return 0


def check(cfg, pub, day):
    """Everything the daily job needs, verified without publishing anything."""
    ok = True

    def line(passed, text):
        nonlocal ok
        ok &= passed
        print(f"  {'✓' if passed else '✗'} {text}")

    print(f"Checking {day:%A, %B %-d, %Y} (nothing will be posted)")
    folder = post_dir(day)
    has_post = os.path.exists(os.path.join(folder, "post.jpg"))
    has_entry = os.path.exists(os.path.join(ROOT, "calendar", day.strftime("%m-%d.json")))
    if has_post:
        caption = open(os.path.join(folder, "caption.txt"), encoding="utf-8").read()
        tags = caption.count("#")
        line(len(caption) <= 2200 and tags <= 30, f"post.jpg and caption.txt ready ({len(caption)} characters, {tags} hashtags)")
        url = image_url(pub, day)
        line(is_public(url), f"image is public at {url}")
    else:
        line(has_entry, "calendar entry exists; the job will build the post that morning" if has_entry
             else f"no post and no calendar entry for {day:%B %-d}")
    line(day >= dt.date.fromisoformat(pub["start_date"]),
         f"automatic posting starts {pub['start_date']} at {pub['time']}")
    if os.path.exists(os.path.join(folder, "published.json")):
        print("  • already published; the job will skip this day")
    token = read_env().get(TOKEN_KEY)
    if not token:
        line(False, "no Instagram token in .env yet")
        return 0 if ok else 1
    try:
        me = account(token, pub["api_version"])
        line(me.get("username", "").lower() == cfg["handle"].lstrip("@").lower(),
             f"token works and belongs to @{me.get('username')}")
        quota = api("GET", f"{pub['api_version']}/{me['user_id']}/content_publishing_limit",
                    fields="quota_usage,config", access_token=token).get("data", [{}])[0]
        line(True, f"publishing quota: {quota.get('quota_usage', 0)} of {quota.get('config', {}).get('quota_total', 100)} used in the last 24 hours")
    except ApiError as e:
        line(False, f"token didn't work. {e}")
    return 0 if ok else 1


def next_unpublished(pub):
    day = max(dt.date.today(), dt.date.fromisoformat(pub["start_date"]))
    while os.path.exists(os.path.join(post_dir(day), "published.json")):
        day += dt.timedelta(days=1)
    return day


def save_token():
    token = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()
    if len(token) < 60 or any(c.isspace() for c in token):
        print("The clipboard doesn't hold an access token. Copy it from the Meta dashboard and run this again.")
        return 1
    write_env(TOKEN_KEY, token)
    write_env(RENEWED_KEY, dt.date.today().isoformat())
    print(f"Saved a {len(token)}-character token to .env (not shown, never committed).")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="verify setup without publishing")
    ap.add_argument("--date", help="YYYY-MM-DD for --check (default: next day the job will post)")
    ap.add_argument("--save-token", action="store_true", help="store the access token from the clipboard in .env")
    a = ap.parse_args()
    cfg, pub = load_config()
    if a.save_token:
        sys.exit(save_token())
    if a.check:
        sys.exit(check(cfg, pub, dt.date.fromisoformat(a.date) if a.date else next_unpublished(pub)))
    sys.exit(daily(cfg, pub))
