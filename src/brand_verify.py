"""Module — Brand consistency validator (5T Transparent + Tangible).

Validates generated artifacts against the sushi_dr brand preset:
- intro_line presence
- DNA palette mapping for each shot
- no forbidden AI visuals
"""
from __future__ import annotations

from . import brand as _brand


class BrandVerifyResult:
    def __init__(self) -> None:
        self.passed: bool = True
        self.issues: list[str] = []
        self.checks: dict[str, bool] = {}

    def fail(self, key: str, msg: str) -> None:
        self.passed = False
        self.issues.append(msg)
        self.checks[key] = False

    def ok(self, key: str) -> None:
        self.checks[key] = True


def verify_artifact(
    artifact: dict,
    preset: str = "sushi_dr",
) -> BrandVerifyResult:
    """Validate one produced artifact (video / script / metadata)."""
    res = BrandVerifyResult()
    b = _brand.get_brand(preset)

    # 1) Intro line must be present in narration/text when provided.
    text = artifact.get("narration") or artifact.get("text") or ""
    if text and b["intro_line"] not in text:
        # Intro line may legitimately appear only in the first shot; allow if
        # the artifact is a later shot (index > 1).
        if artifact.get("index", 1) == 1:
            res.fail("intro_line", "missing brand intro line in first shot")
        else:
            res.ok("intro_line")
    else:
        res.ok("intro_line")

    # 2) DNA palette mapping: theme must be one of the known DNA themes.
    theme = artifact.get("theme")
    if theme:
        _, _, tag = theme if len(theme) == 3 else (theme[0], theme[0], "")
        valid_tags = {v[2] for v in _brand.DNA_PALETTES.values()}
        valid_tags.add("brand")
        if tag not in valid_tags:
            res.fail("dna_palette", f"unknown theme tag: {tag}")
        else:
            res.ok("dna_palette")
    else:
        res.fail("dna_palette", "shot missing theme")

    # 3) Forbidden AI visuals must never appear in prompts / captions.
    forbidden = [w.lower() for w in b.get("forbidden_ai_visuals", [])]
    candidate = " ".join(
        str(artifact.get(k, "")) for k in ("narration", "text", "caption", "visual_prompt")
    ).lower()
    hits = [w for w in forbidden if w and w in candidate]
    if hits:
        res.fail("forbidden_visuals", f"contains forbidden visuals: {hits}")
    else:
        res.ok("forbidden_visuals")

    return res


def verify_batch(shots: list[dict], preset: str = "sushi_dr") -> BrandVerifyResult:
    """Validate a list of shots and aggregate the result."""
    agg = BrandVerifyResult()
    for s in shots:
        r = verify_artifact(s, preset=preset)
        if not r.passed:
            agg.passed = False
            agg.issues.extend(r.issues)
        agg.checks.update(r.checks)
    return agg
