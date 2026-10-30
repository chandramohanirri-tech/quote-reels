"""List recent Instagram DM conversations, or send one message to people who wrote in the last 24 hours.

Runs inside GitHub Actions with the IG_TOKEN secret, or with FB_TOKEN (a Facebook user token
for the Facebook Page linked to the Instagram account) when that secret is set. What it does is set by dm/request.json:
    {"mode": "list"}
    {"mode": "send", "text": "Hi!", "to": ["username1", "username2"], "reel": "<media id>"}
"reel" is optional: one of the page's own posts, shared in the chat after the text.
Instagram only allows a business reply within 24 hours of the person's last message,
so "send" skips anyone outside that window. Message text is never printed.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://graph.instagram.com/v23.0"
TOKEN = os.environ.get("IG_TOKEN", "")
REQUEST = Path(__file__).parent / "dm" / "request.json"


def call(method, path, body=None, **params):
    params["access_token"] = TOKEN
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        if "permission" in err.lower() or '"code":10' in err or '"code":200' in err:
            sys.exit(f"Token is missing the messaging permission (instagram_business_manage_messages): {err}")
        sys.exit(f"Instagram API error on {path}: {err}")


def conversations(me, owner="me"):
    """Everyone with a DM thread, with the time of their own latest message."""
    people, after = {}, None
    while True:
        extra = {"after": after} if after else {}
        page = call("GET", f"{owner}/conversations", platform="instagram", limit=50,
                    fields="participants,updated_time,messages.limit(25){from,created_time}", **extra)
        for conv in page.get("data", []):
            others = [p for p in conv.get("participants", {}).get("data", []) if p.get("id") != me]
            if not others:
                continue
            who = others[0]
            theirs = [m["created_time"] for m in conv.get("messages", {}).get("data", [])
                      if m.get("from", {}).get("id") != me]
            last = max(theirs) if theirs else None
            people[who.get("username", who["id"])] = {"id": who["id"], "last": last}
        after = page.get("paging", {}).get("cursors", {}).get("after")
        if not page.get("paging", {}).get("next"):
            return people


def hours_ago(stamp):
    if not stamp:
        return None
    t = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S%z")
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


def check_token():
    """Describe the token's shape without revealing it, to spot paste mistakes."""
    t = TOKEN
    print(f"Token: {len(t)} chars, starts with {t[:2]!r}, "
          f"spaces/newlines: {any(c.isspace() for c in t)}, quotes: {any(c in t for c in '\"\'')}")


def facebook_login():
    """Switch to the Facebook Graph API with the token of the Page linked to the Instagram account."""
    global API, TOKEN
    API, TOKEN = "https://graph.facebook.com/v23.0", os.environ["FB_TOKEN"]
    check_token()
    pages = call("GET", "me/accounts", fields="name,access_token,instagram_business_account{id,username}")
    print(f"Facebook Pages: {[p.get('name') for p in pages.get('data', [])]}")
    for page in pages.get("data", []):
        ig = page.get("instagram_business_account")
        if ig:
            TOKEN = page["access_token"]
            print(f"Using Page '{page['name']}' linked to @{ig.get('username')}")
            return {"user_id": ig["id"], "username": ig.get("username")}, page["id"]
    sys.exit("No Facebook Page linked to an Instagram account was found for this token.")


def main():
    req = json.loads(REQUEST.read_text(encoding="utf-8"))
    if os.environ.get("FB_TOKEN"):
        me, owner = facebook_login()
        people = conversations(me["user_id"], owner)
        sender = owner
    else:
        check_token()
        me = call("GET", "me", fields="user_id,username")
        owner, sender = "me", me["user_id"]
        people = conversations(me["user_id"])
    print(f"Account: @{me.get('username')}")
    if not people and owner == "me":
        # Diagnostic: the same list through the account id, with only ids (no names or text).
        raw = call("GET", f"{me['user_id']}/conversations", platform="instagram", fields="updated_time")
        print(f"Check via account id: {len(raw.get('data', []))} conversations")
        if req.get("subscribe"):
            # Ask Instagram to route this account's messages to the app (needed by some setups).
            print("Subscribe:", call("POST", f"{me['user_id']}/subscribed_apps", subscribed_fields="messages"))
            people = conversations(me["user_id"])
            print(f"After subscribing: {len(people)} conversations")
    print(f"{len(people)} conversations")
    for name, p in sorted(people.items(), key=lambda kv: hours_ago(kv[1]["last"]) or 1e9):
        h = hours_ago(p["last"])
        status = "can message" if h is not None and h < 24 else "outside 24h window"
        age = f"{h:.1f}h ago" if h is not None else "never wrote"
        print(f"  @{name}: last wrote {age} -> {status}")

    if req.get("mode") != "send":
        return
    text = req["text"]
    for name in req["to"]:
        p = people.get(name.lstrip("@"))
        h = hours_ago(p["last"]) if p else None
        if p is None or h is None or h >= 24:
            print(f"SKIPPED @{name}: no message from them in the last 24 hours")
            continue
        res = call("POST", f"{sender}/messages",
                   body={"recipient": {"id": p["id"]}, "message": {"text": text}})
        print(f"SENT to @{name}: {res.get('message_id', res)}")
        if req.get("reel"):
            res = call("POST", f"{sender}/messages",
                       body={"recipient": {"id": p["id"]},
                             "message": {"attachment": {"type": "MEDIA_SHARE", "payload": {"id": req["reel"]}}}})
            print(f"SENT reel to @{name}: {res.get('message_id', res)}")


if __name__ == "__main__":
    main()
