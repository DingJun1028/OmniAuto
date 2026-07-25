"""AI Station — FastAPI control center.

Exposes the orchestration hub (IDEA.md module 1) over HTTP so it can be
driven by n8n webhooks, the built-in web UI, or any client.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, pipeline
from .config import BASE_DIR, STORAGE_DIR, feature_summary

app = FastAPI(title="AI Station", version="0.1.0")
db.init_db()


class ScriptIn(BaseModel):
    title: str = "Untitled"
    script: str


@app.get("/api/health")
def health():
    return {"status": "ok", "features": feature_summary()}


@app.post("/api/jobs")
def create_job(payload: ScriptIn):
    if not payload.script.strip():
        raise HTTPException(400, "script is empty")
    job = pipeline.enqueue(payload.script, payload.title)
    return job


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

    @property
    def body(self) -> str:
        return self.script or self.text or ""


@app.post("/webhook/n8n")
def webhook_n8n(payload: WebhookIn):
    script = payload.body
    if not script.strip():
        raise HTTPException(400, "missing 'script' or 'text'")
    job = pipeline.enqueue(script, payload.title)
    # Return a compact, n8n-friendly shape.
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
    path = Path(j["result"]) if isinstance(j["result"], str) else None
    import json
    res = json.loads(j["result"]) if isinstance(j["result"], str) else j["result"]
    file = Path(res["file"])
    if not file.exists():
        raise HTTPException(404, "file missing")
    return FileResponse(str(file), media_type="video/mp4", filename=f"{job_id}.mp4")


@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE_DIR / "web" / "index.html").read_text(encoding="utf-8")


# Serve generated assets (local storage, IDEA.md module 6 fallback).
app.mount("/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")


def main():
    import uvicorn
    from .config import HOST, PORT
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
