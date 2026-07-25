"""AI Station — pytest suite.

Milestone regression tests for the features delivered across sessions:
- config feature flags (free-mode defaults, cloud-gated)
- parser (free path + empty-script guard; OpenAI skipped without key)
- tts: build_srt (word-synced) helper
- renderer: caption filter (word-synced drawtext) + audio-duration fallback
- db: job lifecycle (create/update/get/list) against a temp SQLite
- FastAPI: n8n webhook + job endpoints (TestClient, no network)
- CI workflow + n8n workflow JSON structural checks

These are UNIT/INTEGRATION tests that do NOT require network, ffmpeg, or
cloud keys. (End-to-end ffmpeg rendering is exercised separately via CI /
ad-hoc scripts, since it needs a working ffmpeg binary.)
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------- config
def test_config_free_mode_is_default():
    from src import config
    assert config.USE_ELEVENLABS is False
    assert config.USE_RUNWAY is False
    assert config.USE_OPENAI is False
    assert config.USE_S3 is False
    assert config.USE_NCBDB is False


def test_feature_summary_has_all_modules():
    from src import config
    fs = config.feature_summary()
    assert isinstance(fs, dict) and len(fs) == 5
    for v in fs.values():
        assert ("free" in v) or ("edge-tts" in v) or ("pillow" in v) or ("local" in v) or ("sqlite" in v)


# ---------------------------------------------------------------- parser
def test_parser_free_produces_shots():
    from src import parser
    shots = parser.parse_script("宇宙浩瀚無垠。科學家持續探索。今天我們看見起源。")
    assert len(shots) >= 1
    s0 = shots[0].to_dict()
    assert s0["narration"] and s0["theme"] and s0["visual_prompt"]


def test_parser_empty_script_raises():
    from src import parser
    with pytest.raises(ValueError):
        parser.parse_script("   ")


def test_parser_openai_skipped_without_key():
    from src import parser, config
    assert config.USE_OPENAI is False
    # default groups 2 sentences per shot -> 1 shot here
    shots = parser.parse_script("一句話。另一句話。")
    assert len(shots) >= 1


# ---------------------------------------------------------------- tts
def test_build_srt_highlights_current_word():
    from src import tts
    bounds = [
        {"text": "這", "start": 0.1, "end": 0.3},
        {"text": "是", "start": 0.3, "end": 0.5},
    ]
    srt = tts.build_srt(bounds)
    assert "這<b>是</b>" in srt
    assert "00:00:00,100 --> 00:00:00,300" in srt
    assert "2\n00:00:00,300 --> 00:00:00,500" in srt


def test_build_srt_empty_is_blank():
    from src import tts
    assert tts.build_srt([]) == ""


# ---------------------------------------------------------------- renderer
def test_caption_filter_uses_enable_windows():
    from src import renderer
    bounds = [
        {"text": "這", "start": 0.1, "end": 0.3},
        {"text": "是", "start": 0.3, "end": 0.5},
    ]
    vf = renderer._caption_filter(bounds)
    assert "drawtext" in vf
    assert "enable='between(t" in vf
    assert "這是" in vf  # cumulative line


def test_caption_filter_empty_returns_blank():
    from src import renderer
    assert renderer._caption_filter([]) == ""


def test_audio_duration_fallback(tmp_path):
    from src import renderer
    assert renderer.audio_duration(tmp_path / "nope.mp3") >= 1.0


# ---------------------------------------------------------------- db
def test_db_job_lifecycle(tmp_path, monkeypatch):
    from src import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    payload = [{"narration": "x", "theme": ["#000", "#fff", "t"], "visual_prompt": "p", "caption": "c"}]
    j = db.create_job("job1", "t", payload)
    assert db.get_job("job1")["status"] == "queued"
    db.update_job("job1", status="done", progress=100, file="x.mp4",
                  result=json.dumps({"file": "x.mp4", "shots": 1}))
    got = db.get_job("job1")
    assert got["status"] == "done"
    assert json.loads(got["result"])["shots"] == 1
    assert any(jj["job_id"] == "job1" for jj in db.list_jobs())


# ---------------------------------------------------------------- api
def test_n8n_webhook_returns_compact_result():
    from src import app
    from fastapi.testclient import TestClient
    client = TestClient(app.app)
    r = client.post("/webhook/n8n",
                    json={"title": "t", "script": "城市夜晚閃爍。科技改變生活。"})
    assert r.status_code == 200
    b = r.json()
    assert b["status"] == "done"
    assert b["video_url"].startswith("/storage/")
    assert b["shots"] >= 1


def test_n8n_webhook_rejects_empty():
    from src import app
    from fastapi.testclient import TestClient
    client = TestClient(app.app)
    r = client.post("/webhook/n8n", json={"title": "t", "script": "  "})
    assert r.status_code == 400


def test_jobs_endpoints(tmp_path, monkeypatch):
    from src import app, db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    from fastapi.testclient import TestClient
    client = TestClient(app.app)
    payload = {"narration": "鏡頭一。", "theme": ["#000", "#fff", "t"], "visual_prompt": "p", "caption": "c"}
    post = client.post("/api/jobs", json={"title": "t", "script": "鏡頭一。鏡頭二。"})
    assert post.status_code == 200
    jid = post.json()["job_id"]
    got = client.get(f"/api/jobs/{jid}")
    assert got.status_code == 200
    assert got.json()["job_id"] == jid
    assert client.get("/api/jobs/does-not-exist").status_code == 404


# ---------------------------------------------------------------- ci / n8n files
def test_ci_workflow_is_yaml_and_wired():
    try:
        import yaml
    except ImportError:
        pytest.skip("pyyaml not installed")
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["build"]["steps"]
    assert any(s.get("uses", "").startswith("docker/build-push-action") for s in steps)
    assert "push" in steps[-1]["with"]


def test_n8n_workflow_has_schedule_and_http():
    n8n = json.loads((ROOT / "n8n" / "workflow.json").read_text(encoding="utf-8"))
    types = {n["type"] for n in n8n["nodes"]}
    assert "n8n-nodes-base.httpRequest" in types
    assert "n8n-nodes-base.scheduleTrigger" in types
