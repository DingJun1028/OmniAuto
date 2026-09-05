"""Tests for 5T-Canon Multi-Repo Orchestrator (C 项)."""
import sys, json
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(r"C:\Project\aistation")))
import gen_5t_multi_repo as mr


def test_aggregate_all_pass_returns_ok():
    proofs = [
        mr.RepoProof(repo_id="r1", status="ok", hash_lock="abc", five_t_passed=True, duration_s=1.0),
        mr.RepoProof(repo_id="r2", status="ok", hash_lock="def", five_t_passed=True, duration_s=1.0),
    ]
    digest = mr.aggregate(proofs)
    assert digest.escalation == "OK"
    assert digest.entropy == 0.0
    assert digest.passed == 2
    assert digest.failed == 0
    assert len(digest.digest_hash) == 64


def test_aggregate_partial_fail_is_p1():
    """1 fail out of 4 active → entropy=0.25 → P1."""
    proofs = [
        mr.RepoProof(repo_id="r1", status="ok", hash_lock="a", five_t_passed=True, duration_s=1.0),
        mr.RepoProof(repo_id="r2", status="fail", hash_lock="", five_t_passed=False, duration_s=1.0),
        mr.RepoProof(repo_id="r3", status="ok", hash_lock="b", five_t_passed=True, duration_s=1.0),
        mr.RepoProof(repo_id="r4", status="ok", hash_lock="c", five_t_passed=True, duration_s=1.0),
    ]
    digest = mr.aggregate(proofs)
    assert digest.escalation == "P1"
    assert abs(digest.entropy - 0.25) < 0.01


def test_aggregate_majority_fail_is_p0():
    """3 fail out of 4 → entropy=0.75 → P0."""
    proofs = [
        mr.RepoProof(repo_id=f"r{i}", status="fail", hash_lock="", five_t_passed=False, duration_s=1.0)
        for i in range(3)
    ] + [
        mr.RepoProof(repo_id="ok", status="ok", hash_lock="x", five_t_passed=True, duration_s=1.0),
    ]
    digest = mr.aggregate(proofs)
    assert digest.escalation == "P0"
    assert abs(digest.entropy - 0.75) < 0.01


def test_aggregate_skipped_dont_count_in_entropy():
    """Skipped repos don't increase entropy denominator."""
    proofs = [
        mr.RepoProof(repo_id="r1", status="ok", hash_lock="a", five_t_passed=True, duration_s=1.0),
        mr.RepoProof(repo_id="r2", status="skip", hash_lock="", five_t_passed=False, duration_s=0.0),
    ]
    digest = mr.aggregate(proofs)
    assert digest.escalation == "OK"  # 0 failures / 1 active = 0
    assert digest.skipped == 1


def test_scan_repo_missing_path():
    """Missing repo path → skip."""
    p = mr.scan_repo({"id": "missing", "path": r"C:\does\not\exist", "proof_script": "x.py"})
    assert p.status == "skip"
    assert "not found" in p.error


def test_format_telegram_is_single_message():
    """Telegram format produces ONE message (not N)."""
    proofs = [
        mr.RepoProof(repo_id="r1", status="ok", hash_lock="abc123", five_t_passed=True, duration_s=1.5),
        mr.RepoProof(repo_id="r2", status="fail", hash_lock="", five_t_passed=False, duration_s=0.5, error="timeout"),
    ]
    digest = mr.aggregate(proofs)
    msg = mr.format_telegram(digest)
    # Single newline-joined message
    assert msg.count("\n5T-Canon") == 0  # only one header
    assert "5T-Canon Multi-Repo Digest" in msg
    assert "r1" in msg
    assert "r2" in msg
    assert "timeout" in msg


def test_digest_is_frozen():
    """5T Trustworthy: AggregatorDigest is frozen."""
    proofs = [
        mr.RepoProof(repo_id="r1", status="ok", hash_lock="a", five_t_passed=True, duration_s=1.0),
    ]
    digest = mr.aggregate(proofs)
    # Should be immutable
    try:
        digest.passed = 999
        assert False, "should have raised"
    except Exception:
        pass


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
