"""Module 2 — Text parsing (LLM Brain).

Turns a plain-text script into a structured list of "shots":
  { index, narration, visual_prompt, caption }

Default: a deterministic built-in parser that splits the script into
sentences, groups a configurable number of sentences per shot, and
derives a visual prompt from keywords. If OPENAI_API_KEY is set, the
script is parsed by GPT-4o into a richer shot array instead.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from typing import Optional

import httpx

from .config import OPENAI_API_KEY, OPENAI_MODEL, USE_OPENAI
from . import brand

# Simple keyword -> visual style mapping so the free path produces
# semantically appropriate background tints without any AI call.
THEME_KEYWORDS = {
    "space": ("#0b1026", "#1b2a6b", "cosmos"),
    "宇宙": ("#0b1026", "#1b2a6b", "cosmos"),
    "ocean": ("#021b2e", "#0a6e8c", "ocean"),
    "海洋": ("#021b2e", "#0a6e8c", "ocean"),
    "forest": ("#0c2417", "#1f6b3b", "forest"),
    "森林": ("#0c2417", "#1f6b3b", "forest"),
    "fire": ("#2a0a05", "#b3361a", "fire"),
    "火": ("#2a0a05", "#b3361a", "fire"),
    "tech": ("#03121f", "#0b6fa3", "tech"),
    "科技": ("#03121f", "#0b6fa3", "tech"),
    "city": ("#10131a", "#3a4a63", "city"),
    "城市": ("#10131a", "#3a4a63", "city"),
}


@dataclass
class Shot:
    index: int
    narration: str
    visual_prompt: str
    caption: str
    theme: tuple  # (color1, color2, name)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["theme"] = list(self.theme)
        return d


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    parts = re.split(r"(?<=[。.!?！？])\s*", text)
    return [p.strip() for p in parts if p.strip()]


def _detect_theme(text: str) -> tuple:
    lower = text.lower()
    for kw, theme in THEME_KEYWORDS.items():
        if kw in lower:
            return theme
    return ("#10131a", "#2a3a5c", "neutral")


def parse_free(script: str, shots_per_group: int = 2) -> list[Shot]:
    sentences = _split_sentences(script)
    if not sentences:
        sentences = [script]
    shots: list[Shot] = []
    theme = _detect_theme(script)
    for i in range(0, len(sentences), shots_per_group):
        group = sentences[i : i + shots_per_group]
        narration = " ".join(group)
        caption = group[0][:40]
        prompt = f"Cinematic wide shot, {theme[2]} mood, soft light: {narration[:120]}"
        shots.append(
            Shot(
                index=len(shots) + 1,
                narration=narration,
                visual_prompt=prompt,
                caption=caption,
                theme=theme,
            )
        )
    return shots


_OPENAI_SYSTEM = (
    "You are a video shot planner. Given a script, return a JSON array of shots. "
    "Each shot: {index:int, narration:str (the spoken line), visual_prompt:str "
    "(English image prompt), caption:str (short on-screen text)}. Keep 1-3 "
    "sentences of narration per shot. Respond with JSON only."
)


def parse_openai(script: str) -> list[Shot]:
    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json={
            "model": OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": _OPENAI_SYSTEM},
                {"role": "user", "content": script},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()["choices"][0]["message"]["content"]
    arr = json.loads(data)
    if isinstance(arr, dict):
        arr = arr.get("shots", arr.get("results", []))
    theme = _detect_theme(script)
    return [
        Shot(
            index=i + 1,
            narration=s.get("narration", ""),
            visual_prompt=s.get("visual_prompt", ""),
            caption=s.get("caption", ""),
            theme=theme,
        )
        for i, s in enumerate(arr)
    ]


def parse_dna_script(script: str) -> list[Shot] | None:
    """If the script uses 壽司博士 DNA markers (【場景】【衝突】【洞察】【方法】【反思】),
    produce one on-brand shot per beat. Returns None when no markers are found."""
    beats = brand.parse_dna(script)
    if not beats:
        return None
    shots: list[Shot] = []
    for label, text in beats:
        theme = brand.dna_palette(label)
        caption = text[:40]
        prompt = (
            f"On-brand {theme[2]} visual for 壽司博士 Dr. Source: "
            f"{text[:120]} — no neon, no robot-brain, no floating data clichés"
        )
        shots.append(
            Shot(
                index=len(shots) + 1,
                narration=text,
                visual_prompt=prompt,
                caption=caption,
                theme=theme,
            )
        )
    return shots


def parse_script(script: str) -> list[Shot]:
    if not script or not script.strip():
        raise ValueError("script must not be empty")
    # 1) 壽司博士 brand DNA markers take priority (structured, on-brand).
    dna = parse_dna_script(script)
    if dna:
        return dna
    if USE_OPENAI:
        try:
            return parse_openai(script)
        except Exception:
            # Fall back gracefully to the free parser if the API call fails.
            pass
    return parse_free(script)
