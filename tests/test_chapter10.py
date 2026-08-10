"""Tests for Chapter 10 best-practice modules: gate5t, kpi, newsletter."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from src import gate5t, kpi, newsletter  # noqa: E402
from src import config as _config, db as _db  # noqa: E402


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Redirect job DB + storage into a temp dir (mirrors test_aistation.py)."""
    storage = tmp_path / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_config, "STORAGE_DIR", storage)
    monkeypatch.setattr(_db, "DB_PATH", storage / "jobs.db")
    _db.init_db()
    yield storage
    # cleanup not strictly needed; tmp_path is ephemeral


# ---------------------------------------------------------------------------
# gate5t
# ---------------------------------------------------------------------------
def _good_artifact():
    return {
        "uuid": "job_abc123",
        "source_origin": "aistation:src/pipeline.py",
        "sources": [
            "aistation:src/pipeline.py",
            "aistation:src/notify.py",
            "esggo:app/api/verify-5t",
            "esggo:packages/omni-agent-bus",
        ],
        "lifecycle_hooks": ["created", "rendered", "done"],
        "ui_feedback": {"rating": 4.7},
        "transparent_audit": True,
        "frozen": True,
    }


def test_verify_5t_passes_good_artifact():
    r = gate5t.verify_5t(_good_artifact())
    assert r.passed is True
    assert all(r.checks.values())


def test_verify_5t_fails_missing_source_origin():
    a = _good_artifact()
    del a["source_origin"]
    r = gate5t.verify_5t(a)
    assert r.passed is False
    assert "source_origin" in r.missing
    assert r.checks["Traceable"] is False


def test_verify_5t_fails_missing_frozen():
    a = _good_artifact()
    a["frozen"] = False
    r = gate5t.verify_5t(a)
    assert r.checks["Trustworthy"] is False
    assert r.passed is False


def test_lock_artifact_freezes_and_tamper_detect():
    locked = gate5t.lock_artifact(_good_artifact(), kind="video")
    assert gate5t.verify_locked(locked) is True
    # frozen dataclass cannot be mutated
    with pytest.raises(Exception):
        locked.uuid = "tampered"  # type: ignore[misc]
    # different payload -> hash mismatch
    assert gate5t.verify_locked(
        gate5t.LockedArtifact(locked.uuid, locked.kind, '{"x":1}', "deadbeef", locked.checks)
    ) is False


def test_lock_artifact_rejects_unverified():
    with pytest.raises(ValueError):
        gate5t.lock_artifact({"uuid": "x"})  # missing everything


# ---------------------------------------------------------------------------
# kpi
# ---------------------------------------------------------------------------
def test_kpi_snapshot_overall_ok_with_real_metrics(isolated_state):
    # isolated_state redirects db + storage; create a done job so metrics compute
    from src import db

    db.create_job("j1", "t", {"brand_preset": "sushi_dr"})
    db.update_job("j1", status="done")
    snap = kpi.snapshot()
    assert snap.overall in ("OK", "WARN", "CRIT", "N/A")
    # ai_station_success should be 100% with one done job
    if "ai_station_success" in snap.values:
        assert snap.values["ai_station_success"] == 100.0


def test_kpi_alert_on_crit():
    snap = kpi.snapshot(entropy=0.5)  # target 0.1 -> CRIT
    assert any(a["metric"] == "entropy" and a["level"] == "CRIT" for a in snap.alerts)


# ---------------------------------------------------------------------------
# newsletter
# ---------------------------------------------------------------------------
def test_newsletter_template_rejects_unknown_type():
    with pytest.raises(ValueError):
        newsletter.build_template("bogus", "s", "b")


def test_newsletter_template_frozen():
    t = newsletter.build_template("weekly_swarm", "週報", "body")
    with pytest.raises(Exception):
        t.subject = "hacked"  # type: ignore[misc]


def test_newsletter_rate_limit():
    # hammer telegram channel; should block after ceiling within 1s window.
    # Test the limiter directly for determinism (no network).
    ceiling = newsletter._RATE_LIMITS["telegram"]
    allowed_flags = [newsletter._RATE.allow("telegram") for _ in range(ceiling + 5)]
    # first `ceiling` allowed, remaining blocked
    assert all(allowed_flags[:ceiling]) is True
    assert all(allowed_flags[ceiling:]) is False


def test_newsletter_send_best_effort_no_channels():
    t = newsletter.build_template("ai_station_update", "AI Station 更新", "hello")
    # no channels configured -> empty results, no error
    results = newsletter.send(t)
    assert results == []


def test_newsletter_unsubscribe_logs(isolated_state):
    ok = newsletter.unsubscribe("someone@example.com", "too frequent")
    assert ok is True
    log_path = __import__("src.config", fromlist=["config"]).STORAGE_DIR / "unsubscribes.log"
    assert log_path.exists()


# ---------------------------------------------------------------------------
# single source of truth alignment (esggo IComponentCore)
# ---------------------------------------------------------------------------
def test_to_component_core_shape():
    locked = gate5t.lock_artifact(_good_artifact(), kind="video")
    core = gate5t.to_component_core(locked, version="2.3.0")
    assert core["uuid"] == locked.uuid
    assert core["version"] == "2.3.0"
    assert "timestamp" in core and isinstance(core["timestamp"], int)
    assert core["hashLock"] == locked.hash_lock
    assert core["evidence"]["checks"] == locked.checks


def test_verify_via_esggo_local_fallback(monkeypatch):
    # no ESGO_HASHLOCK_URL -> local verify path, never errors
    monkeypatch.delenv("ESGO_HASHLOCK_URL", raising=False)
    locked = gate5t.lock_artifact(_good_artifact())
    res = gate5t.verify_via_esggo(locked)
    assert res["ok"] is True
    assert res["source"] == "local"


def test_verify_via_esggo_passes_authority(monkeypatch):
    """With ESGO_HASHLOCK_URL set + 4 sources, esggo authority returns pass=true."""
    # module-level constant read at import; override directly
    monkeypatch.setattr(gate5t, "ESGO_HASHLOCK_URL", "http://esggo.test")

    class _Resp:
        status_code = 200

        def json(self):
            return {"pass": True, "status": {"traceable": True}, "score": {}, "hashLock": "abc"}

    captured = {}

    def _post(url, json=None, timeout=10.0, **kw):
        captured["url"] = url
        captured["payload"] = json
        return _Resp()

    monkeypatch.setattr(gate5t.httpx, "post", _post)
    locked = gate5t.lock_artifact(_good_artifact())
    res = gate5t.verify_via_esggo(locked)
    assert res["ok"] is True
    assert res["source"] == "esggo"
    # payload carries the multi-source list so esggo's traceable gate can pass
    assert captured["payload"]["sources"] == _good_artifact()["sources"]
    assert captured["url"].endswith("/api/verify-5t")


def test_kpi_esggo_summary_unwrap_double_nested(monkeypatch):
    """esggo /api/omni-center/summary returns {data:{data:{...}}} (double nested)."""
    import src.kpi as kpi

    class _Resp:
        status_code = 200

        def json(self):
            return {"success": True, "data": {"success": True, "data": {"caseCount": 47, "griIndicatorCount": 142}}}

    monkeypatch.setattr(kpi.httpx, "get", lambda *a, **k: _Resp())
    summary = kpi.fetch_esggo_summary()
    assert summary is not None
    assert summary.get("caseCount") == 47
    assert summary.get("griIndicatorCount") == 142


def test_kpi_esggo_summary_single_nested(monkeypatch):
    """Older shape {data:{...}} still unwraps."""
    import src.kpi as kpi

    class _Resp:
        status_code = 200

        def json(self):
            return {"data": {"caseCount": 10, "griIndicatorCount": 20}}

    monkeypatch.setattr(kpi.httpx, "get", lambda *a, **k: _Resp())
    summary = kpi.fetch_esggo_summary()
    assert summary is not None
    assert summary.get("caseCount") == 10


def test_weekly_report_renders_esggo(monkeypatch, isolated_state):
    """build_weekly_report includes esggo OmniCenter when summary available."""
    import src.kpi as kpi

    class _Resp:
        status_code = 200

        def json(self):
            return {"success": True, "data": {"success": True, "data": {"caseCount": 47, "griIndicatorCount": 142}}}

    monkeypatch.setattr(kpi.httpx, "get", lambda *a, **k: _Resp())
    report = kpi.build_weekly_report(pairing=100, entropy=0.08, security=0, satisfaction=4.6)
    assert report["esggo_omnicenter"]["caseCount"] == 47
    md = kpi.render_weekly_markdown(report)
    assert "案件數: 47" in md
    assert "GRI 指標: 142" in md
