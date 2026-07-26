"""AI Station — FastAPI control center.

Exposes the orchestration hub (IDEA.md module 1) over HTTP so it can be
driven by n8n webhooks, the built-in web UI, or any client.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import hmac

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import db, pipeline
from . import config
from .config import BASE_DIR, feature_summary, setup_logging, log

app = FastAPI(title="AI Station", version="0.1.0")
db.init_db()
setup_logging()  # TODO pillar 6: structured logging (no-op if already configured)


class ScriptIn(BaseModel):
    title: str = "Untitled"
    script: str
    brand_preset: str | None = None  # e.g. "sushi_dr" for 壽司博士 Dr. Source


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
def health():
    return {"status": "ok", "features": feature_summary()}


@app.get("/api/metrics")
def metrics():
    """Lightweight pipeline observability (TODO pillar 6): throughput,
    reliability, and per-brand activity aggregated from the job store."""
    from . import metrics as _metrics

    return _metrics.compute_metrics()


@app.post("/api/jobs")
def create_job(payload: ScriptIn, request: Request, _: None = Depends(rate_limit)):
    """Submit a job. Returns immediately (202) with the job id; the heavy
    render runs in the background so long scripts don't block the request.
    Poll GET /api/jobs/{id} for status."""
    if not payload.script.strip():
        raise HTTPException(400, "script is empty")
    job_id = pipeline.submit(payload.script, payload.title, brand_preset=payload.brand_preset)
    return {"job_id": job_id, "status": "queued"}


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
class WebhookIn(BaseModel):
    title: str = "Untitled"
    script: str | None = None
    text: str | None = None   # alias accepted by some n8n setups
    brand_preset: str | None = None  # "sushi_dr" to render on-brand

    @property
    def body(self) -> str:
        return self.script or self.text or ""


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


# Serve generated assets (local storage, IDEA.md module 6 fallback).
# Guarded against path traversal: resolve and confirm inside STORAGE_DIR.
@app.get("/storage/{rest_of_path:path}")
def storage_file(rest_of_path: str):
    target = (config.STORAGE_DIR / rest_of_path).resolve()
    if not str(target).startswith(str(config.STORAGE_DIR.resolve())) or not target.exists():
        raise HTTPException(404, "not found")
    return FileResponse(str(target))


def main():
    import uvicorn
    from .config import HOST, PORT
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
