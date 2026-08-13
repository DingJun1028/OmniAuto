"""Tests for src.brand_verify."""
from __future__ import annotations

import pytest

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from src import brand_verify  # noqa: E402
from src import brand as brand_mod  # noqa: E402


def _shot(**overrides):
    base = {
        "index": 1,
        "narration": brand_mod.BRAND["intro_line"],
        "theme": brand_mod.dna_palette("場景"),
        "visual_prompt": "deep blue gradient with gold light",
        "caption": "",
    }
    base.update(overrides)
    return base


def test_good_shot_passes():
    r = brand_verify.verify_artifact(_shot())
    assert r.passed is True
    assert r.checks["intro_line"] is True
    assert r.checks["dna_palette"] is True
    assert r.checks["forbidden_visuals"] is True


def test_missing_intro_line_in_first_shot_fails():
    r = brand_verify.verify_artifact(_shot(narration="沒有開場白的腳本。"))
    assert r.passed is False
    assert any("intro line" in i for i in r.issues)


def test_non_first_shot_intro_line_is_optional():
    r = brand_verify.verify_artifact(_shot(index=2, narration="後段敘述"))
    assert r.checks.get("intro_line") in (True, None)


def test_forbidden_visual_detected():
    r = brand_verify.verify_artifact(_shot(visual_prompt="藍紫霓虹賽博龐克風格"))
    assert r.passed is False
    assert any("forbidden" in i for i in r.issues)


def test_unknown_theme_tag_fails():
    r = brand_verify.verify_artifact(_shot(theme=("#000", "#fff", "not_a_tag")))
    assert r.checks.get("dna_palette") is False


def test_batch_aggregates_failures():
    shots = [
        _shot(index=1, narration="缺 intro"),
        _shot(index=2, visual_prompt="機器人大腦"),
    ]
    r = brand_verify.verify_batch(shots)
    assert r.passed is False
    assert len(r.issues) >= 2


def test_verify_batch_all_pass():
    shots = [_shot(index=1), _shot(index=2, narration="後段")]
    r = brand_verify.verify_batch(shots)
    assert r.passed is True
