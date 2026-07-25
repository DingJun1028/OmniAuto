"""AI Station — FastAPI control center.

Exposes the orchestration hub (IDEA.md module 1) over HTTP so it can be
driven by n8n webhooks, the built-in web UI, or any client.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import db, pipeline
from . import config
from .config import BASE_DIR, STORAGE_DIR, feature_summary

app = FastAPI(title="AI Station", version="0.1.0")
db.init_db()


class ScriptIn(BaseModel):
    title: str = "Untitled"
    script: str
    brand_preset: str | None = None  # e.g. "sushi_dr" for 壽司博士 Dr. Source


@app.get("/api/health")
def health():
    return {"status": "ok", "features": feature_summary()}


@app.post("/api/jobs")
def create_job(payload: ScriptIn):
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
    """If WEBHOOK_SECRET is configured, require it via header or query."""
    secret = config.WEBHOOK_SECRET
    if not secret:
        return
    x_key = request.headers.get("X-AI-Station-Key")
    key = request.query_params.get("key")
    if x_key != secret and key != secret:
        raise HTTPException(401, "invalid or missing webhook key")


@app.post("/webhook/n8n")
def webhook_n8n(payload: WebhookIn, request: "Request"):
    _check_webhook_auth(request)
    script = payload.body
    if not script.strip():
        raise HTTPException(400, "missing 'script' or 'text'")
    # Webhook stays synchronous (n8n awaits the result), but runs via the
    # same background pool so very long scripts still complete.
    job = pipeline.enqueue(script, payload.title, brand_preset=payload.brand_preset)
    res = json.loads(job["result"]) if job.get("result") else {}
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "title": job["title"],
        "video_url": res.get("video_url"),
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
    if not str(file.resolve()).startswith(str(STORAGE_DIR.resolve())):
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
    target = (STORAGE_DIR / rest_of_path).resolve()
    if not str(target).startswith(str(STORAGE_DIR.resolve())) or not target.exists():
        raise HTTPException(404, "not found")
    return FileResponse(str(target))


def main():
    import uvicorn
    from .config import HOST, PORT
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
