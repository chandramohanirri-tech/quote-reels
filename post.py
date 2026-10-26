"""Render the next unposted quote from quotes.csv and publish it as an Instagram Reel.

Runs inside GitHub Actions. Needs env vars:
    IG_TOKEN           Instagram API long-lived access token (GitHub secret)
    GITHUB_REPOSITORY  owner/repo, set by Actions (used for the public video URL)
    DRY_RUN=1          optional: render and commit the video, but don't post
"""
import csv
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from make_reel import render

ROOT = Path(__file__).parent
QUOTES = ROOT / "quotes.csv"
API = "https://graph.instagram.com/v23.0"

FOLLOW = "Follow @betweenyour.thoughts for more"
CTA = {
    "sad": "Tag someone who needs to read this 🤍",
    "motivation": "Save this for the days you feel like giving up 💪",
    "inspiring": "Share this with someone who needs a little hope ✨",
    "life": "Save this and read it again in a year 📌",
}
HASHTAGS = {
    "sad": "#sadquotes #heartbreak #selfworth #healing #deepthoughts",
    "motivation": "#motivation #motivationalquotes #discipline #selfgrowth #nevergiveup",
    "inspiring": "#inspiration #inspirationalquotes #hope #positivevibes #keepgoing",
    "life": "#lifequotes #lifelessons #wisdom #mindset #deepthoughts",
}
TELUGU_TAGS = "#teluguquotes #telugu #telugumotivation"


def api(method, path, **params):
    params["access_token"] = os.environ["IG_TOKEN"]
    data = urllib.parse.urlencode(params).encode()
    url = f"{API}/{path}"
    if method == "GET":
        req = urllib.request.Request(f"{url}?{data.decode()}")
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Instagram API error on {path}: {e.read().decode()}")


def git(*args):
    subprocess.run(["git", *args], check=True, cwd=ROOT)


def push(message):
    git("add", "-A")
    git("commit", "-m", message)
    git("push")


def main():
    with QUOTES.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fields = list(rows[0].keys())
    todo = [i for i, r in enumerate(rows) if not r["posted_at"].strip()]
    if not todo:
        sys.exit("No quotes left in quotes.csv. Add more rows to keep posting.")
    i = todo[0]
    row = rows[i]
    lang = row["lang"].strip() or "en"
    mood = row.get("mood", "").strip() or "sad"

    # Today's background (made by Chandu in ChatGPT) goes in incoming/; it's used once.
    todays = sorted((ROOT / "incoming").glob("*.[jp][pn]g")) + sorted((ROOT / "incoming").glob("*.jpeg"))
    bg = todays[0] if todays else None
    if bg is None and os.environ.get("REQUIRE_IMAGE") == "1":
        sys.exit("No image in incoming/ for today's reel.")

    video = Path("reels") / f"{i + 1:03d}.mp4"
    render(row["text"].replace("\\n", "\n"), ROOT / video, lang, seed=i, bg=bg, mood=mood)
    if bg is not None and os.environ.get("DRY_RUN") != "1":
        used = ROOT / "backgrounds" / "used" / f"{i + 1:03d}{bg.suffix}"
        used.parent.mkdir(parents=True, exist_ok=True)
        bg.rename(used)
    push(f"Render reel {video.name}")

    if os.environ.get("DRY_RUN") == "1":
        print(f"Dry run: rendered {video}, not posting.")
        return

    quote = row["text"].replace("\\n", "\n")
    heading = row.get("heading", "").strip()
    caption = row["caption"].strip() or (f"{heading}\n\n“{quote}”" if heading else quote)
    tags = HASHTAGS.get(mood, HASHTAGS["sad"]) + (f" {TELUGU_TAGS}" if lang == "te" else "") + " #quotes #reels"
    caption = f"{caption}\n\n{CTA.get(mood, CTA['sad'])}\n{FOLLOW}\n\n{tags}"
    branch = subprocess.run(["git", "branch", "--show-current"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()
    video_url = f"https://raw.githubusercontent.com/{os.environ['GITHUB_REPOSITORY']}/{branch}/{video.as_posix()}"

    user_id = api("GET", "me", fields="user_id")["user_id"]
    container = api("POST", f"{user_id}/media", media_type="REELS", video_url=video_url,
                    caption=caption, share_to_feed="true")["id"]
    for _ in range(40):  # Instagram processes the video; wait up to ~10 min.
        status = api("GET", container, fields="status_code,status")
        if status.get("status_code") == "FINISHED":
            break
        if status.get("status_code") in ("ERROR", "EXPIRED"):
            sys.exit(f"Instagram couldn't process the video: {status}")
        time.sleep(15)
    else:
        sys.exit("Timed out waiting for Instagram to process the video.")
    media_id = api("POST", f"{user_id}/media_publish", creation_id=container)["id"]
    print(f"Posted reel {video.name} as media {media_id}")

    row["posted_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with QUOTES.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    push(f"Mark quote {i + 1} as posted")


if __name__ == "__main__":
    main()
