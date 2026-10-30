"""Render one quote reel (1080x1920 MP4) for @betweenyour.thoughts.

Usage:
    python make_reel.py "Some silences hurt more than words." out.mp4 [--lang te] [--seed 7]

Backgrounds come from backgrounds/ (jpg/png), music from music/ (mp3/m4a/wav).
If either folder is empty, a moody gradient / silent track is used instead.
"""
import argparse
import io
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).parent
W, H = 1080, 1920
DURATION = 7.0
FPS = 30
WATERMARK = "betweenyour.thoughts"

FONTS = {
    "en": ROOT / "fonts" / "NotoSerif-Medium.ttf",
    "te": ROOT / "fonts" / "NotoSansTelugu-Medium.ttf",
}
WATERMARK_FONT = ROOT / "fonts" / "NotoSerif-Italic.ttf"
MINIMAL_FONT = ROOT / "fonts" / "Inter-Medium.otf"


def find_ffmpeg():
    # System ffmpeg if present, else the static build from the imageio-ffmpeg pip package.
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


FFMPEG = find_ffmpeg()

# Used when backgrounds/ is empty and AI_BACKGROUNDS=1.
AI_STYLE = ("moody cinematic photo, dark, soft light, film grain, melancholic, "
            "lots of empty space in the middle, no text, no people facing camera")
AI_SCENES = [
    "rain drops on a window at night with blurred city lights",
    "lonely figure in a hoodie seen from behind, looking at a sunset over the sea",
    "empty street at night under a single streetlight in the rain",
    "open old book and a cup of tea by a rainy window",
    "silhouette of a person sitting alone on a rooftop at dusk",
    "dark cloudy sky with a faint orange sunset over fields",
    "dried rose petals on an old wooden table in dim light",
    "empty bench in a park in the fog",
    "candle burning in a dark room, warm glow",
    "crescent moon over calm dark water",
    "handwritten letter and faded photograph on a table, low light",
    "train window view at night with rain streaks",
]

# Dark, moody gradient pairs used when backgrounds/ is empty.
PALETTES = [
    ((12, 14, 28), (58, 46, 82)),
    ((8, 18, 24), (34, 70, 84)),
    ((20, 10, 14), (92, 40, 52)),
    ((14, 14, 14), (70, 62, 54)),
    ((6, 12, 30), (24, 44, 96)),
]


def pick(folder, exts, rng):
    files = sorted(p for p in (ROOT / folder).glob("*") if p.suffix.lower() in exts)
    return rng.choice(files) if files else None


def gradient_background(rng):
    top, bottom = rng.choice(PALETTES)
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        draw.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    # Soft light blob so it isn't a flat gradient.
    glow = Image.new("L", (W, H), 0)
    gx, gy = rng.randint(200, 880), rng.randint(400, 1300)
    ImageDraw.Draw(glow).ellipse([gx - 420, gy - 420, gx + 420, gy + 420], fill=110)
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    img = Image.composite(Image.new("RGB", (W, H), (255, 236, 210)), img, glow)
    return img


def ai_background(rng):
    """Fresh AI image from the free Pollinations API (no key). None if it fails."""
    scene = rng.choice(AI_SCENES)
    prompt = urllib.parse.quote(f"{scene}, {AI_STYLE}")
    url = (f"https://image.pollinations.ai/prompt/{prompt}"
           f"?width={W}&height={H}&seed={rng.randint(1, 10**6)}&nologo=true&model=flux")
    # The free tier is busy at times and allows 1 image per 45s, so retry patiently.
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return Image.open(io.BytesIO(r.read())).convert("RGB")
        except Exception as e:
            print(f"AI background attempt {attempt + 1} failed ({e})", file=sys.stderr)
            time.sleep(30)
    print("AI background unavailable, falling back", file=sys.stderr)
    return None


def load_background(rng, path=None):
    path = path or pick("backgrounds", {".jpg", ".jpeg", ".png", ".webp"}, rng)
    if path is not None:
        img = Image.open(path).convert("RGB")
    else:
        img = ai_background(rng) if os.environ.get("AI_BACKGROUNDS") == "1" else None
        if img is None:
            return gradient_background(rng)
    # Cover-crop to 9:16.
    scale = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((left, top, left + W, top + H))


def darken(img):
    # Vertical shade, strongest behind the text band, keeps any image readable.
    shade = Image.new("L", (W, H))
    d = ImageDraw.Draw(shade)
    for y in range(H):
        dist = abs(y - H * 0.45) / (H * 0.55)
        d.line([(0, y), (W, y)], fill=int(150 - 60 * min(dist, 1)))
    return Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, shade)


def wrap(text, font, draw, max_width):
    lines = []
    for para in text.split("\n"):
        words, line = para.split(), ""
        for word in words:
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= max_width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def minimal_layer(quote):
    """Small left-aligned text with a thin red bar, like a film subtitle."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = ImageFont.truetype(str(MINIMAL_FONT), 40)
    lines = wrap(quote, font, draw, W * 0.8)
    line_h = 54
    block_w = max(draw.textlength(line, font=font) for line in lines)
    x = int((W - block_w) / 2) + 14
    top = int(H * 0.56)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    for k, line in enumerate(lines):
        sdraw.text((x, top + k * line_h + 2), line, font=font, fill=(0, 0, 0, 220))
        draw.text((x, top + k * line_h), line, font=font, fill=(250, 250, 250, 255))
    layer = Image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(4)), layer)
    draw = ImageDraw.Draw(layer)
    draw.rectangle([x - 16, top + 6, x - 11, top + len(lines) * line_h - 4], fill=(220, 38, 38, 255))
    wfont = ImageFont.truetype(str(WATERMARK_FONT), 30)
    wx = (W - draw.textlength(WATERMARK, font=wfont)) / 2
    draw.text((wx, H - 260), WATERMARK, font=wfont, fill=(245, 240, 232, 150))
    return layer


def text_layer(quote, lang):
    """Transparent PNG with the quote centred and the watermark at the bottom."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    max_width = W - 2 * 120
    size = 78 if lang == "en" else 70
    while True:
        font = ImageFont.truetype(str(FONTS[lang]), size)
        lines = wrap(quote, font, draw, max_width)
        line_h = int(size * (1.45 if lang == "en" else 1.7))
        # With manual line breaks, shrink until no line has to wrap again.
        fits_breaks = "\n" not in quote or len(lines) == quote.count("\n") + 1
        if (len(lines) * line_h <= H * 0.42 and fits_breaks) or size <= 44:
            break
        size -= 4
    y = int(H * 0.45 - len(lines) * line_h / 2)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    for line in lines:
        x = (W - draw.textlength(line, font=font)) / 2
        sdraw.text((x, y + 3), line, font=font, fill=(0, 0, 0, 200))
        draw.text((x, y), line, font=font, fill=(245, 240, 232, 255))
        y += line_h
    layer = Image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)), layer)

    draw = ImageDraw.Draw(layer)
    wfont = ImageFont.truetype(str(WATERMARK_FONT), 34)
    wx = (W - draw.textlength(WATERMARK, font=wfont)) / 2
    draw.text((wx, H - 260), WATERMARK, font=wfont, fill=(245, 240, 232, 170))
    return layer


def watermark_layer():
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    wfont = ImageFont.truetype(str(WATERMARK_FONT), 30)
    wx = (W - draw.textlength(WATERMARK, font=wfont)) / 2
    draw.text((wx, H - 200), WATERMARK, font=wfont, fill=(245, 240, 232, 160))
    return layer


def fit_with_blur(path):
    """Fit a finished post (any shape) into 9:16 without cropping it, over a blurred copy."""
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    scale = max(W / img.width, H / img.height)
    back = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (back.width - W) // 2, (back.height - H) // 2
    back = back.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(40))
    back = Image.blend(back, Image.new("RGB", (W, H), (0, 0, 0)), 0.35)
    scale = min(W / img.width, H / img.height)
    front = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    back.paste(front, ((W - front.width) // 2, (H - front.height) // 2))
    return back


def soft_shade(img):
    # Lighter grade for the minimal style: keep the photo, just calm the highlights.
    return Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), 0.25)


def render(quote, out, lang="en", seed=None, bg=None, mood="sad", music=None, style="classic"):
    rng = random.Random(seed)
    exts = {".mp3", ".m4a", ".wav", ".aac"}
    # music=False means a silent reel.
    music = None if music is False else music or pick(f"music/{'sad' if mood == 'sad' else 'uplifting'}", exts, rng) or pick("music", exts, rng)
    with tempfile.TemporaryDirectory() as tmp:
        bg_path, txt_path = Path(tmp) / "bg.png", Path(tmp) / "text.png"
        if style in ("finished", "asis"):
            # Chandu's own finished post: keep it as is ("asis" already has the watermark).
            fit_with_blur(bg).save(bg_path)
            (watermark_layer() if style == "finished" else Image.new("RGBA", (W, H))).save(txt_path)
        elif style == "minimal":
            soft_shade(load_background(rng, bg)).save(bg_path)
            minimal_layer(quote).save(txt_path)
        else:
            darken(load_background(rng, bg)).save(bg_path)
            text_layer(quote, lang).save(txt_path)

        frames = int(DURATION * FPS)
        video = (
            # Upscale first so the slow zoom doesn't jitter.
            f"[0:v]scale={W * 2}:{H * 2},zoompan=z='1+0.06*on/{frames}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS}[bg];"
            f"[1:v]format=rgba,fade=in:st=0.6:d=1.2:alpha=1[txt];"
            f"[bg][txt]overlay=0:0,fade=out:st={DURATION - 0.6}:d=0.6,format=yuv420p[v]"
        )
        cmd = [FFMPEG, "-y", "-loglevel", "error",
               "-loop", "1", "-i", str(bg_path),
               "-loop", "1", "-i", str(txt_path)]
        if music:
            cmd += ["-ss", str(rng.choice([0, 5, 10, 20])), "-i", str(music)]
            audio = f"[2:a]afade=in:d=1,afade=out:st={DURATION - 1.2}:d=1.2[a]"
        else:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
            audio = "[2:a]anull[a]"
        cmd += ["-filter_complex", f"{video};{audio}",
                "-map", "[v]", "-map", "[a]", "-t", str(DURATION),
                "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "20",
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("quote")
    ap.add_argument("out")
    ap.add_argument("--lang", default="en", choices=FONTS)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--bg", help="background image to use instead of backgrounds/")
    ap.add_argument("--mood", default="sad", help="sad, motivation, inspiring or life")
    ap.add_argument("--music", help="music file to use instead of music/")
    ap.add_argument("--style", default="classic", choices=["classic", "minimal", "finished", "asis"])
    a = ap.parse_args()
    render(a.quote.replace("\\n", "\n"), a.out, a.lang, a.seed, a.bg, a.mood, a.music, a.style)
