"""Test configuration.

The app ships an in-memory per-IP rate limiter (best-practice abuse guard).
Under pytest, every TestClient request reports `client.host == "testclient"`,
so all tests would share ONE bucket and eventually trip the 429 — making the
suite order-dependent and flaky. This conftest neutralizes the limiter for the
normal tests; the dedicated `test_rate_limit_blocks_burst` re-arms it locally.
"""
import pytest

from src import app as _app


@pytest.fixture(autouse=True)
def _neutralize_rate_limit(monkeypatch):
    """Keep the rate limiter out of the way for ordinary tests.

    Restores the original limit afterwards so state never leaks between tests.
    """
    monkeypatch.setattr(_app, "_RATE_LIMIT", 10_000)
    _app._RATE_BUCKETS.clear()
    yield
    _app._RATE_BUCKETS.clear()
