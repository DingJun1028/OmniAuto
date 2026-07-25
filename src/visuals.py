"""Module 4 — Visuals.

Default (free): generate a smooth two-color gradient background with a
subtle vignette + title text using Pillow, then the renderer applies a
slow ken-burns zoom/pan for motion. If RUNWAY_API_KEY is set, the shot's
visual_prompt is sent to Runway to produce an AI-generated B-roll clip.

Each shot renders to ONE representative frame (PNG). The ffmpeg renderer
turns that still into motion (ken-burns) so we don't need per-shot video
generation to produce a watchable clip.
"""
from __future__ import annotations

import httpx
from PIL import Image, ImageDraw, ImageFont

from .config import RUNWAY_API_KEY, USE_RUNWAY, VIDEO_WIDTH, VIDEO_HEIGHT

# Try to find a usable TrueType font; fall back to bitmap if missing.
def _font(size: int):
    for cand in [
        "C:/Windows/Fonts/msyh.ttc",   # Microsoft YaHei (zh)
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]:
        try:
            return ImageFont.truetype(cand, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))


def gradient_frame(color1: str, color2: str, text: str, idx: int, total: int) -> Image.Image:
    """Render one 16:9 gradient background. Caption text is NOT drawn here —
    synced subtitles are burned by the renderer (IDEA.md 5). We keep only a
    subtle progress pill so each shot's still is visually distinct."""
    w, h = VIDEO_WIDTH, VIDEO_HEIGHT
    c1, c2 = _hex(color1), _hex(color2)
    img = Image.new("RGB", (w, h))
    px = img.load()
    # diagonal gradient
    for y in range(h):
        for x in range(w):
            t = (x / w + y / h) / 2
            r = _lerp(c1[0], c2[0], t)
            g = _lerp(c1[1], c2[1], t)
            b = _lerp(c1[2], c2[2], t)
            px[x, y] = (r, g, b)
    draw = ImageDraw.Draw(img, "RGBA")
    # vignette
    for i in range(60):
        alpha = int(1.2 * (60 - i))
        draw.rectangle([i, i, w - i, h - i], outline=(0, 0, 0, alpha))
    # progress pill
    draw.text((w - 140, 60), f"{idx}/{total}", font=_font(40),
              fill=(255, 255, 255, 200), anchor="mm")
    return img


def _wrap(text: str, n: int) -> list[str]:
    words = list(text)
    out, cur = [], ""
    for ch in words:
        cur += ch
        if len(cur) >= n:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out[:3]


def render_free_frame(shot, idx: int, total: int, out_path) -> str:
    color1, color2, _ = shot["theme"]
    img = gradient_frame(color1, color2, shot.get("caption", ""), idx, total)
    img.save(out_path)
    return out_path


def render_runway(shot, out_path) -> str:
    """Generate a B-roll clip via Runway (returns a video path)."""
    resp = httpx.post(
        "https://api.runwayml.com/v1/generate",
        headers={"Authorization": f"Bearer {RUNWAY_API_KEY}"},
        json={"prompt": shot["visual_prompt"], "duration": 4},
        timeout=180,
    )
    resp.raise_for_status()
    url = resp.json().get("video_url")
    clip = httpx.get(url, timeout=120).content
    out_path.write_bytes(clip)
    return out_path


def render_shot_frame(shot, idx: int, total: int, out_path) -> str:
    if USE_RUNWAY:
        try:
            return render_runway(shot, out_path)
        except Exception:
            pass
    return render_free_frame(shot, idx, total, out_path)
