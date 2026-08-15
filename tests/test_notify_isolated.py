"""Isolated unit test for src.notify (no fastapi/app import).

Verifies the Hermes V2 webhook signature scheme and best-effort behavior
without touching the network or the (separately-broken) pydantic stack.
"""
import importlib
import json

import pytest


def _load_notify(monkeypatch):
    """Import src.notify with HERMES_* env cleared so no real POST fires."""
    monkeypatch.delenv("HERMES_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("HERMES_WEBHOOK_SECRET", raising=False)
    import src.notify as notify

    importlib.reload(notify)
    return notify


def test_v2_signature_scheme(monkeypatch):
    notify = _load_notify(monkeypatch)
    secret = "test-secret"
    ts = "1700000000"
    body = json.dumps({"a": 1}).encode()
    sig = notify._v2_signature(secret, ts, body)
    # HMAC-SHA256 of "<ts>.<body>"
    import hmac, hashlib

    expected = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert sig == expected
    # timestamp is bound into the message — replay outside window changes sig
    assert notify._v2_signature(secret, "1700000001", body) != sig


def test_disabled_when_env_unset(monkeypatch):
    notify = _load_notify(monkeypatch)
    assert notify._USE_HERMES is False
    # best-effort: returns False, never raises
    assert notify.video_done("j1", "t", "https://x/y.mp4") is False


def test_video_done_posts_v2_and_returns_true(monkeypatch):
    notify = _load_notify(monkeypatch)
    monkeypatch.setenv("HERMES_WEBHOOK_URL", "http://localhost:8644/webhooks/aistation-done")
    monkeypatch.setenv("HERMES_WEBHOOK_SECRET", "sec")
    importlib.reload(notify)
    assert notify._USE_HERMES is True

    captured = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"status": "delivered"}

    def _post(url, content, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = content
        return _Resp()

    monkeypatch.setattr(notify.httpx, "post", _post)
    ok = notify.video_done("job9", "壽司博士", "https://x/f.mp4", status="done")
    assert ok is True
    assert captured["url"].endswith("/webhooks/aistation-done")
    assert captured["headers"]["X-Webhook-Signature-V2"]
    assert captured["headers"]["X-Webhook-Timestamp"]
    body = json.loads(captured["body"])
    assert body["event_type"] == "video_done"
    assert body["job_id"] == "job9"
    assert body["video_url"] == "https://x/f.mp4"


def test_video_done_swallows_network_error(monkeypatch):
    notify = _load_notify(monkeypatch)
    monkeypatch.setenv("HERMES_WEBHOOK_URL", "http://localhost:8644/x")
    monkeypatch.setenv("HERMES_WEBHOOK_SECRET", "sec")
    importlib.reload(notify)

    def _boom(*a, **k):
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(notify.httpx, "post", _boom)
    # must not raise — best-effort contract
    assert notify.video_done("j", "t", "u") is False
