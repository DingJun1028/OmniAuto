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

from .config import (
    FONT_PATH,
    RUNWAY_API_KEY,
    USE_RUNWAY,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
    log,
)


def _font(size: int):
    # Converged to the single CJK-capable font resolved in config.FONT_PATH.
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))


def gradient_frame(color1: str, color2: str, idx: int, total: int) -> Image.Image:
    """Render one 16:9 gradient background + progress pill (no caption text —
    synced subtitles are burned by the renderer, IDEA.md 5).

    The gradient is computed as a numpy diag blend (no per-pixel Python loop),
    so even 720p frames build in a few milliseconds.
    """
    import numpy as np

    w, h = VIDEO_WIDTH, VIDEO_HEIGHT
    # Memory-light: 1-D broadcasts (ogrid) + float32 instead of a full 2-D
    # float64 meshgrid. Peak working set drops from ~3 arrays of h*w*8 bytes to
    # a single h*w*4 float plus the uint8 output, so it renders on RAM-starved
    # machines instead of raising MemoryError.
    xs = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :]   # 1 x w
    ys = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]   # h x 1
    t = ((xs + ys) / 2.0).astype(np.float32)                  # h x w, 4 bytes/px
    c1 = np.array(_hex(color1), dtype=np.float32)
    c2 = np.array(_hex(color2), dtype=np.float32)
    buf = (c1[None, None, :] * (1.0 - t[..., None])
           + c2[None, None, :] * t[..., None]).astype("uint8")
    img = Image.fromarray(buf, "RGB")
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
    """Generate an AI B-roll clip via Runway text-to-video (current API).

    Uses POST /v1/text_to_video with model + promptText, then polls
    GET /v1/tasks/{id} until SUCCEEDED (output is a list of URLs). Raises on
    any failure so the pipeline falls back to the gradient still.
    """
    prompt = shot.get("visual_prompt", "")
    model = shot.get("runway_model", "gen3a_turbo")
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
        json={
            "model": model,
            "promptText": prompt,
            "ratio": f"{VIDEO_WIDTH}:{VIDEO_HEIGHT}",
            "duration": 5,
            "watermark": False,
        },
        timeout=60,
    )
    if r.status_code == 410:
        # Endpoint/version may have changed; surface it instead of silent fail.
        raise RuntimeError(f"Runway API returned 410 (Gone): {r.text[:200]}")
    r.raise_for_status()
    body = r.json()
    task_id = body.get("id") or body.get("taskId") or body.get("task_uuid")
    if not task_id:
        # Some shapes return the url inline.
        url = body.get("video_url") or (body.get("output") or [None])[0]
        if url:
            out_path.write_bytes(httpx.get(url, headers=headers, timeout=120).content)
            return out_path
        raise RuntimeError("Runway did not return a task id or url")
    # 2) poll until done
    for _ in range(90):
        t = httpx.get(
            f"https://api.runwayml.com/v1/tasks/{task_id}", headers=headers, timeout=30
        )
        t.raise_for_status()
        data = t.json()
        status = data.get("status")
        if status == "SUCCEEDED":
            outs = data.get("output") or []
            url = outs[0] if outs else (data.get("video_url") or data.get("url"))
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
            log.info("visuals: generating Runway B-roll for shot %d", idx)
            return generate_broll(shot, mp4_path), True
        except Exception as e:
            log.warning("visuals: Runway failed (%s); falling back to gradient", e)
    render_free_frame(shot, idx, total, png_path)
    return png_path, False
