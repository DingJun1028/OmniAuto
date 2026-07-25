"""Module 5 — Rendering engine (ffmpeg, "code-as-video").

Assembles each shot's audio + background frame into a watchable clip:
  - per-shot duration = audio duration (or 4s fallback)
  - slow ken-burns zoom/pan on the still for motion
  - concat all shots into one MP4
Runs fully headless via ffmpeg; no GPU required (IDEA.md architecture).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import VIDEO_FPS, VIDEO_HEIGHT, VIDEO_WIDTH


def audio_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    ).stdout
    try:
        return max(1.0, float(json.loads(out)["format"]["duration"]))
    except Exception:
        return 4.0


def render_shot_clip(frame: Path, audio: Path, out_clip: Path, idx: int) -> float:
    """Render one shot: zoompan the still frame, pair with the audio, fit duration."""
    dur = audio_duration(audio)
    zoom = 1.08 + (idx % 3) * 0.04  # 1.08 .. 1.16 gentle ken-burns zoom
    vf = (
        f"scale={VIDEO_WIDTH*2}:{VIDEO_HEIGHT*2},"
        f"zoompan=z='min({zoom},1.5)':d=1:x='iw/2':y='ih/2':"
        f"s={VIDEO_WIDTH}x{VIDEO_HEIGHT},"
        f"trim=duration={dur:.2f},setpts=PTS-STARTPTS,"
        f"fade=t=in:st=0:d=0.3,fade=t=out:st={max(0,dur-0.3):.2f}:d=0.3,"
        f"format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", str(frame),
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
