"""Tests for OCI Controller API integration in app."""

from fastapi.testclient import TestClient
from src.app import app


def test_oci_endpoints_registered():
    """Verify OCI routes are exposed through main app."""
    client = TestClient(app)
    # Should return 401/403 or list, not 404
    r = client.get("/oci/instances")
    assert r.status_code in (200, 401, 403, 500), f"unexpected: {r.status_code}"


def test_oci_ops_log_endpoint():
    """Verify ops-log endpoint is reachable."""
    client = TestClient(app)
    r = client.get("/oci/ops-log")
    assert r.status_code in (200, 401, 403, 500)
