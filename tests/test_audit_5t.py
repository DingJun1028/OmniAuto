"""Tests for the automated 5T audit sweep (§24)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import gate5t, config as _config  # noqa: E402
from scripts import audit_5t  # noqa: E402


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Redirect storage into a temp dir."""
    storage = tmp_path / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_config, "STORAGE_DIR", storage)
    monkeypatch.setattr(audit_5t, "config", _config)
    yield storage


def _make_valid_artifact(uuid: str = "test_valid") -> dict:
    """Create a properly 5T-verified and Hash-Locked artifact."""
    artifact = {
        "uuid": uuid,
        "source_origin": "aistation:test",
        "sources": ["aistation:test", "aistation:src/entropy.py"],
        "lifecycle_hooks": ["created", "locked"],
        "ui_feedback": {"rating": 4.8},
        "transparent_audit": True,
        "frozen": True,
        "content": f"test content {uuid}",
    }
    locked = gate5t.lock_artifact(artifact, kind="test")
    return {
        "uuid": locked.uuid,
        "kind": locked.kind,
        "payload": locked.payload,
        "hash_lock": locked.hash_lock,
        "checks": locked.checks,
    }


def test_audit_no_artifacts(isolated_state):
    """Empty artifacts dir → 0 total, 1.0 pass_rate."""
    result = audit_5t.audit_artifacts()
    assert result["total"] == 0
    assert result["verified"] == 0
    assert result["tampered"] == 0
    assert result["failed"] == 0
    assert result["pass_rate"] == 1.0  # nothing to fail = perfect


def test_audit_all_verified(isolated_state):
    """Valid artifacts pass the full 5T audit."""
    art_dir = isolated_state / "artifacts"
    art_dir.mkdir()
    for i in range(3):
        art = _make_valid_artifact(f"valid_{i}")
        (art_dir / f"valid_{i}.json").write_text(json.dumps(art), encoding="utf-8")

    result = audit_5t.audit_artifacts()
    assert result["total"] == 3
    assert result["verified"] == 3
    assert result["tampered"] == 0
    assert result["failed"] == 0
    assert result["pass_rate"] == 1.0
    assert all(d["status"] == "verified" for d in result["details"])


def test_audit_detects_tamper(isolated_state):
    """Tampered artifact (hash mismatch) is flagged."""
    art_dir = isolated_state / "artifacts"
    art_dir.mkdir()
    art = _make_valid_artifact("tampered_1")
    art["payload"] = '{"tampered": true, "uuid": "tampered_1"}'
    (art_dir / "tampered_1.json").write_text(json.dumps(art), encoding="utf-8")

    result = audit_5t.audit_artifacts()
    assert result["total"] == 1
    assert result["tampered"] == 1
    assert result["verified"] == 0
    assert result["pass_rate"] == 0.0
    assert result["details"][0]["status"] == "tampered"


def test_audit_detects_5t_failure(isolated_state):
    """Artifact with valid hash but missing frozen flag fails 5T gate.

    We recalculate the hash after modifying the payload so the hash matches
    but the 5T gate (frozen=true) still fails — this is the '5t_failed' case.
    """
    import hashlib

    art_dir = isolated_state / "artifacts"
    art_dir.mkdir()
    art = _make_valid_artifact("5t_fail_1")

    # Modify the payload to break frozen flag, then recalculate hash
    # so hash_lock matches but the 5T gate check fails
    payload = json.loads(art["payload"])
    payload["frozen"] = False
    new_payload = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    new_hash = hashlib.sha256(new_payload.encode("utf-8")).hexdigest()

    art["payload"] = new_payload
    art["hash_lock"] = new_hash  # hash now matches the modified payload
    # But frozen=False still fails the Trustworthy check
    (art_dir / "5t_fail_1.json").write_text(json.dumps(art), encoding="utf-8")

    result = audit_5t.audit_artifacts()
    assert result["total"] == 1
    assert result["tampered"] == 0  # hash now matches
    assert result["failed"] == 1
    assert result["details"][0]["status"] == "5t_failed"
    assert result["details"][0]["hash_lock_ok"] is True
    assert result["details"][0]["5t_passed"] is False


def test_audit_handles_parse_error(isolated_state):
    """Corrupt JSON files are flagged as parse_error."""
    art_dir = isolated_state / "artifacts"
    art_dir.mkdir()
    (art_dir / "broken.json").write_text("{not valid json!!!", encoding="utf-8")

    result = audit_5t.audit_artifacts()
    assert result["total"] == 1
    assert result["failed"] == 1
    assert result["details"][0]["status"] == "parse_error"


def test_audit_mixed(isolated_state):
    """Mix of valid, tampered, and failed artifacts."""
    import hashlib

    art_dir = isolated_state / "artifacts"
    art_dir.mkdir()

    # Valid
    valid = _make_valid_artifact("mixed_valid")
    (art_dir / "mixed_valid.json").write_text(json.dumps(valid), encoding="utf-8")

    # Tampered (payload changed without hash update → hash mismatch)
    tampered = _make_valid_artifact("mixed_tamper")
    tampered["payload"] = '{"tampered": true}'
    (art_dir / "mixed_tamper.json").write_text(json.dumps(tampered), encoding="utf-8")

    # 5T failed (payload modified + hash recalculated, but frozen=False)
    failed_art = _make_valid_artifact("mixed_5t")
    payload = json.loads(failed_art["payload"])
    payload["frozen"] = False
    new_payload = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    new_hash = hashlib.sha256(new_payload.encode("utf-8")).hexdigest()
    failed_art["payload"] = new_payload
    failed_art["hash_lock"] = new_hash
    (art_dir / "mixed_5t.json").write_text(json.dumps(failed_art), encoding="utf-8")

    result = audit_5t.audit_artifacts()
    assert result["total"] == 3
    assert result["verified"] == 1
    assert result["tampered"] == 1
    assert result["failed"] == 1
    assert result["pass_rate"] == round(1/3, 4)


def test_audit_json_output_format(isolated_state):
    """JSON output contains all required fields."""
    art_dir = isolated_state / "artifacts"
    art_dir.mkdir()
    art = _make_valid_artifact("json_test")
    (art_dir / "json_test.json").write_text(json.dumps(art), encoding="utf-8")

    result = audit_5t.audit_artifacts()
    assert "total" in result
    assert "verified" in result
    assert "tampered" in result
    assert "failed" in result
    assert "pass_rate" in result
    assert "details" in result
    assert "timestamp" in result
