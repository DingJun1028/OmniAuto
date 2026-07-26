"""Module 5 — Rendering engine (ffmpeg, "code-as-video").

Assembles each shot's audio + background media into a watchable clip:
  - media may be a still PNG (free gradient) or an MP4 (Runway B-roll)
  - stills get a slow ken-burns zoom/pan; videos are trimmed/faded
  - captions burned as word-synced subtitles via ffmpeg drawtext
  - concat all shots into one MP4
Runs fully headless via ffmpeg; no GPU required.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from .config import VIDEO_FPS, VIDEO_HEIGHT, VIDEO_WIDTH, FONT_PATH, log

# Caption font for ffmpeg drawtext — reuse the single resolved CJK font.
# drawtext needs a POSIX-style path with ':' escaped (ffmpeg filter syntax).
_CAP_FONT = str(FONT_PATH).replace("\\", "/").replace(":", "\\:")
_CAP_OPTS = (
    "fontcolor=white:fontsize=44:box=1:boxcolor=black@0.55:boxborderw=14:"
    "line_spacing=8:alpha=0.95"
)


def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))


def _title_font(size: int):
    """Reuse the CJK-capable font resolution from visuals for on-brand slates."""
    from . import visuals

    return visuals._font(size)


_CAP_TITLE = _CAP_FONT  # same family, used by make_brand_intro via _title_font


def audio_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout
        return max(1.0, float(json.loads(out)["format"]["duration"]))
    except Exception as e:
        # ffprobe missing or failed -> safe fallback duration.
        log.warning("audio_duration: ffprobe failed (%s); using 4.0s fallback", e)
        return 4.0


def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace("'", "\\'")
            .replace(":", "\\:").replace("%", "\\%").replace(",", "\\,"))


def _caption_filter(boundaries: list[dict]) -> str:
    """Karaoke-style captions: each word appears during its spoken window."""
    if not boundaries:
        return ""
    filters: list[str] = []
    for i, w in enumerate(boundaries):
        word = w["text"].strip()
        if not word:
            continue
        line = "".join(b["text"] for b in boundaries[: i + 1]).strip()
        start, end = w["start"], w["end"]
        enable = f"between(t\\,{start:.3f}\\,{end:.3f})"
        filters.append(
            f"drawtext=fontfile='{_CAP_FONT}':text='{_esc(line)}':"
            f"{_CAP_OPTS}:x=(w-text_w)/2:y=h-text_h-60:enable='{enable}'"
        )
    return ",".join(filters)


def render_shot_clip(media: Path, is_video: bool, audio: Path, out_clip: Path,
                     idx: int, boundaries: list[dict] | None = None) -> float:
    dur = audio_duration(audio)
    cap_vf = _caption_filter(boundaries or [])

    if is_video:
        # Runway B-roll: trim to narration length, reset PTS (so trim works on
        # non-zero-start streams), scale/pad, fade, then captions.
        base_vf = (
            f"trim=duration={dur:.2f},setpts=PTS-STARTPTS,"
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
            f"fade=t=in:st=0:d=0.3,fade=t=out:st={max(0,dur-0.3):.2f}:d=0.3,"
            f"format=yuv420p"
        )
    else:
        zoom = 1.08 + (idx % 3) * 0.04
        base_vf = (
            f"scale={VIDEO_WIDTH*2}:{VIDEO_HEIGHT*2},"
            f"zoompan=z='min({zoom},1.5)':d=1:x='iw/2':y='ih/2':"
            f"s={VIDEO_WIDTH}x{VIDEO_HEIGHT},"
            f"trim=duration={dur:.2f},setpts=PTS-STARTPTS,"
            f"fade=t=in:st=0:d=0.3,fade=t=out:st={max(0,dur-0.3):.2f}:d=0.3,"
            f"format=yuv420p"
        )

    vf = base_vf + ("," + cap_vf) if cap_vf else base_vf
    # `-loop 1` only for still images; videos are read once.
    media_input = ["-loop", "1", "-i", str(media)] if not is_video else ["-i", str(media)]
    cmd = [
        "ffmpeg", "-y",
        *media_input,
        "-i", str(audio), "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-vf", vf,
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{dur:.2f}", "-shortest", str(out_clip),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return dur


def make_brand_intro(preset: str = "sushi_dr", out: Path | None = None) -> Path:
    """Generate the 壽司博士 Dr. Source opening slate (深藍→暖金, name + tagline).

    Returns a short silent MP4 used as the video's first beat so every clip
    carries the channel's visual identity without extra authoring.
    """
    from . import brand as _brand

    b = _brand.get_brand(preset)
    if out is None:
        out = Path(tempfile.mkdtemp()) / "brand_intro.mp4"
    out = Path(out)
    w, h = VIDEO_WIDTH, VIDEO_HEIGHT
    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        img = Image.new("RGB", (w, h), _hex(b["palette"]["deep_blue"]))
        d = ImageDraw.Draw(img, "RGBA")
        d.rectangle([0, h - 180, w, h], fill=_hex(b["palette"]["warm_gold"]))
        d.text((w // 2, h // 2 - 40), b["name"], font=_title_font(54),
               fill=(243, 237, 225), anchor="mm")
        d.text((w // 2, h // 2 + 30), b["tagline"], font=_title_font(30),
               fill=(16, 36, 63), anchor="mm")
        img.save(tmp)
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", tmp,
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "2.4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(out),
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out


def render_final(shot_clips: list[Path], video_out: Path,
                 shots: list[dict], brand_preset: str | None = None) -> Path:
    if not shot_clips:
        raise RuntimeError("No shots rendered.")
    # `shots` is informational but also a guard: the caller passes the
    # post-ordering shot dicts, so a mismatch against the clip list signals a
    # pipeline bug rather than silently producing a wrong-length video.
    if shots is not None and len(shots) and len(shots) != len(shot_clips):
        log.warning("render_final: %d shot dicts vs %d clips — concat uses the "
                    "clips as given", len(shots), len(shot_clips))
    video_out = Path(video_out)
    inputs = []
    for c in shot_clips:
        inputs += ["-i", str(c)]
    n = len(shot_clips)
    if brand_preset:
        try:
            intro = make_brand_intro(brand_preset, out=video_out.parent / "brand_intro.mp4")
            inputs = ["-i", str(intro)] + inputs
            n += 1
        except Exception:
            pass  # intro is a nicety; never fail the render because of it
    concat = "".join(f"[{i}:v][{i}:a]" for i in range(n))
    cmd = [
        "ffmpeg", "-y", *inputs, "-filter_complex",
        f"{concat}concat=n={n}:v=1:a=1[outv][outa]",
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(video_out),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return video_out
