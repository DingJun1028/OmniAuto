"""Module 3 — Speech engine (TTS).

Default: Microsoft edge-tts (free, no API key, multi-language). If
ELEVENLABS_API_KEY is set, ElevenLabs is used instead. If AZURE_VOICE is set,
edge-tts uses that Azure neural voice directly (no REST key needed — edge-tts
speaks the voice natively, this is what "Azure TTS V1" means in MoneyPrinterTurbo).

If the configured engine is unreachable, we transparently fall back to a
generated silent audio track so the pipeline still produces a real MP4.

Each synthesize() call returns a tuple:
    (audio_path, boundaries, is_silent)
where `boundaries` is a list of word-level timings:
    {"start": float_seconds, "end": float_seconds, "text": str}
These are consumed by the renderer to burn synced captions (IDEA.md 5).

MoneyPrinterTurbo compatibility:
- synthesize_with_voice() accepts an explicit `voice` param so the MPT UI can
  override AZURE_VOICE / EDGE_VOICE at submission time.
- style_name + style_text are forwarded to edge-tts for Azure voices that
  support them (e.g., zh-CN-XiaoxiaoNeural with "sad" style).
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from .config import (
    ELEVENLABS_API_KEY,
    ELEVENLABS_VOICE_ID,
    USE_ELEVENLABS,
    AZURE_VOICE,
    AZURE_VOICE_STYLE,
    AZURE_STYLE_TEXT,
    USE_AZURE,
    EDGE_VOICE,
    EDGE_VOICE_EN,
    log,
)

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


def _detect_voice(text: str, voice: str | None) -> str:
    """Pick a voice: explicit override > Azure configured > language heuristic.

    If no voice is specified, we sniff the script for CJK characters and pick
    the matching edge-tts neural voice automatically (same behaviour as MPT's
    language auto-detection toggle).
    """
    if voice:
        return voice
    if USE_AZURE and AZURE_VOICE:
        return AZURE_VOICE
    # Auto-detect: if script contains CJK, use the Chinese voice; else English.
    if any("\u4e00" <= c <= "\u9fff" for c in text):
        return EDGE_VOICE  # zh-TW-HsiaoChenNeural by default
    return EDGE_VOICE_EN


def _tts_edge(text: str, out_path: Path, voice: str | None = None,
              style_name: str | None = None, style_text: str | None = None):
    """Stream audio + capture word boundaries via edge-tts.

    Returns (Path, boundaries). For Azure voices that support style, passes
    style_name and style_text through to edge-tts's `Communicate`.
    """
    import edge_tts

    boundaries: list[dict] = []
    chosen_voice = _detect_voice(text, voice)

    async def run():
        kwargs = {"voice": chosen_voice, "boundary": "WordBoundary"}
        comm = edge_tts.Communicate(text, **kwargs)

        # For Azure neural voices that support style, inject style params.
        if style_name:
            comm.configure_style(style_name, style_text or "")

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
    return synthesize_with_voice(text, out_path)


def synthesize_with_voice(text: str, out_path: Path, voice: str | None = None,
                          style_name: str | None = None,
                          style_text: str | None = None):
    """Like synthesize() but accepts an explicit voice override.

    This is the entry point MoneyPrinterTurbo webhook payloads use to pass
    the user's chosen voice (e.g., "zh-TW-HsiaoChenNeural").
    """
    try:
        if USE_ELEVENLABS:
            log.info("tts: using elevenlabs")
            path, bounds = _tts_elevenlabs(text, out_path)
        else:
            log.info("tts: using edge-tts (free) voice=%s",
                     _detect_voice(text, voice))
            path, bounds = _tts_edge(text, out_path, voice=voice,
                                     style_name=style_name or AZURE_VOICE_STYLE,
                                     style_text=style_text or AZURE_STYLE_TEXT)
        return path, bounds, False
    except Exception as e:
        log.warning("tts: engine failed (%s); falling back to silent track", e)
        _silent_audio(text, out_path)
        return out_path, [], True


def _fmt_srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(boundaries: list[dict]) -> str:
    """Build a karaoke-style SRT string from word boundaries.

    Each cue highlights the currently-spoken word (wrapped in <b>) over the
    cumulative spoken text, useful for soft subtitles or an alternative to the
    burned-in captions (IDEA.md 5). Returns "" when there are no boundaries.
    """
    if not boundaries:
        return ""
    words = [b["text"] for b in boundaries]
    cues = []
    for i, w in enumerate(boundaries):
        seg = ("").join(words[:i]) + "<b>" + words[i] + "</b>" + ("".join(words[i + 1:]))
        cue = f"{i + 1}\n{_fmt_srt_time(w['start'])} --> {_fmt_srt_time(w['end'])}\n{seg}"
        cues.append(cue)
    return "\n\n".join(cues) + "\n"