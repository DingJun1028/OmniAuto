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

    # 1) Brand host signature must appear in first-shot narration/text.
    #    Use substring match on the host signature to allow intro lines that
    #    are followed by additional on-brand content in the same shot.
    signature = "大家好，我是壽司博士"
    text = artifact.get("narration") or artifact.get("text") or ""
    if text and signature not in text:
        if artifact.get("index", 1) == 1:
            res.fail("intro_line", "missing brand intro line in first shot")
        else:
            res.ok("intro_line")
    else:
        res.ok("intro_line")

    # 2) DNA palette mapping: theme must be one of the known DNA themes
    #    OR a parser-produced visual theme tag (free path).
    theme = artifact.get("theme")
    if theme:
        _, _, tag = theme if len(theme) == 3 else (theme[0], theme[0], "")
        valid_tags = {v[2] for v in _brand.DNA_PALETTES.values()}
        valid_tags.add("brand")
        # Parser visual themes (free path) — do not fail brand verify for these.
        valid_tags.update({"cosmos", "ocean", "forest", "fire", "tech", "city", "neutral"})
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
