"""Tests for src/n5t.py — 5T-canon proof notifier with dual-channel fallback."""
import json
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, r"C:\Project\aistation")

from src import n5t


def test_v2_signature_format():
    """V2 signature: HMAC-SHA256(secret, "<ts>.<body>") → hex digest."""
    secret = "test-secret"
    ts = "1700000000"
    body = b'{"event":"5t_canon_proof"}'
    sig = n5t._v2_signature(secret, ts, body)
    expected = hmac_sha256(secret, f"{ts}.".encode() + body)
    assert sig == expected, f"signature mismatch: {sig} != {expected}"
    assert len(sig) == 64, f"SHA-256 hex should be 64 chars, got {len(sig)}"
    print("  [PASS] test_v2_signature_format")


def hmac_sha256(secret: str, msg: bytes) -> str:
    import hmac, hashlib
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def test_notify_returns_delivered_flag():
    """notify_5t_canon_proof returns dict with delivered bool + primary + legacy."""
    fake_primary = {"delivered": True, "status": 200, "response": "ok"}
    fake_legacy = {"delivered": True, "status": 200, "response": "ok"}
    with patch.object(n5t, "_post_signed", side_effect=[fake_primary, fake_legacy]):
        result = n5t.notify_5t_canon_proof(
            kind="5T-Canon-Proof",
            uuid="test-uuid",
            hash_lock="abc123" * 10,
            source_origin="test://origin",
            pillars_passed={"Tangible": True, "Traceable": True},
            result="PASSED",
        )
    assert result["delivered"] is True
    assert "primary_event" in result
    assert "legacy_event" in result
    assert result["primary_event"]["status"] == 200
    assert result["legacy_event"]["status"] == 200
    print("  [PASS] test_notify_returns_delivered_flag")


def test_legacy_envelope_format():
    """Legacy envelope uses video_done route the gateway already accepts."""
    captured = []

    def capture_post(url, body):
        captured.append(body)
        return {"delivered": True, "status": 200, "response": "ok"}

    with patch.object(n5t, "_post_signed", side_effect=capture_post):
        n5t.notify_5t_canon_proof(
            kind="5T-Canon-Module-M1",
            uuid="m1-uuid",
            hash_lock="d" * 64,
            source_origin="AIStation::M1",
            pillars_passed={"Tangible": True},
        )

    assert len(captured) == 2, f"expected 2 calls, got {len(captured)}"
    primary, legacy = captured
    assert primary["event"] == "5t_canon_proof", "primary event should be 5t_canon_proof"
    assert legacy["event"] == "video_done", "legacy event should be video_done"
    assert legacy["job_id"] == "m1-uuid"
    assert legacy["video_url"].startswith("5t://")
    assert "5T-Canon-Module-M1" in legacy["title"]
    print("  [PASS] test_legacy_envelope_format")


def test_partial_delivery_still_delivered_true():
    """If primary fails (unknown event) but legacy succeeds, delivered=True."""
    fake_primary = {"delivered": True, "status": 200, "response": '{"status":"ignored","event":"unknown"}'}
    fake_legacy = {"delivered": True, "status": 200, "response": "ok"}
    with patch.object(n5t, "_post_signed", side_effect=[fake_primary, fake_legacy]):
        result = n5t.notify_5t_canon_proof(
            kind="5T-Canon-Proof",
            uuid="x",
            hash_lock="0" * 64,
            source_origin="t",
            pillars_passed={"Tangible": True},
        )
    assert result["delivered"] is True, "should be delivered via legacy fallback"
    print("  [PASS] test_partial_delivery_still_delivered_true")


def test_total_failure():
    """Both channels fail → delivered=False."""
    fake_primary = {"delivered": False, "error": "timeout"}
    fake_legacy = {"delivered": False, "error": "timeout"}
    with patch.object(n5t, "_post_signed", side_effect=[fake_primary, fake_legacy]):
        result = n5t.notify_5t_canon_proof(
            kind="5T-Canon-Proof",
            uuid="x",
            hash_lock="0" * 64,
            source_origin="t",
            pillars_passed={"Tangible": True},
        )
    assert result["delivered"] is False
    print("  [PASS] test_total_failure")


def test_dispatch_wrapper_backward_compat():
    """dispatch() shim still works for old callers (gen_5t_dispatch.py)."""
    with patch.object(n5t, "_post_signed", return_value={"delivered": True, "status": 200, "response": "ok"}):
        result = n5t.dispatch(
            {
                "kind": "5T-Canon-Proof",
                "uuid": "abc",
                "hash_lock": "1" * 64,
                "source_origin": "test",
                "pillars_passed": {"Tangible": True},
                "result": "PASSED",
            },
            dry_run=False,
        )
    assert result["delivered"] is True
    assert "channels" in result
    print("  [PASS] test_dispatch_wrapper_backward_compat")


def test_dry_run_short_circuits():
    """dispatch(dry_run=True) returns without HTTP call."""
    with patch.object(n5t, "_post_signed") as mock_post:
        result = n5t.dispatch({}, dry_run=True)
    assert result["dry_run"] is True
    assert mock_post.call_count == 0, "dry_run must not POST"
    print("  [PASS] test_dry_run_short_circuits")


def test_pillars_str_format():
    """Verify the pillars_str format inside the data payload."""
    captured = []

    def capture(url, body):
        captured.append(body)
        return {"delivered": True, "status": 200}

    with patch.object(n5t, "_post_signed", side_effect=capture):
        n5t.notify_5t_canon_proof(
            kind="X",
            uuid="u",
            hash_lock="0" * 64,
            source_origin="s",
            pillars_passed={
                "Tangible": True, "Traceable": True, "Trackable": True,
                "Transparent": False, "Trustworthy": True,
            },
        )

    primary = captured[0]
    ps = primary["data"]["pillars_str"]
    assert "✓ Tangible" in ps
    assert "✓ Traceable" in ps
    assert "✗ Transparent" in ps
    assert "✓ Trustworthy" in ps
    print("  [PASS] test_pillars_str_format")


if __name__ == "__main__":
    print("=" * 60)
    print("  n5t.py test suite")
    print("=" * 60)
    test_v2_signature_format()
    test_notify_returns_delivered_flag()
    test_legacy_envelope_format()
    test_partial_delivery_still_delivered_true()
    test_total_failure()
    test_dispatch_wrapper_backward_compat()
    test_dry_run_short_circuits()
    test_pillars_str_format()
    print(f"\n  All 8 tests passed")
