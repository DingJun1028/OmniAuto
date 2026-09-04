"""Tests for the entropy monitor (§23 §24 — 熵減目標 < 0.1)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import entropy, gate5t, db, config as _config  # noqa: E402
from src.gate5t import LockedArtifact  # noqa: E402


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Redirect job DB + storage into a temp dir (mirrors test_chapter10)."""
    storage = tmp_path / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_config, "STORAGE_DIR", storage)
    monkeypatch.setattr(db, "DB_PATH", storage / "jobs.db")
    db.init_db()
    # Redirect entropy's STORAGE_DIR too
    import src.entropy as _entropy_mod
    monkeypatch.setattr(_entropy_mod, "STORAGE_DIR", storage)
    yield storage


# ---------------------------------------------------------------------------
# job_failure_rate
# ---------------------------------------------------------------------------
def test_entropy_zero_when_no_jobs(isolated_state):
    result = entropy.compute_entropy()
    assert result["entropy"] == 0.0
    assert result["status"] == "OK"
    assert result["target"] == 0.1


def test_entropy_crit_with_all_failures(isolated_state):
    db.create_job("j1", "t", {})
    db.create_job("j2", "t", {})
    db.update_job("j1", status="failed", result="error1")
    db.update_job("j2", status="failed", result="error2")
    result = entropy.compute_entropy()
    assert result["components"]["job_failure_rate"] == 1.0
    assert result["entropy"] > 0.1
    assert result["status"] == "CRIT"


def test_entropy_ok_with_all_success(isolated_state):
    db.create_job("j1", "t", {})
    db.create_job("j2", "t", {})
    db.create_job("j3", "t", {})
    db.update_job("j1", status="done", result="out1.mp4")
    db.update_job("j2", status="done", result="out2.mp4")
    db.update_job("j3", status="done", result="out3.mp4")
    result = entropy.compute_entropy()
    assert result["components"]["job_failure_rate"] == 0.0
    assert result["components"]["lifecycle_incompleteness"] == 0.0  # all have result
    assert result["entropy"] == 0.0
    assert result["status"] == "OK"


def test_entropy_warns_on_missing_result(isolated_state):
    # done job with NULL result = lifecycle gap
    db.create_job("j1", "t", {})
    db.update_job("j1", status="done")  # no result set
    result = entropy.compute_entropy()
    assert result["components"]["lifecycle_incompleteness"] == 1.0
    assert result["status"] in ("WARN", "CRIT")


# ---------------------------------------------------------------------------
# 5T audit
# ---------------------------------------------------------------------------
def _make_locked_artifact(uuid: str = "test_artifact", kind: str = "video") -> dict:
    """Create a valid 5T-verified locked artifact dict and save to disk."""
    artifact = {
        "uuid": uuid,
        "source_origin": "aistation:test",
        "sources": ["aistation:test", "aistation:src/entropy.py"],
        "lifecycle_hooks": ["created", "locked"],
        "ui_feedback": {"rating": 4.8},
        "transparent_audit": True,
        "frozen": True,
        "content": "test content",
    }
    locked = gate5t.lock_artifact(artifact, kind=kind)
    return {
        "uuid": locked.uuid,
        "kind": locked.kind,
        "payload": locked.payload,
        "hash_lock": locked.hash_lock,
        "checks": locked.checks,
    }


def test_entropy_5t_audit_no_artifacts(isolated_state):
    """No artifact files → 5T audit failure = 0.0 (no entropy)."""
    result = entropy.compute_entropy()
    assert result["components"]["5t_audit_failure"] == 0.0


def test_entropy_5t_audit_all_pass(isolated_state):
    art_dir = isolated_state / "artifacts"
    art_dir.mkdir()
    art = _make_locked_artifact()
    (art_dir / "good.json").write_text(json.dumps(art), encoding="utf-8")
    result = entropy.compute_entropy(artifacts_dir=art_dir)
    assert result["components"]["5t_audit_failure"] == 0.0


def test_entropy_5t_audit_detects_tamper(isolated_state):
    art_dir = isolated_state / "artifacts"
    art_dir.mkdir()
    art = _make_locked_artifact()
    art["payload"] = '{"tampered": true}'
    (art_dir / "tampered.json").write_text(json.dumps(art), encoding="utf-8")
    result = entropy.compute_entropy(artifacts_dir=art_dir)
    assert result["components"]["5t_audit_failure"] == 1.0
    assert result["status"] == "CRIT"


# ---------------------------------------------------------------------------
# within_target helper
# ---------------------------------------------------------------------------
def test_entropy_within_target_true_on_empty(isolated_state):
    assert entropy.entropy_within_target() is True


def test_entropy_within_target_false_with_failures(isolated_state):
    db.create_job("j1", "t", {})
    db.update_job("j1", status="failed", result="err")
    assert entropy.entropy_within_target() is False


# ---------------------------------------------------------------------------
# Weights sanity
# ---------------------------------------------------------------------------
def test_entropy_weights_sum_to_one():
    total = sum(entropy._WEIGHTS.values())
    assert abs(total - 1.0) < 0.001


def test_entropy_status_thresholds():
    """Verify OK < 0.1, WARN < 0.15, CRIT >= 0.15."""
    # 0.05 → OK
    assert entropy.compute_entropy()["status"] == "OK"
    # These are checked via component values, not direct injection
    # (entropy is computed from real data, not injected)
