# This Day in WWII History

A daily Instagram post: a real, public-domain WWII photo in a framed card with the date and a caption on the border, plus a ready-to-paste Instagram caption with the story and 5 hashtags.

## What's here

| Path | What it is |
|---|---|
| `posts/YYYY-MM-DD/post.jpg` | The image to upload (1080×1350, Instagram's 4:5 portrait size) |
| `posts/YYYY-MM-DD/caption.txt` | The Instagram caption: story, photo credit, 5 hashtags |
| `posts/YYYY-MM-DD/source.json` | Where the photo came from and its public-domain license (keep as proof) |
| `calendar/MM-DD.json` | One entry per day of the year: event, photo, captions, hashtags. Reusable every year |
| `profile/avatar.png` | Profile picture |
| `make_post.py` | Builds the posts from the calendar |
| `commons.py` | Searches Wikimedia Commons and checks photo licenses |
| `publish.py` | Posts each day to Instagram through the official API |
| `launchd/` | The daily job that runs `publish.py` |
| `config.json` | Look (`dark` or `paper`), your handle, and posting settings (start date, time) |
| `.env` | Your Instagram token. Created during setup, stays on this Mac, never uploaded |

Ready now: **November 2 – 15**, starting today.

## 1. Set up the account (once, about 5 minutes)

1. Create the account in the Instagram app.
2. **Name:** `This Day in WWII History`
3. **Username:** `thisdayinwwii`
4. **Profile picture:** `profile/avatar.png`
5. **Bio** (under Instagram's 150-character limit):
   ```
   One World War II story for every day of the year.
   Real archive photos, all public domain.
   🎖️ 1939–1945 · New post daily
   ```
6. Switch to a **Professional account → Creator**, category **Education**. It's free, adds insights, and lets you schedule posts in the app.
7. The handle is already set in `config.json`, so @thisdayinwwii is printed in every image's footer and reposts credit you. If it ever changes, edit `config.json` and re-run the build.

## 2. Post by hand (November 2–6)

From November 7 on, posting is automatic (section 4). Don't also schedule those days in the app, or they'll post twice.

- **From the Mac:** on instagram.com, click **Create**, upload `post.jpg`, and paste `caption.txt`.
- **Schedule ahead:** in the app, before sharing, open **Advanced settings → Schedule this post**.
- Post at the same time each morning. Consistency matters more than the exact hour.

## 3. Make more days

Each day is one JSON file in `calendar/`, named `MM-DD.json`:

```json
{
  "year": 1942,
  "headline": "Short title",
  "border_caption": "What the photo shows (goes on the image border, 3 lines max)",
  "image": {
    "file": "File:Exact Wikimedia Commons file name.jpg",
    "credit": "U.S. Navy",
    "note": "Full photo description with date (goes in the Instagram caption)",
    "crop": [0, 0, 0, 0]
  },
  "hook": "First line of the caption (Instagram cuts the preview at ~125 characters)",
  "body": ["Paragraph", "Paragraph", "Paragraph"],
  "closer": "Optional question or closing line",
  "hashtags": ["#Five", "#Hashtags", "#Exactly", "#WWII", "#OnThisDay"]
}
```

Then build:

```bash
python3 make_post.py                          # today
python3 make_post.py --from 2026-11-16 --days 14
```

The build **refuses any photo that Wikimedia Commons doesn't mark as public domain**, so a copyrighted image can't slip through. `crop` trims scan borders and is given as fractions of the left, top, right, and bottom edges. To find photos, run `python3 commons.py search "Battle of Midway"`.

How photos were chosen: U.S. government (Army, Navy, Signal Corps, Office of War Information), UK Crown copyright expired (Imperial War Museums), Australian War Memorial, and a 1941 Japanese government document. Soviet and German Bundesarchiv photos were skipped. Their "public domain" status is shaky, or they're actually CC-licensed.

## 4. Automatic posting

Starting **November 7**, a job on this Mac publishes each day's post at **5:00 PM Central** through Instagram's official API.

- **Schedule:** it runs at 5:00 PM, retries at 7:00 PM, and also runs at login in case the Mac was off at 5:00. It never posts a day twice. Each published day gets a `published.json` with the post's link.
- **Images:** Instagram fetches each image from a public link, so the posts are hosted on GitHub at [bfrische/thisdayinwwii](https://github.com/bfrische/thisdayinwwii). The job uploads any new day by itself. Your token is never uploaded.
- **Missing posts:** if a day's post hasn't been built yet but the calendar has an entry for it, the job builds the post that morning.
- **Token:** it renews itself weekly. It only expires if the Mac is off for 60 days in a row; if that happens, repeat steps 4–5 below.
- **Mac asleep at 5:00?** The job runs as soon as it wakes. If the Mac stays off all day, that day is skipped rather than posted late.
- **Problems:** you get a Mac notification (no token, no calendar entry for the day, an Instagram error). Details are in `logs/publish.log`.

### One-time Meta setup (about 15 minutes)

1. Go to **developers.facebook.com** and log in with Facebook. Register as a developer if asked; it's free.
2. Click **My Apps → Create app**. Skip connecting a business portfolio, choose the use case **Other**, then the app type **Business**. Name it anything (for example "thisdayinwwii poster") and create it.
3. In the app's dashboard, find **Instagram**, click **Set up**, then open **Instagram → API setup with Instagram login**.
4. Under **Generate access tokens**, add your Instagram account and log in as @thisdayinwwii. Then click **Generate token** next to it and copy the token.
   - If Instagram asks you to accept a tester invite, accept it in the app: **Settings → Website permissions → Apps and websites → Tester invites**.
   - Leave the app in Development mode. That's all you need to post to your own account.
5. With the token still copied, run this. It saves the token into `.env` without showing it:
   ```bash
   cd /Users/bill/Projects/instagram-wwii && python3 publish.py --save-token
   ```
6. Check everything without posting anything:
   ```bash
   cd /Users/bill/Projects/instagram-wwii && python3 publish.py --check
   ```

### Pause or resume the daily job

```bash
launchctl bootout gui/$(id -u)/com.thisdayinwwii.publish
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.thisdayinwwii.publish.plist
```

To change the start date or posting time, edit `publish` in `config.json`. If you change the time, also change the hours in `launchd/com.thisdayinwwii.publish.plist`, copy it to `~/Library/LaunchAgents/`, then pause and resume the job.

### Why not `~/Downloads/instagramautopost`?

That tool logs in with your password through `instagrapi`, an unofficial client. Instagram flags accounts that do this, and new accounts most of all. The official API has no such risk.
