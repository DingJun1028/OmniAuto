"""Entropy monitor (§23 §24 — 熵減目標 < 0.1).

Computes the entropy (disorder) of the AI Station pipeline and the 30-agent
swarm based on real measurable signals — never fabricated. Lower entropy
means a healthier, more ordered system.

Entropy components (0.0 = perfectly ordered, 1.0 = maximum disorder):
  - job_failure_rate: fraction of jobs that ended in 'failed' (weight 0.4)
  - lifecycle_incompleteness: fraction of terminal jobs missing provenance
    log entries across expected lifecycle events (weight 0.3)
  - 5T_audit_failure: fraction of frozen artifacts failing 5T re-verification
    (weight 0.3)

Combined entropy = weighted sum. Target: < 0.1.

Free-local by default — reads from SQLite job store + on-disk artifact hashes.
No external services, no paid APIs.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import db, metrics
from .config import log, STORAGE_DIR

# Weights must sum to 1.0
_WEIGHTS = {
    "job_failure_rate": 0.4,
    "lifecycle_incompleteness": 0.3,
    "5t_audit_failure": 0.3,
}

# Expected lifecycle transitions for a terminal job (created → queued → rendering → done)
_EXPECTED_HOOKS = ["created", "queued", "rendered", "done"]


def _job_failure_rate(jobs: List[Dict[str, Any]]) -> float:
    """Fraction of jobs in 'failed' status. 0.0 if no jobs."""
    if not jobs:
        return 0.0
    by_status = Counter(j["status"] for j in jobs)
    total = len(jobs)
    failed = by_status.get("failed", 0)
    return failed / total if total else 0.0


def _lifecycle_incompleteness(jobs: List[Dict[str, Any]]) -> float:
    """Fraction of terminal jobs with incomplete lifecycle tracking.

    A terminal job (done/failed) should have a provenance log entry for each
    expected hook stage. Since we use SQLite mirroring (no external provenance
    store in free mode), we approximate via job table completeness: a terminal
    job with a NULL result (no output artifact path) indicates a lifecycle gap.

    Returns 0.0 for empty or no terminal jobs.
    """
    terminal = [j for j in jobs if j["status"] in ("done", "failed")]
    if not terminal:
        return 0.0
    incomplete = sum(1 for j in terminal if not j.get("result"))
    return incomplete / len(terminal)


def _5t_audit_failure(artifacts_dir: Optional[Path] = None) -> float:
    """Fraction of frozen artifacts that fail 5T hash re-verification.

    In free-local mode, frozen artifacts are stored as JSON files in the
    STORAGE_DIR / 'artifacts' directory. Each file is a LockedArtifact shape.

    Returns 0.0 if no artifacts (nothing to audit = zero entropy contribution).
    """
    art_dir = artifacts_dir or (STORAGE_DIR / "artifacts")
    if not art_dir or not art_dir.exists():
        return 0.0

    try:
        from .gate5t import verify_locked, LockedArtifact
    except ImportError:
        return 0.0

    import json

    total = 0
    failures = 0
    for f in art_dir.iterdir():
        if not f.suffix == ".json":
            continue
        total += 1
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            locked = LockedArtifact(
                uuid=data.get("uuid", ""),
                kind=data.get("kind", ""),
                payload=data.get("payload", ""),
                hash_lock=data.get("hash_lock", ""),
                checks=data.get("checks", {}),
            )
            if not verify_locked(locked):
                failures += 1
        except Exception as e:
            log.warning("entropy._5t_audit_failure: could not parse %s: %s", f.name, e)
            failures += 1

    return failures / total if total else 0.0


def compute_entropy(
    jobs_limit: int = 500,
    artifacts_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compute the current entropy of the system.

    Args:
        jobs_limit: how many recent jobs to sample from the DB.
        artifacts_dir: directory containing frozen .json artifact files.
            Defaults to STORAGE_DIR / "artifacts".

    Returns:
        {
            "entropy": float,          # combined entropy (target < 0.1)
            "components": {            # raw component values
                "job_failure_rate": float,
                "lifecycle_incompleteness": float,
                "5t_audit_failure": float,
            },
            "weights": dict,           # the weight map used
            "status": "OK"|"WARN"|"CRIT",
            "target": 0.1,
            "timestamp": int,          # unix epoch
        }
    """
    import time

    jobs = db.list_jobs(jobs_limit)

    jfr = _job_failure_rate(jobs)
    lic = _lifecycle_incompleteness(jobs)
    taf = _5t_audit_failure(artifacts_dir)

    components = {
        "job_failure_rate": round(jfr, 4),
        "lifecycle_incompleteness": round(lic, 4),
        "5t_audit_failure": round(taf, 4),
    }

    entropy_val = (
        jfr * _WEIGHTS["job_failure_rate"]
        + lic * _WEIGHTS["lifecycle_incompleteness"]
        + taf * _WEIGHTS["5t_audit_failure"]
    )
    entropy_val = round(entropy_val, 4)

    # Status based on proximity to 0.1 target
    if entropy_val < 0.1:
        status = "OK"
    elif entropy_val < 0.15:
        status = "WARN"
    else:
        status = "CRIT"

    return {
        "entropy": entropy_val,
        "components": components,
        "weights": _WEIGHTS,
        "status": status,
        "target": 0.1,
        "timestamp": int(time.time()),
    }


def entropy_within_target(threshold: float = 0.1) -> bool:
    """Quick boolean: is the system entropy below the target threshold?"""
    return compute_entropy()["entropy"] < threshold
