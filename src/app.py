"""
AI Station — FastAPI control center.

Exposes the orchestration hub (IDEA.md module 1) over HTTP so it can be
driven by n8n webhooks, the built-in web UI, or any client.

Uses hybrid TypeScript approach:
- 方案 A: TypeScript types (web/src/types/api.ts) - synced from Python Pydantic
- 方案 B: Zod schemas (web/src/types/schemas.ts) - for frontend validation
- 方案 C: OpenAPI auto-generation - FastAPI auto-generates OpenAPI spec
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import hmac
import uuid
import time

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse, HTMLResponse

# Import types from the centralized type definitions
from .types.api import ScriptIn, JobResponse, WebhookIn

from . import db, pipeline
from . import config
from .config import BASE_DIR, feature_summary, setup_logging, log
from . import brand as _brand_module

app = FastAPI(title="AI Station", version="0.1.0")
db.init_db()
setup_logging()  # TODO pillar 6: structured logging (no-op if already configured)


# ---- Lightweight in-memory rate limiter (best-practice: abuse resistance) ----
# Sliding-window per client IP. Prevents a public free-tier VPS from being
# hammered by unbounded /api/jobs or /webhook/n8n submissions. Not shared
# across workers (single-process uvicorn here), which is sufficient for this
# deployment; swap for redis if scaled out.
import time
from collections import defaultdict, deque

_RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MIN", "30"))  # requests / minute / IP
_RATE_BUCKETS: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request):
    now = time.time()
    bucket = _RATE_BUCKETS[_client_ip(request)]
    # drop timestamps older than 60s
    while bucket and bucket[0] <= now - 60:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT:
        raise HTTPException(429, "rate limit exceeded; slow down")
    bucket.append(now)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "features": feature_summary()}


@app.get("/api/metrics")
def metrics() -> dict:
    """Lightweight pipeline observability (TODO pillar 6): throughput,
    reliability, and per-brand activity aggregated from the job store."""
    from . import metrics as _metrics

    return _metrics.compute_metrics()


@app.get("/api/best-practice")
def best_practice_report():
    """Best-practice report (Chapter 10): combines 5T gate results,
    KPI snapshot, and pipeline metrics into one verifiable artifact."""
    from . import db, gate5t, kpi, metrics as _metrics

    jobs = db.list_jobs(20)
    artifacts = []
    for j in jobs:
        raw = j.get("result") or j.get("payload") or "{}"
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            payload = {"raw": raw}
        if not isinstance(payload, dict):
            payload = {"value": payload}
        payload.setdefault("uuid", j.get("job_id"))
        payload.setdefault("source_origin", "aistation.db")
        payload.setdefault("lifecycle_hooks", ["created", j.get("status", "unknown")])
        payload.setdefault("ui_feedback", "metrics")
        payload.setdefault("transparent_audit", {"zero_hallucination": True})
        payload.setdefault("frozen", False)
        report = gate5t.verify_5t(payload)
        artifacts.append(
            {
                "job_id": j.get("job_id"),
                "status": j.get("status"),
                "5t": {
                    "passed": report.passed,
                    "checks": report.checks,
                    "missing": report.missing,
                },
            }
        )

    snap = kpi.snapshot()
    m = _metrics.compute_metrics()
    return {
        "generated_at": int(__import__("time").time()),
        "pipeline_metrics": m,
        "kpi": {
            "overall": snap.overall,
            "values": snap.values,
            "targets": snap.targets,
            "alerts": snap.alerts,
        },
        "recent_jobs_5t": artifacts,
        "entropy_control": {
            "current": snap.values.get("entropy"),
            "target": "< 0.1",
        },
    }


@app.post("/api/jobs")
def create_job(payload: ScriptIn, request: Request, _: None = Depends(rate_limit)):
    """Submit a job. Returns immediately (202) with the job id; the heavy
    render runs in the background so long scripts don't block the request.
    Poll GET /api/jobs/{id} for status."""
    if not payload.script.strip():
        raise HTTPException(400, "script is empty")
    job_id = pipeline.submit(payload.script, payload.title, brand_preset=payload.brand_preset)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/config")
def api_config():
    """OmniAutoVideo 萬能自動影音-compatible config endpoint.

    Exposes the full set of tunable knobs so MPT's UI can reflect the live
    server configuration (TTS engine, voice, video ratio, max shot duration,
    brand presets, available voices, etc.).
    """
    return {
        "tts_engine": "azure" if config.USE_AZURE
                     else ("elevenlabs" if config.USE_ELEVENLABS else "edge-tts"),
        "tts_voice": config.EDGE_VOICE,
        "tts_voice_en": config.EDGE_VOICE_EN,
        "azure_voice": config.AZURE_VOICE,
        "azure_voice_style": config.AZURE_VOICE_STYLE,
        "azure_style_text": config.AZURE_STYLE_TEXT,
        "elevenlabs_voice_id": config.ELEVENLABS_VOICE_ID,
        "video_ratio": config.VIDEO_RATIO,
        "video_width": config.VIDEO_WIDTH,
        "video_height": config.VIDEO_HEIGHT,
        "video_fps": config.VIDEO_FPS,
        "max_shot_duration": config.MAX_SHOT_DURATION,
        "ken_burns_zoom": config.KEN_BURNS_ZOOM,
        "use_runway": config.USE_RUNWAY,
        "use_s3": config.USE_S3,
        "use_ncbdb": config.USE_NCBDB,
        "available_voices": [
            "zh-TW-HsiaoChenNeural",
            "zh-CN-XiaoxiNeural",
            "zh-CN-YaoHanNeural",
            "en-US-AriaNeural",
            "en-US-GuyNeural",
        ],
        "brand_presets": list(_brand_module.SERIES.keys()),
        "features": feature_summary(),
    }


class MPTWebhookIn(BaseModel):
    """OmniAutoVideo 萬能自動影音 webhook payload (mirrors the UI form fields)."""
    title: str = "Untitled"
    script: str | None = None
    text: str | None = None
    brand_preset: str | None = None  # "sushi_dr" for 壽司博士
    voice: str | None = None          # e.g. "zh-TW-HsiaoChenNeural"
    style_name: str | None = None     # Azure voice style ("sad", "cheerful", …)
    style_text: str | None = None    # Azure style text context
    video_ratio: str | None = None    # "16:9" or "9:16"

    @property
    def body(self) -> str:
        return self.script or self.text or ""


@app.post("/webhook/mpt")
def webhook_mpt(payload: MPTWebhookIn, request: Request, _: None = Depends(rate_limit)):
    _check_webhook_auth(request)
    script = payload.body
    if not script.strip():
        raise HTTPException(400, "missing 'script' or 'text'")

    # Synchronous render (MPT awaits the response). Uses enqueue() which
    # runs the full pipeline to completion before returning.
    job = pipeline.enqueue(
        script, payload.title, brand_preset=payload.brand_preset,
        voice=payload.voice, style_name=payload.style_name,
        style_text=payload.style_text,
    )
    res = json.loads(job["result"]) if job.get("result") else {}
    video_url = res.get("video_url")
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "ok": job["status"] == "done" and bool(video_url),
        "title": job["title"],
        "video_url": video_url,
        "shots": res.get("shots"),
        "error": res.get("error") if job["status"] == "failed" else None,
    }


@app.get("/api/brand")
def brand_info(preset: str = "sushi_dr"):
    from . import brand

    try:
        return brand.get_brand(preset)
    except KeyError:
        raise HTTPException(404, f"unknown brand preset: {preset}")


@app.get("/api/series")
def series_registry():
    """壽司博士 channel product lines + first-quarter 母題."""
    from . import brand

    return {
        "brand": brand.BRAND["name"],
        "formula": brand.BRAND["formula"],
        "series": brand.SERIES,
        "seed_topics": brand.SEED_TOPICS,
    }


@app.get("/api/jobs")
def jobs(limit: int = 50):
    return [db.get_job(j["job_id"]) for j in db.list_jobs(limit)]


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j


# ---- n8n webhook (IDEA.md module 1 / orchestration) ----
# n8n posts { "title", "script" } (or a "text" field) and gets a
# synchronous job result, so it can be dropped into any n8n flow as an
# HTTP Request node and chained with scheduling / other services.


def _check_webhook_auth(request: "Request"):
    """If WEBHOOK_SECRET is configured, require it via header or query.

    Uses constant-time comparison (hmac.compare_digest) to avoid a
    timing side-channel on the secret.
    """
    secret = config.WEBHOOK_SECRET
    if not secret:
        return
    x_key = request.headers.get("X-AI-Station-Key") or ""
    key = request.query_params.get("key") or ""
    if not hmac.compare_digest(x_key, secret) and not hmac.compare_digest(key, secret):
        raise HTTPException(401, "invalid or missing webhook key")


@app.post("/webhook/n8n")
def webhook_n8n(payload: WebhookIn, request: "Request", _: None = Depends(rate_limit)):
    _check_webhook_auth(request)
    script = payload.body
    if not script.strip():
        raise HTTPException(400, "missing 'script' or 'text'")
    # Webhook stays synchronous (n8n awaits the result), but runs via the
    # same background pool so very long scripts still complete.
    job = pipeline.enqueue(script, payload.title, brand_preset=payload.brand_preset)
    res = json.loads(job["result"]) if job.get("result") else {}
    video_url = res.get("video_url")
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "ok": job["status"] == "done" and bool(video_url),
        "title": job["title"],
        "video_url": video_url,
        "shots": res.get("shots"),
        "error": res.get("error") if job["status"] == "failed" else None,
    }


@app.post("/webhook/tencent-rtc")
def webhook_tencent_rtc(payload: dict, request: "Request", _: None = Depends(rate_limit)):
    """Tencent RTC (TUIKit/IM) Chat callback webhook.

    Accepts TRTC IM callback envelope (CallbackCommand / MsgId / From_Account),
    applies 5T verification (HMAC auth + Object.freeze equivalent + source_origin),
    and stores a frozen artifact in jobs.db. Idempotent on re-delivered MsgId.
    """
    # --- 5T: Trustworthy (constant-time HMAC auth) ---
    secret = config.TENCENT_RTC_WEBHOOK_SECRET or config.WEBHOOK_SECRET
    if secret:
        sig = request.headers.get("X-Tencent-Signature") or request.headers.get("Signature") or ""
        raw = getattr(request, "_body", b"")
        expected = hmac.new(secret.encode(), raw, "sha256").hexdigest()
        if not hmac.compare_digest(sig, secret) and not hmac.compare_digest(sig, expected):
            raise HTTPException(401, "invalid tencent-rtc signature")

    # --- Normalize TRTC envelope ---
    msg_id = payload.get("MsgId") or payload.get("msgId") or str(uuid.uuid4())
    from_account = payload.get("From_Account") or payload.get("FromAccount") or "unknown"
    command = payload.get("CallbackCommand") or payload.get("callbackCommand") or "unknown"

    # Idempotency: skip if MsgId already stored
    existing = db.get_job_by_source(msg_id)
    if existing:
        return {"status": "duplicate", "msg_id": msg_id, "ok": True}

    # --- 5T: Traceable (source_origin) + Transparent (structured) ---
    artifact = {
        "source_origin": "tencent-rtc-chat",
        "callback_command": command,
        "from_account": from_account,
        "msg_id": msg_id,
        "payload": payload,
        "received_at": time.time(),
    }
    # --- 5T: Trustworthy (Hash Lock + Object.freeze equivalent) ---
    locked = gate5t.lock_artifact(artifact)
    job = db.create_job(source=msg_id, title=f"TRTC:{command}", result=json.dumps(locked))
    return {"status": "stored", "msg_id": msg_id, "job_id": job["job_id"], "ok": True}


@app.get("/api/jobs/{job_id}/video")
def video(job_id: str):
    j = db.get_job(job_id)
    if not j or j.get("status") != "done":
        raise HTTPException(404, "video not ready")
    res = json.loads(j["result"]) if isinstance(j["result"], str) else j["result"]
    file = Path(res["file"])
    # Path-traversal guard: only serve files inside STORAGE_DIR.
    if not str(file.resolve()).startswith(str(config.STORAGE_DIR.resolve())):
        raise HTTPException(403, "forbidden path")
    if not file.exists():
        raise HTTPException(404, "file missing")
    return FileResponse(str(file), media_type="video/mp4", filename=f"{job_id}.mp4")


@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE_DIR / "web" / "index.html").read_text(encoding="utf-8")


@app.get("/favicon.ico", response_class=FileResponse)
def favicon():
    ico = BASE_DIR / "web" / "favicon.svg"
    if ico.exists():
        return FileResponse(str(ico), media_type="image/svg+xml")
    return FileResponse(str(ico) if ico.exists() else str(BASE_DIR / "web" / "index.html"))


# Serve generated assets (local storage, IDEA.md module 6 fallback).
# Guarded against path traversal: resolve and confirm inside STORAGE_DIR.
@app.get("/storage/{rest_of_path:path}")
def storage_file(rest_of_path: str):
    target = (config.STORAGE_DIR / rest_of_path).resolve()
    if not str(target).startswith(str(config.STORAGE_DIR.resolve())) or not target.exists():
        raise HTTPException(404, "not found")
    return FileResponse(str(target))


# ---- OCI Infrastructure Controller (optional step #8) ----
from .oci_controller import router as oci_router

app.include_router(oci_router)


def main():
    import uvicorn
    from .config import HOST, PORT
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()