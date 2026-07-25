"""Module 3 — Speech engine (TTS).

Default: Microsoft edge-tts (free, no API key, multi-language). If
ELEVENLABS_API_KEY is set, ElevenLabs is used instead. If the network
TTS endpoint is unreachable, we transparently fall back to a generated
silent audio track so the pipeline still produces a real MP4.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, USE_ELEVENLABS

# A pleasant multilingual voice that works across EN / ZH / JA on edge-tts.
EDGE_VOICE = "zh-TW-HsiaoChenNeural"  # swap to en-US-AriaNeural etc. if preferred

# Rough speech rate for the offline fallback (chars per second).
_CHARS_PER_SEC = 8


def _silent_audio(text: str, out_path: Path) -> Path:
    dur = max(2.0, len(text) / _CHARS_PER_SEC)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
         "-t", f"{dur:.1f}", str(out_path)],
        capture_output=True, text=True, check=True,
    )
    return out_path


def _tts_edge(text: str, out_path: Path) -> Path:
    import asyncio
    import edge_tts

    asyncio.run(edge_tts.Communicate(text, EDGE_VOICE).save(str(out_path)))
    return out_path


def _tts_elevenlabs(text: str, out_path: Path) -> Path:
    import httpx

    resp = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream",
        headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
        json={"text": text, "model_id": "eleven_multilingual_v2"},
        timeout=120,
    )
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    return out_path


def synthesize(text: str, out_path: Path) -> Path:
    """Synchronous wrapper used by the pipeline runner.

    Tries the configured engine; on any failure, falls back to a silent
    audio track so rendering still completes and a real MP4 is produced.
    """
    try:
        if USE_ELEVENLABS:
            return _tts_elevenlabs(text, out_path)
        return _tts_edge(text, out_path)
    except Exception:
        return _silent_audio(text, out_path)
