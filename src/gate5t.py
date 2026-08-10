"""5T 驗證閘 (Chapter 10 best-practice enforcement).

Implements the 5T verification gate from the OA-Team soul canon as a
reusable, testable function so every AI Station artifact must pass
Traceable / Trackable / Tangible / Transparent / Trustworthy before it is
released. On success the artifact is Hash-Locked and frozen (Object.freeze
equivalent: a namedtuple / frozen dataclass so callers cannot mutate it).

Free-local by default — no network, no cloud keys. The Trustworthy lock is
a SHA-256 digest over the canonical JSON of the artifact, matching the
soul canon §一 1.2 "Hash Lock + Object.freeze()".
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from . import config

log = config.log


@dataclass(frozen=True)
class LockedArtifact:
    """A frozen, Hash-Locked artifact. Immutable after creation (5T Trustworthy)."""

    uuid: str
    kind: str
    payload: str  # canonical JSON of the artifact
    hash_lock: str
    checks: Dict[str, bool]


def _canonical(obj: Any) -> str:
    """Deterministic JSON so the same logical artifact always yields the same hash."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class GateReport:
    passed: bool = False
    checks: Dict[str, bool] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def verify_5t(
    artifact: Dict[str, Any],
    *,
    require_source_origin: bool = True,
    require_lifecycle_hooks: bool = True,
    require_ui_feedback: bool = False,
    require_zero_hallucination: bool = True,
) -> GateReport:
    """Run the 5T verification gate over an artifact dict.

    Artifact contract (keys):
      - uuid:            unique id (Traceable root)
      - source_origin:  first-cause origin tag (Traceable)
      - lifecycle_hooks:non-empty list of lifecycle events (Trackable)
      - ui_feedback:     optional user-feedback evidence (Tangible)
      - transparent_audit: bool / evidence of zero-hallucination audit (Transparent)
      - frozen:          bool, artifact is immutable once locked (Trustworthy)

    Returns a GateReport; callers should only release when `passed` is True.
    """
    report = GateReport(checks={})
    a = artifact or {}

    # --- Traceable ---
    has_uuid = bool(a.get("uuid"))
    has_origin = bool(a.get("source_origin")) if require_source_origin else True
    report.checks["Traceable"] = has_uuid and has_origin
    if require_source_origin and not a.get("source_origin"):
        report.missing.append("source_origin")
    if not has_uuid:
        report.missing.append("uuid")
    # sources: 多源陣列 (>=4 建議, 單源仍過欄位閘但權威閘需多源)
    if "sources" in a and not isinstance(a.get("sources"), (list, tuple)):
        report.errors.append("sources must be a list")

    # --- Trackable ---
    hooks = a.get("lifecycle_hooks")
    has_hooks = bool(hooks) if require_lifecycle_hooks else True
    report.checks["Trackable"] = has_hooks
    if require_lifecycle_hooks and not hooks:
        report.missing.append("lifecycle_hooks")

    # --- Tangible (optional gate by caller) ---
    if require_ui_feedback:
        report.checks["Tangible"] = bool(a.get("ui_feedback"))
        if not a.get("ui_feedback"):
            report.missing.append("ui_feedback")
    else:
        report.checks["Tangible"] = True  # not blocking unless requested

    # --- Transparent ---
    if require_zero_hallucination:
        report.checks["Transparent"] = bool(a.get("transparent_audit"))
        if not a.get("transparent_audit"):
            report.missing.append("transparent_audit")
    else:
        report.checks["Transparent"] = True

    # --- Trustworthy ---
    report.checks["Trustworthy"] = bool(a.get("frozen"))
    if not a.get("frozen"):
        report.missing.append("frozen")

    report.passed = all(report.checks.values())
    return report


def lock_artifact(
    artifact: Dict[str, Any],
    kind: str = "artifact",
) -> LockedArtifact:
    """Validate through the 5T gate, then Hash-Lock + freeze.

    Raises ValueError if the gate fails (never release an unverified artifact).
    The returned LockedArtifact is a frozen dataclass — mutating it raises
    FrozenInstanceError, enforcing the Trustworthy prohibition.
    """
    report = verify_5t(artifact)
    if not report.passed:
        msg = f"5T gate failed: missing {report.missing}"
        log.error("gate5t.lock_artifact rejected: %s", msg)
        raise ValueError(msg)

    canonical = _canonical(artifact)
    digest = _sha256(canonical)
    locked = LockedArtifact(
        uuid=str(artifact.get("uuid", "")),
        kind=kind,
        payload=canonical,
        hash_lock=digest,
        checks=dict(report.checks),
    )
    log.info("gate5t: artifact %s locked (hash=%s…)", locked.uuid, digest[:12])
    return locked


def verify_locked(locked: LockedArtifact) -> bool:
    """Re-verify a LockedArtifact's integrity (tamper detection)."""
    return _sha256(locked.payload) == locked.hash_lock


# ---------------------------------------------------------------------------
# Single Source of Truth alignment (esggo oa-framework IComponentCore + hashlock)
# ---------------------------------------------------------------------------
# esggo 是 5T 協議的權威真相源 (packages/oa-framework/src/core/types.ts:
# IComponentCore { uuid, version, timestamp, evidence } + OATaskResult.hashLock).
# This adapter maps an aistation LockedArtifact onto that shape so both
# runtimes share ONE 5T contract. Network calls are best-effort: if the
# esggo hashlock endpoint is unreachable, we fall back to the local digest,
# exactly like the AI Station "優雅回落" rule (§九 / §22).
ESGO_HASHLOCK_URL = os.getenv("ESGO_HASHLOCK_URL", "").rstrip("/")


def to_component_core(locked: LockedArtifact, version: str = "1.0.0") -> dict:
    """Project a LockedArtifact into esggo's IComponentCore shape.

    Returns the canonical JSON contract shared with OA-Team 30 swarm:
      { uuid, version, timestamp, evidence:{ hash_lock, checks }, hashLock }
    """
    return {
        "uuid": locked.uuid,
        "version": version,
        "timestamp": int(time.time()),
        "evidence": {
            "hash_lock": locked.hash_lock,
            "checks": locked.checks,
            "kind": locked.kind,
        },
        # esggo OATaskResult naming
        "hashLock": locked.hash_lock,
    }


def verify_via_esggo(locked: LockedArtifact, version: str = "1.0.0") -> dict:
    """Verify a locked artifact against esggo's unified 5T endpoint (single source).

    Calls esggo `/api/verify-5t` so the 5T verdict comes from ONE place
    (oa-framework / five-t-protocol), not a duplicated Python re-implementation.
    The artifact's 5T fields are mapped to the endpoint contract; esggo returns
    the authoritative {pass, status, score, hashLock}.

    Returns {"ok": bool, "source": "esggo"|"local", "detail": str}.
    Best-effort: on any network failure, falls back to local hash check so
    the pipeline never blocks on the gateway.
    """
    if not ESGO_HASHLOCK_URL:
        ok = verify_locked(locked)
        return {"ok": ok, "source": "local", "detail": "ESGO_HASHLOCK_URL unset; local verify"}
    # Map the locked artifact's 5T checks to esggo's verify-5t contract.
    # sources: 多源陣列 (>=4 才過 esggo traceable 權威閘); fallback 單源.
    try:
        _art = json.loads(locked.payload) if isinstance(locked.payload, str) else locked.payload
    except Exception:
        _art = {}
    src_origin = _art.get("source_origin", "") if isinstance(_art, dict) else ""
    sources = _art.get("sources", []) if isinstance(_art, dict) else []
    if not sources and src_origin:
        sources = [src_origin]
    payload = {
        "source_origin": src_origin,
        "sources": sources,
        "lifecycle_hooks": ["locked"] if locked.checks.get("Trackable") else [],
        "ui_feedback": locked.checks.get("Tangible", False),
        "transparent_audit": locked.checks.get("Transparent", False),
        "frozen": locked.checks.get("Trustworthy", False),
    }
    try:
        resp = httpx.post(
            f"{ESGO_HASHLOCK_URL}/api/verify-5t",
            json=payload,
            timeout=10.0,
        )
        if resp.status_code == 200:
            body = resp.json()
            return {"ok": bool(body.get("pass", False)), "source": "esggo", "detail": str(body)}
        return {"ok": verify_locked(locked), "source": "local", "detail": f"esggo HTTP {resp.status_code}; local fallback"}
    except Exception as e:  # noqa: BLE001 best-effort graceful degradation
        log.warning("gate5t.verify_via_esggo fell back to local: %s", e)
        return {"ok": verify_locked(locked), "source": "local", "detail": f"network error; local fallback: {e}"}
