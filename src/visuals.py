"""Module 4 — Visuals.

Default (free): generate a smooth two-color gradient background with a
subtle vignette + progress pill using Pillow. The ffmpeg renderer then
adds motion (ken-burns) and burns synced captions onto the still.

If RUNWAY_API_KEY is set, each shot's visual_prompt is sent to Runway to
produce an AI-generated B-roll clip instead of the gradient still.
"""
from __future__ import annotations

import httpx
from PIL import Image, ImageDraw, ImageFont

from .config import RUNWAY_API_KEY, USE_RUNWAY, VIDEO_WIDTH, VIDEO_HEIGHT


def _font(size: int):
    for cand in [
        "C:/Windows/Fonts/msyh.ttc",   # Microsoft YaHei (zh)
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/NotoSansCJK-Regular.ttc",
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


def gradient_frame(color1: str, color2: str, idx: int, total: int) -> Image.Image:
    """Render one 16:9 gradient background + progress pill (no caption text —
    synced subtitles are burned by the renderer, IDEA.md 5)."""
    w, h = VIDEO_WIDTH, VIDEO_HEIGHT
    c1, c2 = _hex(color1), _hex(color2)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (x / w + y / h) / 2
            r = _lerp(c1[0], c2[0], t)
            g = _lerp(c1[1], c2[1], t)
            b = _lerp(c1[2], c2[2], t)
            px[x, y] = (r, g, b)
    draw = ImageDraw.Draw(img, "RGBA")
    for i in range(60):
        alpha = int(1.2 * (60 - i))
        draw.rectangle([i, i, w - i, h - i], outline=(0, 0, 0, alpha))
    draw.text((w - 140, 60), f"{idx}/{total}", font=_font(40),
              fill=(255, 255, 255, 200), anchor="mm")
    return img


def render_free_frame(shot: dict, idx: int, total: int, out_path) -> str:
    color1, color2, _ = shot["theme"]
    img = gradient_frame(color1, color2, idx, total)
    img.save(out_path)
    return out_path


def generate_broll(shot: dict, out_path) -> str:
    """Generate an AI B-roll clip via Runway (text-to-video). Returns video path.

    NOTE: untested without RUNWAY_API_KEY. Runway's API is async; this is a
    best-effort implementation — adjust endpoint/poll shape to the current
    Runway API. Raises on any failure so the pipeline falls back to the
    gradient still.
    """
    prompt = shot.get("visual_prompt", "")
    headers = {
        "Authorization": f"Bearer {RUNWAY_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "aistation/0.1",
    }
    # 1) submit generation task
    r = httpx.post(
        "https://api.runwayml.com/v1/text_to_video",
        headers=headers,
        json={"prompt": prompt, "duration": 4, "watermark": False},
        timeout=60,
    )
    if r.status_code == 410:
        # Endpoint/version may have changed; surface it instead of silent fail.
        raise RuntimeError(f"Runway API returned 410 (Gone): {r.text[:200]}")
    r.raise_for_status()
    body = r.json()
    task_id = body.get("id") or body.get("taskId")
    if not task_id:
        url = body.get("video_url") or (body.get("output") or [None])[0]
        if url:
            out_path.write_bytes(httpx.get(url, headers=headers, timeout=120).content)
            return out_path
        raise RuntimeError("Runway did not return a task id or url")
    # 2) poll until done
    for _ in range(60):
        t = httpx.get(f"https://api.runwayml.com/v1/tasks/{task_id}", headers=headers, timeout=30)
        t.raise_for_status()
        data = t.json()
        status = data.get("status")
        if status == "SUCCEEDED":
            url = (data.get("output") or [None])[0]
            if url:
                out_path.write_bytes(httpx.get(url, headers=headers, timeout=120).content)
                return out_path
            raise RuntimeError("Runway task succeeded but produced no output url")
        if status == "FAILED":
            raise RuntimeError(f"Runway task failed: {data}")
    raise RuntimeError("Runway task timed out")


def render_shot_media(shot: dict, idx: int, total: int, png_path, mp4_path) -> tuple:
    """Return (media_path, is_video). Uses Runway B-roll when enabled, else gradient."""
    if USE_RUNWAY:
        try:
            return generate_broll(shot, mp4_path), True
        except Exception:
            pass
    render_free_frame(shot, idx, total, png_path)
    return png_path, False
