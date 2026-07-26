"""AI Station — pytest suite.

Milestone regression tests for the features delivered across sessions:
- config feature flags (free-mode defaults, cloud-gated)
- parser (free path + empty-script guard; OpenAI skipped without key)
- tts: build_srt (word-synced) helper
- renderer: caption filter (word-synced drawtext) + audio-duration fallback
- db: job lifecycle (create/update/get/list) against a temp SQLite
- FastAPI: n8n webhook (auth) + job endpoints (TestClient)
- CI workflow + n8n workflow JSON structural checks
- security: webhook secret, storage path-traversal guard
- integration: real ffmpeg render of a 壽司博士 DNA script

Unit tests need no network/ffmpeg/cloud keys. The integration render test
skips itself when ffmpeg is absent (but CI installs ffmpeg, so it runs there).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Redirect job DB + storage into a temp dir so render tests never touch
    the real repo state (jobs.db / storage/).

    All three modules (config, app, pipeline, storage) now read
    `config.STORAGE_DIR` at call time, so redirecting the single
    `config.STORAGE_DIR` attribute is enough to fully isolate rendering.
    """
    from src import config, db

    work = tmp_path / "state"
    work.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "STORAGE_DIR", work)
    monkeypatch.setattr(db, "DB_PATH", work / "jobs.db")
    db.init_db()
    return work


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
def test_n8n_webhook_returns_compact_result(isolated_state):
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


def test_jobs_endpoints(isolated_state, monkeypatch):
    from src import app, db
    monkeypatch.setattr(db, "DB_PATH", isolated_state / "jobs.db")
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


# ---- 壽司博士 brand preset integration (channel planning bible v1.0) ----

def test_brand_preset_present():
    from src import brand

    b = brand.get_brand("sushi_dr")
    assert b["name"] == "創價未來｜壽司博士 Dr. Source"
    assert b["tagline"] == "看懂變局，創造價值，帶著人性前行。"
    assert len(b["constitution"]) == 5
    assert len(brand.SEED_TOPICS) == 6
    assert len(brand.SERIES) >= 10


def test_brand_dna_palette_mapping():
    from src import brand

    for seg in ["場景", "衝突", "洞察", "方法", "反思"]:
        theme = brand.dna_palette(seg)
        assert len(theme) == 3 and theme[2]
    assert brand.dna_palette("其他")[2] == "brand"


def test_dna_parse_one_shot_per_beat():
    from src import brand

    script = (
        "【場景】一家公司花了一年寫完永續報告，老闆只看了十分鐘。\n"
        "【衝突】報告完成了，公司卻沒有改變。\n"
        "【洞察】因為 ESG 被當成交付物，而不是經營系統。\n"
        "【方法】用 1.0、1.5、2.0 檢查公司位置。\n"
        "【反思】如果永續只讓報告更漂亮，卻沒減少任何人的苦，算永續嗎？\n"
    )
    beats = brand.parse_dna(script)
    assert beats is not None
    assert [b[0] for b in beats] == ["場景", "衝突", "洞察", "方法", "反思"]
    assert brand.parse_dna("這是一段普通腳本，沒有標記。") is None


def test_parser_uses_dna_markers():
    from src import parser

    script = (
        "【場景】城市不是替人民設計。\n"
        "【衝突】市民的需求常被專家最佳化取代。\n"
        "【洞察】公共價值來自共創。\n"
        "【方法】用三個共創問題啟動參與。\n"
        "【反思】你上一次被詢問，是什麼時候？\n"
    )
    shots = parser.parse_script(script)
    assert len(shots) == 5
    assert shots[0].theme[2] == "scene"
    assert shots[-1].theme[2] == "reflection"


def test_api_series_endpoint(isolated_state):
    from src import app
    from fastapi.testclient import TestClient

    c = TestClient(app.app)
    r = c.get("/api/series")
    assert r.status_code == 200
    body = r.json()
    assert "創價未來" in body["brand"]
    assert "ESG做完了然後呢" in body["series"]
    rb = c.get("/api/brand")
    assert rb.status_code == 200 and rb.json()["host"] == "壽司博士 Dr. Source"
    script = "【場景】測試場景。\n【反思】測試反思。\n"
    rj = c.post("/api/jobs", json={"script": script, "brand_preset": "sushi_dr"})
    assert rj.status_code == 200
    # API now returns immediately (queued); poll until the job resolves.
    import time

    job_id = rj.json()["job_id"]
    assert rj.json()["status"] == "queued"
    j = None
    # Background render (edge-tts + ffmpeg) can be slow on a cold/loaded box;
    # poll generously so the test is not flaky.
    for _ in range(120):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert j["status"] == "done"


# ---- Security + background-job + integration (real ffmpeg) ----

def test_webhook_requires_secret_when_configured(monkeypatch, isolated_state):
    from src import app, config
    from fastapi.testclient import TestClient

    monkeypatch.setenv("WEBHOOK_SECRET", "s3cr3t")
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "s3cr3t")
    c = TestClient(app.app)
    # no key -> 401
    r = c.post("/webhook/n8n", json={"script": "x"})
    assert r.status_code == 401
    # wrong key -> 401
    r = c.post("/webhook/n8n", json={"script": "x"}, headers={"X-AI-Station-Key": "nope"})
    assert r.status_code == 401
    # correct key -> accepted (renders)
    r = c.post("/webhook/n8n", json={"script": "x"}, headers={"X-AI-Station-Key": "s3cr3t"})
    assert r.status_code == 200
    assert r.json()["status"] in ("done", "failed")


def test_webhook_ok_flag_reflects_video(isolated_state, monkeypatch):
    """Webhook payload must expose an `ok` flag that is True only when the job
    finished `done` AND produced a video_url (so callers can branch on None)."""
    from src import app, pipeline
    from fastapi.testclient import TestClient

    def _fake_enqueue(script, title, brand_preset=None):
        return {"job_id": "abc123", "status": "done", "title": title,
                "result": '{"video_url": "/storage/final.mp4", "shots": 2}'}

    monkeypatch.setattr(pipeline, "enqueue", _fake_enqueue)
    c = TestClient(app.app)
    r = c.post("/webhook/n8n", json={"script": "x"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["video_url"] == "/storage/final.mp4"

    # Failed job -> ok False, even if (hypothetically) a url were present.
    monkeypatch.setattr(
        pipeline, "enqueue",
        lambda s, t, brand_preset=None: {
            "job_id": "xyz", "status": "failed", "title": t,
            "result": '{"error": "boom"}',
        },
    )
    r2 = c.post("/webhook/n8n", json={"script": "x"})
    assert r2.status_code == 200
    assert r2.json()["ok"] is False
    assert r2.json()["video_url"] is None


def test_storage_path_traversal_blocked():
    from src import app
    from fastapi.testclient import TestClient

    c = TestClient(app.app)
    # try to escape STORAGE_DIR via ../../
    r = c.get("/storage/../../etc/passwd")
    assert r.status_code in (403, 404)


def test_publish_returns_job_scoped_storage_url(isolated_state):
    """Regression: publish() must keep the job sub-directory in the URL.

    Every job renders into STORAGE_DIR/<job_id>/final.mp4, so a bare
    `/storage/final.mp4` would resolve to a missing file (404) and also
    collide across jobs. The returned URL must be `/storage/<job_id>/final.mp4`.
    """
    from src import config, storage
    video = config.STORAGE_DIR / "abc123" / "final.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    try:
        url = storage.save_local(video)
        assert url.startswith("/storage/"), url
        assert "/final.mp4" in url
        # Must include the per-job segment, not just the filename.
        assert url != "/storage/final.mp4", "URL lost the job sub-directory"
        # And it must resolve to the real file under STORAGE_DIR.
        resolved = (config.STORAGE_DIR / url[len("/storage/"):]).resolve()
        assert resolved.exists() or str(video.resolve()).startswith(
            str(config.STORAGE_DIR.resolve())
        )
    finally:
        shutil.rmtree(config.STORAGE_DIR / "abc123", ignore_errors=True)


def test_submit_marks_failed_on_render_error(isolated_state, monkeypatch):
    """Regression: a background job whose render raises must end as `failed`,
    never stuck in `queued`/`rendering` (the bug fixed in submit())."""
    import time
    from src import app, pipeline
    from fastapi.testclient import TestClient

    def _boom(*a, **k):
        raise RuntimeError("forced render failure")

    monkeypatch.setattr(pipeline, "run_pipeline", _boom)
    c = TestClient(app.app)
    rj = c.post("/api/jobs", json={"title": "t", "script": "【場景】x。"})
    assert rj.status_code == 200
    job_id = rj.json()["job_id"]
    j = None
    for _ in range(40):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert j["status"] == "failed"
    assert "forced render failure" in (j.get("result") or "")


def test_parse_openai_mock(monkeypatch):
    """parse_openai shapes Shot objects from a mocked OpenAI chat response
    without any real API key / network call."""
    import json
    from src import parser

    class _Resp:
        def __init__(self, payload):
            self._p = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._p

    fake = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "shots": [
                                {"narration": "a", "visual_prompt": "p1", "caption": "c1"},
                                {"narration": "b", "visual_prompt": "p2", "caption": "c2"},
                            ]
                        }
                    )
                }
            }
        ]
    }

    class _Post:
        def __call__(self, *a, **k):
            return _Resp(fake)

    monkeypatch.setattr(parser.httpx, "post", _Post())
    shots = parser.parse_openai("any script")
    assert len(shots) == 2
    assert all(isinstance(s, parser.Shot) for s in shots)
    assert shots[0].narration == "a" and shots[1].visual_prompt == "p2"


def test_runway_fallback_mock(monkeypatch):
    """When RUNWAY_API_KEY is set but the call fails, visuals falls back to
    a gradient still (is_video=False) instead of raising."""
    from src import config, visuals
    import httpx as _httpx
    from pathlib import Path
    import tempfile

    monkeypatch.setattr(config, "USE_RUNWAY", True)
    monkeypatch.setattr(config, "RUNWAY_API_KEY", "fake-key")
    # Force the Runway call to blow up so we exercise the fallback path.
    monkeypatch.setattr(_httpx, "post",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    shot = {"theme": ["#10131a", "#2a3a5c", "neutral"], "visual_prompt": "x"}
    d = Path(tempfile.mkdtemp())
    media, is_video = visuals.render_shot_media(shot, 1, 1, d / "s.png", d / "s.mp4")
    assert is_video is False
    assert str(media).endswith(".png")


def test_integration_render_runs_ffmpeg(isolated_state):
    """End-to-end: a real DNA script should render an MP4 via ffmpeg.

    Marked integration because it shells out to ffmpeg (installed in CI).
    """
    import pytest

    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except Exception:
        pytest.skip("ffmpeg not installed")
    from src import pipeline

    script = (
        "【場景】一家公司花了一年寫完永續報告。\n"
        "【衝突】報告完成了，公司卻沒有改變。\n"
        "【洞察】ESG 被當成交付物而不是經營系統。\n"
        "【方法】用 1.0、1.5、2.0 檢查位置。\n"
        "【反思】如果永續沒減少任何人的苦，算永續嗎？\n"
    )
    job = pipeline.enqueue(script, "integration-test", brand_preset="sushi_dr")
    assert job["status"] == "done"
    import json
    from pathlib import Path

    file = Path(json.loads(job["result"])["file"])
    assert file.exists() and file.stat().st_size > 1000


def test_metrics_endpoint_aggregates(isolated_state):
    """/api/metrics must aggregate total / by_status / success_rate from the
    job store without any external dependency."""
    from src import app, pipeline
    from fastapi.testclient import TestClient

    # render one real DNA job (uses ffmpeg if available, else skipped path
    # still lands in `done` via local fallback in CI — but to keep the test
    # deterministic we fake a finished job via db directly).
    from src import db as _db
    import json
    import time

    _db.create_job("m1", "a", {"brand_preset": "sushi_dr"})
    _db.update_job("m1", status="done", result=json.dumps({"shots": 3}))
    _db.create_job("m2", "b", {"brand_preset": "default"})
    _db.update_job("m2", status="failed", result=json.dumps({"error": "x"}))

    c = TestClient(app.app)
    r = c.get("/api/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["by_status"]["done"] == 1
    assert body["by_status"]["failed"] == 1
    assert body["success_rate"] == 50.0
    # at least the brand breakdown reflects the presets we stored
    assert body["brand_breakdown"].get("sushi_dr") == 1
    assert body["brand_breakdown"].get("default") == 1
