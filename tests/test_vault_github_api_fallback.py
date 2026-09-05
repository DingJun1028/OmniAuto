"""Tests for vault_moc_commit GitHub API fallback (E 项)."""
import sys, os, base64, json
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(r"C:\Users\dingj\AppData\Local\hermes\scripts")))
import vault_moc_commit as vmc


def test_push_via_github_api_success_update(tmp_path):
    """Happy path: file exists, PUT succeeds."""
    f = tmp_path / "vault" / "Agents" / "04-Index" / "5T-Canon-Daily.md"
    f.parent.mkdir(parents=True)
    f.write_text("---\nsource_origin: test\n---\n\n# test", encoding="utf-8")

    fake_get = {"sha": "abc123"}
    fake_put = {"content": {"path": "vault/Agents/04-Index/5T-Canon-Daily.md"}}

    def fake_urlopen(req, **kwargs):
        from urllib.request import Request
        if isinstance(req, Request):
            method = req.get_method()
        else:
            method = "GET"
        if method == "GET":
            r = mock.MagicMock()
            r.__enter__ = lambda s: s
            r.__exit__ = lambda *a: False
            r.read.return_value = json.dumps(fake_get).encode()
            r.read.return_value = json.dumps(fake_get).encode()
            return r
        else:
            r = mock.MagicMock()
            r.__enter__ = lambda s: s
            r.__exit__ = lambda *a: False
            r.read.return_value = json.dumps(fake_put).encode()
            return r

    with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"}):
        with mock.patch.object(vmc, "ESGGO_REPO", tmp_path):
            with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                rc = vmc.push_via_github_api(f, "test commit")
    assert rc == 0


def test_push_via_github_api_404_new_file(tmp_path):
    """File doesn't exist yet (404), should still create."""
    f = tmp_path / "vault" / "Agents" / "04-Index" / "5T-Canon-Daily.md"
    f.parent.mkdir(parents=True)
    f.write_text("# new", encoding="utf-8")

    from urllib.error import HTTPError

    call_count = {"n": 0}

    def fake_urlopen(req, **kwargs):
        from urllib.request import Request
        call_count["n"] += 1
        method = req.get_method() if isinstance(req, Request) else "GET"
        if method == "GET":
            raise HTTPError(req.full_url, 404, "Not Found", {}, None)
        r = mock.MagicMock()
        r.__enter__ = lambda s: s
        r.__exit__ = lambda *a: False
        r.read.return_value = json.dumps({"content": {"path": "x"}}).encode()
        return r

    with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"}):
        with mock.patch.object(vmc, "ESGGO_REPO", tmp_path):
            with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                rc = vmc.push_via_github_api(f, "create test")
    assert rc == 0
    assert call_count["n"] == 2  # GET (404) + PUT


def test_push_via_github_api_no_token(tmp_path):
    """No GITHUB_TOKEN in env → returns 1."""
    f = tmp_path / "vault" / "Agents" / "04-Index" / "5T-Canon-Daily.md"
    f.parent.mkdir(parents=True)
    f.write_text("# x", encoding="utf-8")

    env_no_token = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
    with mock.patch.dict(os.environ, env_no_token, clear=True):
        with mock.patch.object(vmc, "ESGGO_REPO", tmp_path):
            rc = vmc.push_via_github_api(f, "test")
    assert rc == 1


def test_push_via_github_api_403_returns_1(tmp_path):
    """HTTP 403 on GET → return 1 (don't crash)."""
    f = tmp_path / "vault" / "Agents" / "04-Index" / "5T-Canon-Daily.md"
    f.parent.mkdir(parents=True)
    f.write_text("# x", encoding="utf-8")

    from urllib.error import HTTPError

    def fake_urlopen(req, **kwargs):
        raise HTTPError(req.full_url, 403, "Forbidden", {}, None)

    with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}):
        with mock.patch.object(vmc, "ESGGO_REPO", tmp_path):
            with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                rc = vmc.push_via_github_api(f, "test")
    assert rc == 1


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
