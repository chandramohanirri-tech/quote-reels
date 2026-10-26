"""Render one quote reel (1080x1920 MP4) for @betweenyour.thoughts.

Usage:
    python make_reel.py "Some silences hurt more than words." out.mp4 [--lang te] [--seed 7]

Backgrounds come from backgrounds/ (jpg/png), music from music/ (mp3/m4a/wav).
If either folder is empty, a moody gradient / silent track is used instead.
"""
import argparse
import random
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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


def load_background(rng):
    path = pick("backgrounds", {".jpg", ".jpeg", ".png", ".webp"}, rng)
    if path is None:
        return gradient_background(rng)
    img = Image.open(path).convert("RGB")
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
        if len(lines) * line_h <= H * 0.42 or size <= 44:
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


def render(quote, out, lang="en", seed=None):
    rng = random.Random(seed)
    music = pick("music", {".mp3", ".m4a", ".wav", ".aac"}, rng)
    with tempfile.TemporaryDirectory() as tmp:
        bg_path, txt_path = Path(tmp) / "bg.png", Path(tmp) / "text.png"
        darken(load_background(rng)).save(bg_path)
        text_layer(quote, lang).save(txt_path)

        frames = int(DURATION * FPS)
        video = (
            # Upscale first so the slow zoom doesn't jitter.
            f"[0:v]scale={W * 2}:{H * 2},zoompan=z='1+0.06*on/{frames}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS}[bg];"
            f"[1:v]format=rgba,fade=in:st=0.6:d=1.2:alpha=1[txt];"
            f"[bg][txt]overlay=0:0,fade=out:st={DURATION - 0.6}:d=0.6,format=yuv420p[v]"
        )
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
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
    a = ap.parse_args()
    render(a.quote.replace("\\n", "\n"), a.out, a.lang, a.seed)
