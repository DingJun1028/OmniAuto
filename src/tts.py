"""Module 3 — Speech engine (TTS).

Default: Microsoft edge-tts (free, no API key, multi-language). If
ELEVENLABS_API_KEY is set, ElevenLabs is used instead. If the network
TTS endpoint is unreachable, we transparently fall back to a generated
silent audio track so the pipeline still produces a real MP4.

Each synthesize() call returns a tuple:
    (audio_path, boundaries, is_silent)
where `boundaries` is a list of word-level timings:
    {"start": float_seconds, "end": float_seconds, "text": str}
These are consumed by the renderer to burn synced captions (IDEA.md 5).
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from .config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, USE_ELEVENLABS

# A pleasant multilingual voice that works across EN / ZH / JA on edge-tts.
EDGE_VOICE = "zh-TW-HsiaoChenNeural"  # swap to en-US-AriaNeural etc. if preferred

# Rough speech rate for the offline fallback (chars per second).
_CHARS_PER_SEC = 8

_TICKS_PER_SEC = 10_000_000  # edge-tts boundary offsets are in 100-ns ticks


def _silent_audio(text: str, out_path: Path) -> Path:
    dur = max(2.0, len(text) / _CHARS_PER_SEC)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
         "-t", f"{dur:.1f}", str(out_path)],
        capture_output=True, text=True, check=True,
    )
    return out_path


def _tts_edge(text: str, out_path: Path):
    """Stream audio + capture word boundaries. Returns (Path, boundaries)."""
    import edge_tts

    boundaries: list[dict] = []

    async def run():
        comm = edge_tts.Communicate(text, EDGE_VOICE, boundary="WordBoundary")
        with open(out_path, "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    off = int(chunk["offset"])
                    dur = int(chunk["duration"])
                    boundaries.append({
                        "start": off / _TICKS_PER_SEC,
                        "end": (off + dur) / _TICKS_PER_SEC,
                        "text": chunk["text"],
                    })

    asyncio.run(run())
    return out_path, boundaries


def _tts_elevenlabs(text: str, out_path: Path):
    import httpx

    resp = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream",
        headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
        json={"text": text, "model_id": "eleven_multilingual_v2"},
        timeout=120,
    )
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    return out_path, []  # ElevenLabs word timing not captured in free tier


def synthesize(text: str, out_path: Path):
    """Return (audio_path, boundaries, is_silent).

    Tries the configured engine; on any failure, falls back to a silent
    audio track (empty boundaries) so rendering still completes.
    """
    try:
        if USE_ELEVENLABS:
            path, bounds = _tts_elevenlabs(text, out_path)
        else:
            path, bounds = _tts_edge(text, out_path)
        return path, bounds, False
    except Exception:
        _silent_audio(text, out_path)
        return out_path, [], True
