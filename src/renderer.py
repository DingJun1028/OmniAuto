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
import subprocess
from pathlib import Path

from .config import VIDEO_FPS, VIDEO_HEIGHT, VIDEO_WIDTH

_CAP_FONT = "C\\:/Windows/Fonts/msyh.ttc"
# Linux fallback (Debian/Ubuntu + fonts-noto-cjk): Microsoft YaHei won't
# exist there, so the renderer prefers Noto CJK when present.
if not Path(_CAP_FONT).exists():
    for _cand in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(_cand).exists():
            _CAP_FONT = _cand.replace("\\", "/").replace(":", "\\:")
            break
_CAP_OPTS = (
    "fontcolor=white:fontsize=44:box=1:boxcolor=black@0.55:boxborderw=14:"
    "line_spacing=8:alpha=0.95"
)


def audio_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout
        return max(1.0, float(json.loads(out)["format"]["duration"]))
    except Exception:
        # ffprobe missing or failed -> safe fallback duration.
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


def render_final(shot_clips: list[Path], video_out: Path, shots: list[dict]) -> Path:
    if not shot_clips:
        raise RuntimeError("No shots rendered.")
    inputs = []
    for c in shot_clips:
        inputs += ["-i", str(c)]
    n = len(shot_clips)
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
