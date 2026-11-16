"""Render title cards (white Arial Black on black) and encode a silent 1080p H.264 MP4.

Readability: a 50" 16:9 TV is ~24.5" tall, so 1080 px ≈ 44 px per inch. Common signage
guidance is ~1" of letter height per 25-30 ft for comfortable reading, so at 50 ft we want
caps ≥ ~2". Arial Black cap height is ~0.72 em, so the floor is a 120 px font
(≈ 86 px / ~2" caps). Text that won't fit at that size is split onto extra cards.
"""
import glob
import os
import re
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
MARGIN_X, MARGIN_Y = 110, 90
MAX_SIZE, MIN_SIZE, STEP = 230, 120, 6
LINE_SPACING = 1.12
FPS = 30

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/msttcorefonts/Arial_Black.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/ariblk.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Arial Black.ttf",
    "/usr/local/share/fonts/ariblk.ttf",
    "/usr/local/share/fonts/Arial Black.ttf",
]


def find_font(override=""):
    if override and os.path.isfile(override):
        return override
    for p in FONT_CANDIDATES:
        if os.path.isfile(p):
            return p
    for p in glob.glob("/usr/share/fonts/**/*", recursive=True) + glob.glob("/usr/local/share/fonts/**/*", recursive=True):
        n = os.path.basename(p).lower().replace(" ", "").replace("_", "")
        if n in ("ariblk.ttf", "arialblack.ttf"):
            return p
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", "Arial Black"], capture_output=True, text=True, timeout=5).stdout
        if out and "black" in out.lower():
            return out
    except Exception:
        pass
    raise FileNotFoundError("Arial Black not found. Install ttf-mscorefonts-installer or upload ariblk.ttf in Settings.")


def _wrap(draw, words, font, max_w):
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if not cur:  # single word too long for the line
                return None
            lines.append(cur)
            cur = w
            if draw.textlength(cur, font=font) > max_w:
                return None
    if cur:
        lines.append(cur)
    return lines


def _fit(text, font_path):
    """Return (size, lines) for the largest size that fits, or None."""
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    words = text.split()
    for size in range(MAX_SIZE, MIN_SIZE - 1, -STEP):
        font = ImageFont.truetype(font_path, size)
        lines = _wrap(draw, words, font, W - 2 * MARGIN_X)
        if lines and len(lines) * size * LINE_SPACING <= H - 2 * MARGIN_Y:
            return size, lines
    return None


def _split(text):
    """Split text into two roughly equal halves, preferring sentence/clause breaks."""
    parts = re.split(r"(?<=[.!?;:])\s+|(?<=—)\s*|\s+—\s+", text)
    parts = [p for p in parts if p.strip()]
    if len(parts) > 1:
        total = len(text)
        diffs = []
        for i in range(1, len(parts)):
            left = " ".join(parts[:i])
            diffs.append((abs(len(left) - total / 2), i))
        best = min(diffs)[1]
        return " ".join(parts[:best]), " ".join(parts[best:])
    words = text.split()
    mid = len(words) // 2
    return " ".join(words[:mid]), " ".join(words[mid:])


def layout_cards(texts, font_path):
    """Expand texts into cards that each fit on screen at a readable size."""
    cards = []
    for t in texts:
        t = re.sub(r"\s+", " ", t).strip()
        if not t:
            continue
        fit = _fit(t, font_path)
        if fit:
            cards.append((t, *fit))
        elif len(t.split()) > 1:
            a, b = _split(t)
            cards.extend(layout_cards([a, b], font_path))
        else:
            cards.append((t, MIN_SIZE, [t]))
    return cards


def draw_card(size, lines, font_path, out_path):
    img = Image.new("RGB", (W, H), "black")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, size)
    line_h = size * LINE_SPACING
    total = line_h * len(lines)
    y = (H - total) / 2 + (line_h - size) / 2
    for line in lines:
        d.text((W / 2, y + size / 2), line, font=font, fill="white", anchor="mm")
        y += line_h
    img.save(out_path)


def card_texts(issue):
    """Selected cards in order; Spanish card follows its English card."""
    texts = []
    for c in issue["cards"]:
        if not c["selected"] or not c["text_en"].strip():
            continue
        texts.append(c["text_en"])
        if c.get("text_es", "").strip():
            texts.append(c["text_es"])
    return texts


def preview_png(text, font_path, out_path):
    cards = layout_cards([text], font_path)
    _, size, lines = cards[0]
    draw_card(size, lines, font_path, out_path)
    return len(cards)


def render_video(texts, duration, font_path, out_path):
    cards = layout_cards(texts, font_path)
    if not cards:
        raise ValueError("no text to render")
    per = max(1.0, float(duration) / len(cards))
    with tempfile.TemporaryDirectory() as tmp:
        args = ["ffmpeg", "-y", "-loglevel", "error"]
        for i, (_, size, lines) in enumerate(cards):
            p = os.path.join(tmp, f"card{i:02d}.png")
            draw_card(size, lines, font_path, p)
            args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{per:.3f}", "-i", p]
        n = len(cards)
        filt = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0,format=yuv420p[v]"
        args += ["-filter_complex", filt, "-map", "[v]", "-an",
                 "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "20",
                 "-r", str(FPS), "-g", str(FPS * 2), "-profile:v", "high", "-level", "4.1",
                 "-movflags", "+faststart", "-f", "mp4", out_path + ".part"]
        res = subprocess.run(args, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {res.stderr.strip()[-400:]}")
        os.replace(out_path + ".part", out_path)
    return len(cards), per
