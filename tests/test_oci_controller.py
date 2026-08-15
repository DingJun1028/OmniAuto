"""Tests for OCI Controller API (integration requires real OCI credentials)."""

from fastapi.testclient import TestClient
from src.oci_controller import router

client = TestClient(router)


def test_oci_router_has_endpoints():
    """5T Traceable: verify OCI endpoints are registered."""
    routes = [r.path for r in router.routes]
    assert "/oci/instances" in routes
    assert any("/oci/instances/{name}" in r for r in routes)
    assert any("/oci/instances/{name}/start" in r for r in routes)
    assert any("/oci/instances/{name}/stop" in r for r in routes)
    assert "/oci/ops-log" in routes


def test_oci_controller_imports():
    """Verify module imports cleanly."""
    from src import oci_controller
    assert hasattr(oci_controller, "router")
    assert hasattr(oci_controller, "list_instances")
