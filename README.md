# quote-reels

Posts one quote reel a day to @betweenyour.thoughts, for free, using GitHub Actions and Instagram's official API.

## How it works

1. `quotes.csv` holds the quotes. Each run takes the first row with an empty `posted_at`.
2. `make_reel.py` renders a 7-second 1080×1920 reel: background, slow zoom, quote fading in, watermark.
3. `post.py` commits the video, posts it as a Reel, and fills in `posted_at`.
4. `.github/workflows/post-reel.yml` runs this every day at 8:00 PM IST.

## Adding things

- **Quotes:** add rows to `quotes.csv`. `lang` is `en` or `te`. `caption` is optional; if it's empty, the quote is used. Write `\n` in the text for a line break.
- **Backgrounds:** if `backgrounds/` is empty, each reel gets a fresh free AI image (Pollinations). Put your own `.jpg`/`.png` images in `backgrounds/` to use those instead. If the AI service is down, a dark gradient is used.
- **Music:** `music/` starts with four soft piano tracks made by `make_music.py` (original, copyright-free). Add royalty-free tracks (Pixabay Music, YouTube Audio Library) in `music/`. If the folder is empty, the reel is silent.

## Secrets (Settings → Secrets and variables → Actions)

- `IG_TOKEN`: the token from the Meta app's "API setup with Instagram login" page.
- `GH_PAT`: a fine-grained GitHub token for this repo with "Secrets: read and write". The weekly refresh workflow uses it to renew `IG_TOKEN` before the 60-day expiry.

## Testing

Actions → "Post daily reel" → Run workflow. With "dry run" ticked, it only renders the reel, and you can download it from the run page. Untick it to post for real.
